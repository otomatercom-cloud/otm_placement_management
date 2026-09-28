# -*- coding: utf-8 -*-
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
    """Never trust a browser-supplied id's type: coerce safely."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class OtmPlacementMainController(http.Controller):

    # ------------------------------------------------------------------
    # Public registration page
    # ------------------------------------------------------------------
    @http.route("/placement/register", type="http", auth="public",
                website=True, sitemap=True)
    def placement_register(self, **kwargs):
        programs = request.env["otm.placement.program"].sudo().search(
            [], order="sequence, name"
        )
        support_areas = request.env["otm.placement.support.area"].sudo().search(
            [], order="sequence, name"
        )
        years = request.env["otm.placement.candidate"].sudo()._get_admission_year_selection()
        values = {
            "programs": programs,
            "support_areas": support_areas,
            "years_json": json.dumps([y[0] for y in years]),
        }
        return request.render(
            "otm_placement_management.placement_register_page", values
        )

    # ------------------------------------------------------------------
    # Step submit: create the candidate record
    # ------------------------------------------------------------------
    @http.route("/placement/register/submit", type="http", methods=["POST"],
                auth="public", website=True, csrf=False)
    def placement_register_submit(self, **kwargs):
        try:
            data = json.loads(request.httprequest.get_data())
        except ValueError:
            return _json_response({"ok": False, "error": "Invalid request."}, 400)

        request.validate_csrf(data.get("csrf_token"))

        name = (data.get("name") or "").strip()
        phone = (data.get("phone") or "").strip()
        email = (data.get("email") or "").strip()
        program_id = _to_int(data.get("program_id"))
        interview_preference = data.get("interview_preference")

        errors = {}
        if not name:
            errors["name"] = "Please enter your name."
        if not phone:
            errors["phone"] = "Please enter a valid WhatsApp number."
        if not email or "@" not in email:
            errors["email"] = "Please enter a valid email address."
        if not program_id:
            errors["program_id"] = "Please select your program."
        if interview_preference not in ("online", "offline"):
            errors["interview_preference"] = "Please select an interview preference."

        if errors:
            return _json_response({"ok": False, "errors": errors}, 400)

        program = request.env["otm.placement.program"].sudo().browse(program_id)
        if not program.exists():
            return _json_response(
                {"ok": False, "errors": {"program_id": "Please select your program."}}, 400
            )

        support_area_ids = [
            _to_int(sid) for sid in (data.get("support_area_ids") or [])
        ]
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

        # Same phone+email as an existing registration (e.g. the candidate
        # re-submitted after a refresh, or double-clicked Continue): update
        # that record and carry on, rather than hitting the unique
        # constraint and surfacing a raw 500 to the visitor.
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
            _logger.exception("Placement registration failed")
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
    # Slot availability (public, safe fields only)
    # ------------------------------------------------------------------
    @http.route("/placement/slots", type="http", methods=["GET"],
                auth="public", website=True, csrf=False)
    def placement_slots(self, date=None, mode=None, **kwargs):
        if mode not in ("online", "offline"):
            return _json_response([])

        domain = [("mode", "=", mode), ("active", "=", True)]
        if date:
            domain.append(("date", "=", date))
        slots = request.env["otm.placement.interview.slot"].sudo().search(
            domain, order="start_datetime"
        )
        data = [
            slot._public_slot_data() for slot in slots
            if slot.slot_status != "past"
        ]
        return _json_response(data)

    # ------------------------------------------------------------------
    # Booking (server-side revalidated, atomic)
    # ------------------------------------------------------------------
    @http.route("/placement/book", type="http", methods=["POST"],
                auth="public", website=True, csrf=False)
    def placement_book(self, **kwargs):
        try:
            data = json.loads(request.httprequest.get_data())
        except ValueError:
            return _json_response({"ok": False, "error": "Invalid request."}, 400)

        request.validate_csrf(data.get("csrf_token"))

        candidate_id = _to_int(data.get("candidate_id"))
        slot_id = _to_int(data.get("slot_id"))
        token = data.get("token")

        if not candidate_id or not slot_id or not token:
            return _json_response(
                {"ok": False, "error": "Missing booking details."}, 400
            )

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
            _logger.exception("Placement booking failed")
            return _json_response(
                {"ok": False, "error": "Something went wrong. Please try again."}, 500
            )

        # Build the date/time labels from the interview's own scheduled_start
        # (set once at booking time, never touched by the raw-SQL counter
        # update) rather than re-reading the slot - the slot's counter
        # fields were deliberately left uninvalidated in book_slot(), see
        # ODOO19_RULES finding #70.
        tz_start = fields.Datetime.context_timestamp(
            interview, interview.scheduled_start
        )
        return _json_response({
            "ok": True,
            "interview_id": interview.id,
            "candidate_name": candidate.name,
            "program": candidate.program_id.name,
            "mode": interview.mode,
            "date_label": tz_start.strftime("%d %B %Y"),
            "time_label": tz_start.strftime("%I:%M %p"),
            "interviewer": interview.interviewer_id.name or "",
            "venue": interview.venue or "",
            "success_url": "/placement/booking/success/%s" % candidate.access_token,
        })

    # ------------------------------------------------------------------
    # Booking success / confirmation page (token secured, never raw ids)
    # ------------------------------------------------------------------
    @http.route("/placement/booking/success/<string:token>", type="http",
                auth="public", website=True, sitemap=False)
    def placement_booking_success(self, token, **kwargs):
        candidate = request.env["otm.placement.candidate"].sudo().search(
            [("access_token", "=", token)], limit=1
        )
        if not candidate:
            return request.not_found()
        interview = candidate.mock_interview_ids.filtered(
            lambda i: i.status not in ("cancelled",)
        )[:1]
        values = {"candidate": candidate, "interview": interview}
        return request.render(
            "otm_placement_management.placement_booking_success_page", values
        )
