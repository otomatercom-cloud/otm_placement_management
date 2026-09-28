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
        [
            ("cancel", "Cancel"),
            ("reschedule", "Reschedule"),
            ("reattempt", "Mock Interview Re-attempt"),
        ],
        required=True,
        default="reschedule",
    )
    current_slot_id = fields.Many2one(
        "otm.placement.interview.slot", string="Current Slot",
        related="interview_id.slot_id", store=True,
    )
    new_slot_id = fields.Many2one(
        "otm.placement.interview.slot", string="New Requested Slot",
        help="Reschedule: the slot to move to. Re-attempt: leave blank to "
             "just grant the candidate permission to pick their own new slot, "
             "or set a slot here to book it directly on approval.",
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
                request.status = "approved"
            elif request.request_type == "reschedule":
                if not request.new_slot_id:
                    raise UserError(_("Please select a new slot before approving."))
                self.env["otm.placement.mock.interview"].sudo().book_slot(
                    interview.candidate_id, request.new_slot_id,
                    bypass_active_check=True,
                )
                interview.action_cancel()
                interview.status = "rescheduled"
                interview._send_notification("interview_rescheduled_mail_template")
                request.status = "approved"
            else:  # reattempt
                if request.new_slot_id:
                    # Manager picked the new slot directly: book it now and
                    # close the request out in one step.
                    self.env["otm.placement.mock.interview"].sudo().book_slot(
                        interview.candidate_id, request.new_slot_id,
                        bypass_active_check=True,
                    )
                    request.status = "completed"
                else:
                    # Grant permission only: the candidate comes back and
                    # picks their own slot, which book_slot() allows once it
                    # finds this approved, still-unconsumed request.
                    request.status = "approved"

    def action_reject(self):
        self.write({"status": "rejected"})
