# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class OtmPlacementRescheduleRequest(models.Model):
    _name = "otm.placement.reschedule.request"
    _description = "Interview Cancellation / Reschedule Request"
    _order = "create_date desc"

    interview_id = fields.Many2one(
        "otm.placement.mock.interview", string="Interview", required=True,
        ondelete="cascade", index=True,
    )
    candidate_id = fields.Many2one(
        "otm.placement.candidate", string="Candidate",
        related="interview_id.candidate_id", store=True,
    )
    request_type = fields.Selection(
        [("cancel", "Cancel"), ("reschedule", "Reschedule")],
        required=True,
        default="reschedule",
    )
    current_slot_id = fields.Many2one(
        "otm.placement.interview.slot", string="Current Slot",
        related="interview_id.slot_id", store=True,
    )
    new_slot_id = fields.Many2one(
        "otm.placement.interview.slot", string="New Requested Slot"
    )
    reason = fields.Text()
    status = fields.Selection(
        [
            ("requested", "Requested"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
            ("completed", "Completed"),
        ],
        default="requested",
    )

    def action_approve(self):
        for request in self:
            interview = request.interview_id
            if request.request_type == "cancel":
                interview.action_cancel()
            else:
                if not request.new_slot_id:
                    raise UserError(_("Please select a new slot before approving."))
                self.env["otm.placement.mock.interview"].sudo().book_slot(
                    interview.candidate_id, request.new_slot_id
                )
                interview.action_cancel()
                interview.status = "rescheduled"
                interview._send_notification("interview_rescheduled_mail_template")
            request.status = "approved"

    def action_reject(self):
        self.write({"status": "rejected"})
