# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal


class OtmPlacementPortalController(CustomerPortal):

    def _get_candidate(self):
        """Return the candidate record owned by the logged-in portal user,
        auto-linking by email on first visit. Ownership is always verified
        against the current session's partner, never a URL parameter."""
        partner = request.env.user.partner_id
        Candidate = request.env["otm.placement.candidate"].sudo()
        candidate = Candidate.search([("partner_id", "=", partner.id)], limit=1)
        if not candidate and partner.email:
            candidate = Candidate.search(
                [("email", "=", partner.email), ("partner_id", "=", False)],
                limit=1, order="registration_date desc",
            )
            if candidate:
                candidate.write({"partner_id": partner.id})
        return candidate

    @http.route(["/my-placement", "/my-placement/"], type="http",
                auth="user", website=True)
    def my_placement_home(self, **kwargs):
        candidate = self._get_candidate()
        if not candidate:
            return request.render(
                "otm_placement_management.placement_portal_no_record", {}
            )
        values = {
            "candidate": candidate,
            "upcoming": candidate.mock_interview_ids.filtered(
                lambda i: i.status in ("scheduled", "confirmed")
            )[:1],
            "placement_record": candidate.placement_record_ids[:1],
        }
        return request.render("otm_placement_management.placement_portal_home", values)

    @http.route("/my-placement/interview", type="http", auth="user", website=True)
    def my_placement_interview(self, **kwargs):
        candidate = self._get_candidate()
        if not candidate:
            return request.redirect("/my-placement")
        interview = candidate.mock_interview_ids.filtered(
            lambda i: i.status in ("scheduled", "confirmed")
        )[:1]
        values = {
            "candidate": candidate,
            "interview": interview,
            "progress": candidate._get_mock_interview_display_status(),
        }
        return request.render(
            "otm_placement_management.placement_portal_interview", values
        )

    @http.route("/my-placement/interview/request-reattempt", type="http",
                methods=["POST"], auth="user", website=True, csrf=True)
    def my_placement_request_reattempt(self, reason=None, new_slot_id=None, **kwargs):
        candidate = self._get_candidate()
        if candidate:
            last_completed = candidate.mock_interview_ids.filtered(
                lambda i: i.status == "completed"
            ).sorted("scheduled_start", reverse=True)[:1]
            already_pending = bool(
                candidate._get_requested_reattempt()
                or candidate._get_pending_reattempt_approval()
            )
            if last_completed and not already_pending:
                vals = {
                    "interview_id": last_completed.id,
                    "request_type": "reattempt",
                    "reason": reason or "",
                }
                slot_id = int(new_slot_id) if str(new_slot_id or "").isdigit() else False
                if slot_id:
                    vals["new_slot_id"] = slot_id
                request.env["otm.placement.reschedule.request"].sudo().create(vals)
        return request.redirect("/my-placement/interview")

    @http.route("/my-placement/interview/cancel", type="http", methods=["POST"],
                auth="user", website=True, csrf=True)
    def my_placement_interview_cancel(self, interview_id=None, reason=None, **kwargs):
        candidate = self._get_candidate()
        interview_id = int(interview_id) if str(interview_id or "").isdigit() else False
        if candidate and interview_id:
            interview = request.env["otm.placement.mock.interview"].sudo().browse(
                interview_id
            )
            if interview.exists() and interview.candidate_id.id == candidate.id:
                request.env["otm.placement.reschedule.request"].sudo().create({
                    "interview_id": interview.id,
                    "request_type": "cancel",
                    "reason": reason or "",
                })
        return request.redirect("/my-placement/interview")

    @http.route("/my-placement/interview/reschedule", type="http", methods=["POST"],
                auth="user", website=True, csrf=True)
    def my_placement_interview_reschedule(self, interview_id=None, new_slot_id=None,
                                            reason=None, **kwargs):
        candidate = self._get_candidate()
        interview_id = int(interview_id) if str(interview_id or "").isdigit() else False
        new_slot_id = int(new_slot_id) if str(new_slot_id or "").isdigit() else False
        if candidate and interview_id and new_slot_id:
            interview = request.env["otm.placement.mock.interview"].sudo().browse(
                interview_id
            )
            if interview.exists() and interview.candidate_id.id == candidate.id:
                request.env["otm.placement.reschedule.request"].sudo().create({
                    "interview_id": interview.id,
                    "request_type": "reschedule",
                    "new_slot_id": new_slot_id,
                    "reason": reason or "",
                })
        return request.redirect("/my-placement/interview")
