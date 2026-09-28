# -*- coding: utf-8 -*-
from odoo import api, fields, models


class OtmPlacementInterviewSlot(models.Model):
    _name = "otm.placement.interview.slot"
    _description = "Placement Interview Slot"
    _order = "start_datetime"

    name = fields.Char(string="Slot", compute="_compute_name", store=True)
    date = fields.Date(
        compute="_compute_date", store=True,
        help="Derived from Start so it can never drift out of sync with it "
             "(the public booking page filters slots by this field).",
    )
    start_datetime = fields.Datetime(string="Start", required=True)
    end_datetime = fields.Datetime(string="End", required=True)
    mode = fields.Selection(
        [("online", "Online"), ("offline", "Offline")],
        required=True,
        default="online",
    )
    interviewer_id = fields.Many2one("res.users", string="Interviewer")

    capacity = fields.Integer(default=1, required=True)
    booked_count = fields.Integer(default=0, readonly=True, copy=False)
    available_count = fields.Integer(
        string="Available", compute="_compute_available_count", store=True
    )

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

    active = fields.Boolean(default=True)
    notes = fields.Text()

    slot_status = fields.Selection(
        [("available", "Available"), ("full", "Full"), ("past", "Past")],
        string="Status",
        compute="_compute_slot_status",
    )

    mock_interview_ids = fields.One2many(
        "otm.placement.mock.interview", "slot_id", string="Bookings"
    )

    _capacity_positive = models.Constraint(
        "check(capacity > 0)", "Capacity must be greater than zero."
    )
    _booked_not_negative = models.Constraint(
        "check(booked_count >= 0)", "Booked count cannot be negative."
    )

    @api.depends("start_datetime")
    def _compute_date(self):
        for slot in self:
            if slot.start_datetime:
                slot.date = fields.Datetime.context_timestamp(
                    slot, slot.start_datetime
                ).date()
            else:
                slot.date = False

    @api.depends("date", "start_datetime", "end_datetime", "mode")
    def _compute_name(self):
        for slot in self:
            if slot.start_datetime:
                slot.name = "{} ({})".format(
                    fields.Datetime.context_timestamp(
                        slot, slot.start_datetime
                    ).strftime("%d %b %Y %I:%M %p"),
                    dict(slot._fields["mode"].selection).get(slot.mode, ""),
                )
            else:
                slot.name = "New Slot"

    @api.depends("capacity", "booked_count")
    def _compute_available_count(self):
        for slot in self:
            slot.available_count = max(slot.capacity - slot.booked_count, 0)

    @api.depends("available_count", "start_datetime")
    def _compute_slot_status(self):
        now = fields.Datetime.now()
        for slot in self:
            if slot.start_datetime and slot.start_datetime < now:
                slot.slot_status = "past"
            elif slot.available_count <= 0:
                slot.slot_status = "full"
            else:
                slot.slot_status = "available"

    def _public_slot_data(self):
        """Return only publicly-safe fields for a slot (no internal ids/notes)."""
        self.ensure_one()
        tz_start = fields.Datetime.context_timestamp(self, self.start_datetime)
        return {
            "id": self.id,
            "date": tz_start.strftime("%Y-%m-%d"),
            "date_label": tz_start.strftime("%d %B %Y"),
            "time_label": tz_start.strftime("%I:%M %p"),
            "mode": self.mode,
            "available": self.slot_status == "available",
            "venue": self.venue if self.mode == "offline" else False,
            "interviewer": self.interviewer_id.name or "",
        }
