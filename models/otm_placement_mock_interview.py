# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class OtmPlacementMockInterview(models.Model):
    _name = "otm.placement.mock.interview"
    _description = "Placement Mock Interview"
    _inherit = ["mail.thread"]
    _order = "scheduled_start desc"

    candidate_id = fields.Many2one(
        "otm.placement.candidate", string="Candidate", required=True,
        ondelete="cascade", tracking=True, index=True,
    )
    slot_id = fields.Many2one(
        "otm.placement.interview.slot", string="Interview Slot", index=True
    )
    mode = fields.Selection(
        [("online", "Online"), ("offline", "Offline")], required=True, tracking=True
    )
    interviewer_id = fields.Many2one("res.users", string="Interviewer", tracking=True)
    external_interviewer_name = fields.Char(string="External Interviewer", tracking=True)
    external_interviewer_contact = fields.Char(string="External Interviewer Contact")
    interviewer_display_name = fields.Char(
        string="Interviewer Shown", compute="_compute_interviewer_display_name", store=True,
        help="Interviewer name shown to candidates and in list views: the "
             "internal Interviewer if set, otherwise the External Interviewer.",
    )
    scheduled_start = fields.Datetime(string="Scheduled Start", tracking=True)
    scheduled_end = fields.Datetime(string="Scheduled End")
    meeting_platform = fields.Selection(
        [
            ("google_meet", "Google Meet"),
            ("zoom", "Zoom"),
            ("teams", "Microsoft Teams"),
            ("other", "Other"),
        ],
        string="Meeting Platform",
    )
    meeting_url = fields.Char(string="Meeting URL")
    venue = fields.Char(string="Venue")

    status = fields.Selection(
        [
            ("scheduled", "Scheduled"),
            ("confirmed", "Confirmed"),
            ("completed", "Completed"),
            ("cancelled", "Cancelled"),
            ("no_show", "No Show"),
            ("rescheduled", "Rescheduled"),
        ],
        default="scheduled",
        tracking=True,
    )
    interviewer_notes = fields.Text(string="Interviewer Notes")
    candidate_feedback = fields.Text(string="Candidate Feedback")
    result = fields.Selection(
        [
            ("needs_improvement", "Needs Improvement"),
            ("interview_ready", "Interview Ready"),
            ("follow_up_required", "Follow-up Required"),
            ("recommended", "Recommended for Placement"),
        ],
        string="Result",
        tracking=True,
    )
    reminder_sent = fields.Boolean(default=False, copy=False)

    @api.depends("interviewer_id", "external_interviewer_name")
    def _compute_interviewer_display_name(self):
        for interview in self:
            interview.interviewer_display_name = (
                interview.interviewer_id.name or interview.external_interviewer_name or ""
            )

    @api.model
    def book_slot(self, candidate, slot, bypass_active_check=False):
        """Atomically book `slot` (a otm.placement.interview.slot recordset)
        for `candidate`. Must be called sudo()'d from a public/portal
        controller. Raises UserError if the slot is no longer available.
        Uses a row-level lock so two simultaneous requests cannot both
        book the last remaining seat (server-side, never trust JS alone).

        Also enforces the one-active-interview-at-a-time rule: a candidate
        who already has a scheduled/confirmed interview, or whose last
        interview is completed and hasn't been granted re-attempt
        permission, cannot self-book another slot here (see
        `candidate._check_can_self_book()`). `bypass_active_check=True` is
        for the two internal call sites that legitimately create a second
        interview on the candidate's behalf after staff approval (reschedule
        and manager-assigned re-attempt) - never pass it from a
        public/portal controller.
        """
        candidate.ensure_one()
        slot.ensure_one()
        if not bypass_active_check:
            candidate._check_can_self_book()

        # Flush ALL of slot's pending ORM state (not just capacity/
        # booked_count) before the raw SQL below. This matters even for
        # fields we are not about to touch: a stored compute field such as
        # available_count can be computed lazily in-cache the first time
        # any caller reads it, and stay queued as a pending write until the
        # next flush - if that pending write is still queued when we later
        # invalidate/flush after the raw UPDATE, it gets flushed then and
        # silently overwrites the raw SQL's correct value with the stale
        # pre-booking one (see ODOO19_RULES finding #70). Flushing
        # everything up front guarantees nothing is left pending to clash
        # with the raw write.
        slot.flush_recordset()

        self.env.cr.execute(
            """
            SELECT capacity, booked_count
            FROM otm_placement_interview_slot
            WHERE id = %s
            FOR UPDATE
            """,
            (slot.id,),
        )
        row = self.env.cr.fetchone()
        if not row:
            raise UserError(_("This interview slot no longer exists."))
        capacity, booked_count = row
        if not slot.active or slot.start_datetime < fields.Datetime.now():
            raise UserError(
                _("Sorry, this slot was just booked by another candidate. "
                  "Please select another slot.")
            )
        if booked_count >= capacity:
            raise UserError(
                _("Sorry, this slot was just booked by another candidate. "
                  "Please select another slot.")
            )

        # Update booked_count AND the stored available_count together: a raw
        # SQL UPDATE bypasses Odoo's compute dependency graph, so a stored
        # compute field (available_count) would otherwise go stale in the
        # database even after invalidating the in-memory cache.
        self.env.cr.execute(
            """
            UPDATE otm_placement_interview_slot
            SET booked_count = booked_count + 1,
                available_count = GREATEST(capacity - (booked_count + 1), 0)
            WHERE id = %s
            """,
            (slot.id,),
        )
        # Invalidate ONLY the plain (non-compute) field we raw-wrote.
        # Deliberately do NOT invalidate available_count/slot_status here:
        # both are stored/non-stored compute fields whose cache
        # bookkeeping interacts badly with a value just written via raw SQL
        # (see ODOO19_RULES finding #70 - it can silently overwrite the
        # correct raw-SQL value, or leave the record in a state a later
        # flush() can't reconcile). Nothing later in this method reads
        # those two fields again; every OTHER request gets a fresh
        # env/cache and reads the committed, correct DB values directly.
        slot.invalidate_recordset(["booked_count"])

        interview = self.create({
            "candidate_id": candidate.id,
            "slot_id": slot.id,
            "mode": slot.mode,
            "interviewer_id": slot.interviewer_id.id,
            "external_interviewer_name": slot.external_interviewer_name or False,
            "external_interviewer_contact": slot.external_interviewer_contact or False,
            "scheduled_start": slot.start_datetime,
            "scheduled_end": slot.end_datetime,
            "meeting_platform": slot.meeting_platform,
            "meeting_url": slot.meeting_url,
            "venue": slot.venue,
            "status": "scheduled",
        })
        candidate.write({"stage": "interview_scheduled"})
        if not bypass_active_check:
            # Self-service booking that just went through: if it was made
            # possible by an approved-but-unconsumed re-attempt permission,
            # that permission is now used up.
            pending = candidate._get_pending_reattempt_approval()
            if pending:
                pending.status = "completed"
        interview._send_notification("interview_booking_confirmation_mail_template")
        interview.action_send_whatsapp_confirmation()
        return interview

    def action_cancel(self):
        for interview in self:
            if interview.slot_id:
                interview.slot_id.sudo().write(
                    {"booked_count": max(interview.slot_id.booked_count - 1, 0)}
                )
            interview.status = "cancelled"
            interview._send_notification("interview_cancelled_mail_template")

    def action_mark_completed(self):
        self.write({"status": "completed"})

    def action_mark_no_show(self):
        self.write({"status": "no_show"})

    def action_confirm(self):
        self.write({"status": "confirmed"})

    def _send_notification(self, template_xmlid):
        self.ensure_one()
        template = self.env.ref(
            "otm_placement_management.%s" % template_xmlid, raise_if_not_found=False
        )
        if template and self.candidate_id.email:
            template.sudo().send_mail(self.id, force_send=False)

    # --- WhatsApp-ready notification architecture -------------------------
    # These are intentionally provider-agnostic. Configure a real WhatsApp
    # Business API/BSP integration by overriding these methods (or wiring
    # them to a WhatsApp module such as otm_whatsapp_coexistence) without
    # touching any other part of this module.

    def action_send_whatsapp_confirmation(self):
        for interview in self:
            interview._whatsapp_log("confirmation")

    def action_send_whatsapp_reminder(self):
        for interview in self:
            interview._whatsapp_log("reminder")

    def action_send_whatsapp_reschedule(self):
        for interview in self:
            interview._whatsapp_log("reschedule")

    def _whatsapp_log(self, kind):
        self.ensure_one()
        self.message_post(
            body=_("WhatsApp %(kind)s notification queued for %(phone)s "
                    "(no provider configured yet).", kind=kind,
                    phone=self.candidate_id.phone)
        )

    @api.model
    def _cron_send_interview_reminders(self):
        """Send a reminder ~24h before scheduled interviews that have not
        already been reminded. Idempotent: guarded by reminder_sent."""
        now = fields.Datetime.now()
        window_start = now
        window_end = now + timedelta(hours=24)
        interviews = self.search([
            ("status", "in", ["scheduled", "confirmed"]),
            ("reminder_sent", "=", False),
            ("scheduled_start", ">=", window_start),
            ("scheduled_start", "<=", window_end),
        ])
        for interview in interviews:
            interview._send_notification("interview_reminder_mail_template")
            interview.action_send_whatsapp_reminder()
            interview.reminder_sent = True
