# -*- coding: utf-8 -*-
"""
JSON endpoints for the Next.js Placement Console BFF
(otm_placement_frontend). These are deliberately separate from the public
website routes in main.py: they are not meant to be opened in a browser,
so there is no Odoo session/CSRF token to validate. Instead every request
must carry the shared secret configured in System Parameters as
`otm_placement_management.bff_secret`, sent as the `X-Otm-Bff-Secret`
header.

Each route is a thin wrapper that delegates to the exact same sudo'd model
methods the website controller (main.py) already uses, so booking
atomicity, the one-active-interview rule, email/WhatsApp notifications and
all other validated business logic live in one place, not two.
"""
import json
import logging

from odoo import fields, http
from odoo.exceptions import UserError
from odoo.http import request

_logger = logging.getLogger(__name__)


def _json_response(payload, status=200):
    return request.make_response(
        json.dumps(payload),
        headers=[("Content-Type", "application/json")],
        status=status,
    )


def _to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _check_secret():
    """True if the request carries the configured BFF shared secret."""
    configured = (
        request.env["ir.config_parameter"]
        .sudo()
        .get_param("otm_placement_management.bff_secret")
    )
    if not configured:
        return False
    supplied = request.httprequest.headers.get("X-Otm-Bff-Secret")
    return bool(supplied) and supplied == configured


class OtmPlacementBffController(http.Controller):

    def _unauthorized(self):
        return _json_response({"ok": False, "error": "Unauthorized."}, 401)

    # ------------------------------------------------------------------
    # Lookup data for the registration form's dropdowns
    # ------------------------------------------------------------------
    @http.route("/api/placement/meta", type="http", methods=["GET"],
                auth="public", csrf=False)
    def api_meta(self, **kwargs):
        if not _check_secret():
            return self._unauthorized()
        Candidate = request.env["otm.placement.candidate"].sudo()
        programs = request.env["otm.placement.program"].sudo().search(
            [], order="sequence, name"
        )
        support_areas = request.env["otm.placement.support.area"].sudo().search(
            [], order="sequence, name"
        )
        years = Candidate._get_admission_year_selection()
        return _json_response({
            "ok": True,
            "programs": [{"id": p.id, "name": p.name} for p in programs],
            "support_areas": [{"id": s.id, "name": s.name} for s in support_areas],
            "admission_years": [y[0] for y in years],
        })

    # ------------------------------------------------------------------
    # Register a candidate (mirrors /placement/register/submit)
    # ------------------------------------------------------------------
    @http.route("/api/placement/candidates/register", type="http",
                methods=["POST"], auth="public", csrf=False)
    def api_register(self, **kwargs):
        if not _check_secret():
            return self._unauthorized()
        try:
            data = json.loads(request.httprequest.get_data())
        except ValueError:
            return _json_response({"ok": False, "error": "Invalid request."}, 400)

        name = (data.get("name") or "").strip()
        phone = (data.get("phone") or "").strip()
        email = (data.get("email") or "").strip()
        program_id = _to_int(data.get("program_id"))
        raw_preference = data.get("interview_preference")
        interview_preference = raw_preference if raw_preference in ("online", "offline") else False

        errors = {}
        if not name:
            errors["name"] = "Please enter your name."
        if not phone:
            errors["phone"] = "Please enter a valid WhatsApp number."
        if not email or "@" not in email:
            errors["email"] = "Please enter a valid email address."
        if not program_id:
            errors["program_id"] = "Please select your program."
        if errors:
            return _json_response({"ok": False, "errors": errors}, 400)

        program = request.env["otm.placement.program"].sudo().browse(program_id)
        if not program.exists():
            return _json_response(
                {"ok": False, "errors": {"program_id": "Please select your program."}}, 400
            )

        support_area_ids = [_to_int(sid) for sid in (data.get("support_area_ids") or [])]
        support_area_ids = [sid for sid in support_area_ids if sid]

        vals = {
            "name": name,
            "phone": phone,
            "email": email,
            "program_id": program.id,
            "admission_year": data.get("admission_year") or False,
            "qualification_status": data.get("qualification_status") or False,
            "employment_status": data.get("employment_status") or False,
            "interview_preference": interview_preference,
            "support_area_ids": [(6, 0, support_area_ids)],
            "additional_support": data.get("additional_support") or False,
        }
        if data.get("employment_status") == "employed":
            vals["company_name"] = data.get("company_name") or False
            vals["designation"] = data.get("designation") or False

        Candidate = request.env["otm.placement.candidate"].sudo()
        candidate = Candidate.search(
            [("phone", "=", phone), ("email", "=", email)], limit=1
        )
        try:
            if candidate:
                candidate.write(vals)
            else:
                candidate = Candidate.create(vals)
        except Exception:
            request.env.cr.rollback()
            _logger.exception("BFF placement registration failed")
            return _json_response(
                {"ok": False, "error": "Something went wrong. Please try again."}, 500
            )

        candidate._send_registration_confirmation()

        return _json_response({
            "ok": True,
            "candidate_id": candidate.id,
            "token": candidate.access_token,
            "name": candidate.name,
            "program": candidate.program_id.name,
            "mode": candidate.interview_preference,
        })

    # ------------------------------------------------------------------
    # Slot availability (mirrors /placement/slots)
    # ------------------------------------------------------------------
    @http.route("/api/placement/slots", type="http", methods=["GET"],
                auth="public", csrf=False)
    def api_slots(self, mode=None, date=None, **kwargs):
        if not _check_secret():
            return self._unauthorized()
        if mode not in ("online", "offline"):
            return _json_response({"ok": False, "error": "mode must be online or offline."}, 400)

        domain = [("mode", "=", mode), ("active", "=", True)]
        if date:
            domain.append(("date", "=", date))
        slots = request.env["otm.placement.interview.slot"].sudo().search(
            domain, order="start_datetime"
        )
        data = [s._public_slot_data() for s in slots if s.slot_status != "past"]
        return _json_response({"ok": True, "slots": data})

    # ------------------------------------------------------------------
    # Book a slot (mirrors /placement/book)
    # ------------------------------------------------------------------
    @http.route("/api/placement/interviews/book", type="http", methods=["POST"],
                auth="public", csrf=False)
    def api_book(self, **kwargs):
        if not _check_secret():
            return self._unauthorized()
        try:
            data = json.loads(request.httprequest.get_data())
        except ValueError:
            return _json_response({"ok": False, "error": "Invalid request."}, 400)

        candidate_id = _to_int(data.get("candidate_id"))
        slot_id = _to_int(data.get("slot_id"))
        token = data.get("token")
        if not candidate_id or not slot_id or not token:
            return _json_response({"ok": False, "error": "Missing booking details."}, 400)

        candidate = request.env["otm.placement.candidate"].sudo().browse(candidate_id)
        if not candidate.exists() or candidate.access_token != token:
            return _json_response({"ok": False, "error": "Invalid session."}, 403)

        slot = request.env["otm.placement.interview.slot"].sudo().browse(slot_id)
        if not slot.exists():
            return _json_response(
                {"ok": False, "error": "This interview slot no longer exists."}, 404
            )

        try:
            interview = request.env["otm.placement.mock.interview"].sudo().book_slot(
                candidate, slot
            )
            request.env.cr.commit()
        except UserError as exc:
            request.env.cr.rollback()
            return _json_response({"ok": False, "error": str(exc)}, 409)
        except Exception:
            request.env.cr.rollback()
            _logger.exception("BFF placement booking failed")
            return _json_response(
                {"ok": False, "error": "Something went wrong. Please try again."}, 500
            )

        tz_start = fields.Datetime.context_timestamp(interview, interview.scheduled_start)
        return _json_response({
            "ok": True,
            "interview_id": interview.id,
            "candidate_name": candidate.name,
            "program": candidate.program_id.name,
            "mode": interview.mode,
            "date_label": tz_start.strftime("%d %B %Y"),
            "time_label": tz_start.strftime("%I:%M %p"),
            "interviewer": interview.interviewer_id.name or interview.external_interviewer_name or "",
            "venue": interview.venue or "",
        })

    # ------------------------------------------------------------------
    # Lookup by phone + email (mirrors /placement/book-interview/lookup)
    # ------------------------------------------------------------------
    @http.route("/api/placement/candidates/lookup", type="http", methods=["POST"],
                auth="public", csrf=False)
    def api_lookup(self, **kwargs):
        if not _check_secret():
            return self._unauthorized()
        try:
            data = json.loads(request.httprequest.get_data())
        except ValueError:
            return _json_response({"ok": False, "error": "Invalid request."}, 400)

        phone = (data.get("phone") or "").strip()
        email = (data.get("email") or "").strip()
        if not phone or not email:
            return _json_response(
                {"ok": False, "error": "Please enter both your WhatsApp number and email."}, 400
            )

        candidate = request.env["otm.placement.candidate"].sudo().search(
            [("phone", "=", phone), ("email", "=", email)], limit=1
        )
        if not candidate:
            return _json_response({
                "ok": False,
                "error": "We couldn't find a registration with that WhatsApp number "
                         "and email. Please check for typos, or register first.",
            }, 404)

        progress = candidate._get_mock_interview_display_status()
        return _json_response({
            "ok": True,
            "candidate_id": candidate.id,
            "token": candidate.access_token,
            "name": candidate.name,
            "program": candidate.program_id.name,
            "status": progress["code"],
            "status_label": progress["label"],
        })

    # ------------------------------------------------------------------
    # Status by token (for the candidate's self-service status page)
    # ------------------------------------------------------------------
    @http.route("/api/placement/candidates/status", type="http", methods=["GET"],
                auth="public", csrf=False)
    def api_status(self, token=None, **kwargs):
        if not _check_secret():
            return self._unauthorized()
        if not token:
            return _json_response({"ok": False, "error": "Missing token."}, 400)

        candidate = request.env["otm.placement.candidate"].sudo().search(
            [("access_token", "=", token)], limit=1
        )
        if not candidate:
            return _json_response({"ok": False, "error": "Not found."}, 404)

        progress = candidate._get_mock_interview_display_status()
        active = candidate.mock_interview_ids.filtered(
            lambda i: i.status in ("scheduled", "confirmed")
        )[:1]
        interview_data = None
        if active:
            tz_start = fields.Datetime.context_timestamp(active, active.scheduled_start)
            interview_data = {
                "id": active.id,
                "mode": active.mode,
                "status": active.status,
                "date_label": tz_start.strftime("%d %B %Y"),
                "time_label": tz_start.strftime("%I:%M %p"),
                "interviewer": active.interviewer_display_name,
                "venue": active.venue or "",
                "meeting_url": active.meeting_url or "",
            }
        placement = candidate.placement_record_ids[:1]
        return _json_response({
            "ok": True,
            "candidate": {
                "id": candidate.id,
                "name": candidate.name,
                "program": candidate.program_id.name,
                "stage": candidate.stage,
            },
            "status": progress["code"],
            "status_label": progress["label"],
            "interview": interview_data,
            "placed": bool(placement),
        })

    # ------------------------------------------------------------------
    # Request a reschedule / re-attempt (mirrors the public reattempt route)
    # ------------------------------------------------------------------
    @http.route("/api/placement/interviews/request-reattempt", type="http",
                methods=["POST"], auth="public", csrf=False)
    def api_request_reattempt(self, **kwargs):
        if not _check_secret():
            return self._unauthorized()
        try:
            data = json.loads(request.httprequest.get_data())
        except ValueError:
            return _json_response({"ok": False, "error": "Invalid request."}, 400)

        candidate_id = _to_int(data.get("candidate_id"))
        token = data.get("token")
        candidate = request.env["otm.placement.candidate"].sudo().browse(candidate_id)
        if not candidate.exists() or not token or candidate.access_token != token:
            return _json_response({"ok": False, "error": "Invalid session."}, 403)

        slot_id = _to_int(data.get("slot_id"))
        slot = request.env["otm.placement.interview.slot"].sudo().browse(slot_id) if slot_id else None
        if slot_id and not (slot and slot.exists()):
            return _json_response(
                {"ok": False, "error": "That slot is no longer available. Please pick another."}, 404
            )

        last_completed = candidate.mock_interview_ids.filtered(
            lambda i: i.status == "completed"
        ).sorted("scheduled_start", reverse=True)[:1]
        already_pending = bool(
            candidate._get_requested_reattempt()
            or candidate._get_pending_reattempt_approval()
        )
        if not last_completed or already_pending:
            return _json_response({"ok": True})

        vals = {
            "interview_id": last_completed.id,
            "request_type": "reattempt",
            "reason": (data.get("reason") or "").strip(),
        }
        if slot:
            vals["new_slot_id"] = slot.id
        request.env["otm.placement.reschedule.request"].sudo().create(vals)
        request.env.cr.commit()
        return _json_response({"ok": True})
