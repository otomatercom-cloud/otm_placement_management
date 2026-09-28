# -*- coding: utf-8 -*-
from datetime import datetime, time, timedelta

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import UserError

MAX_SLOTS_PER_RUN = 500


class OtmPlacementSlotGenerator(models.TransientModel):
    """Bulk-create interview slots across a date range: pick how many
    slots per day and how long each one is, and this splits the day
    into that many back-to-back slots, every day in the range."""

    _name = "otm.placement.slot.generator"
    _description = "Generate Interview Slots"

    date_from = fields.Date(
        string="From Date", required=True, default=fields.Date.context_today
    )
    date_to = fields.Date(
        string="To Date", required=True,
        default=lambda self: fields.Date.context_today(self) + timedelta(days=6),
    )
    skip_weekends = fields.Boolean(
        string="Skip Saturdays & Sundays", default=False
    )

    day_start_time = fields.Float(
        string="Start Time", required=True, default=10.0,
        help="First slot of each day starts at this time (24h).",
    )
    slots_per_day = fields.Integer(
        string="Slots Per Day", required=True, default=5,
        help="How many interview slots to create on each day.",
    )
    slot_duration = fields.Integer(
        string="Slot Duration (minutes)", required=True, default=30,
    )
    gap_minutes = fields.Integer(
        string="Gap Between Slots (minutes)", default=0,
        help="Idle time between the end of one slot and the start of the next.",
    )
    capacity = fields.Integer(
        string="Capacity Per Slot", required=True, default=1,
        help="How many candidates can book each generated slot.",
    )

    mode = fields.Selection(
        [("online", "Online"), ("offline", "Offline")],
        required=True, default="online",
    )
    interviewer_id = fields.Many2one("res.users", string="Interviewer")
    meeting_platform = fields.Selection(
        [
            ("google_meet", "Google Meet"),
            ("zoom", "Zoom"),
            ("teams", "Microsoft Teams"),
            ("other", "Other"),
        ],
        string="Meeting Platform", default="google_meet",
    )
    meeting_url = fields.Char(string="Meeting URL")
    venue = fields.Char(string="Venue")

    preview = fields.Char(string="Preview", compute="_compute_preview")

    @api.depends(
        "date_from", "date_to", "skip_weekends", "slots_per_day",
        "slot_duration", "gap_minutes", "day_start_time",
    )
    def _compute_preview(self):
        for wiz in self:
            if not (wiz.date_from and wiz.date_to) or wiz.date_to < wiz.date_from or wiz.slots_per_day <= 0:
                wiz.preview = ""
                continue
            days = wiz._working_days()
            total = len(days) * wiz.slots_per_day
            last_start_minutes = (
                wiz.day_start_time * 60
                + (wiz.slots_per_day - 1) * (wiz.slot_duration + wiz.gap_minutes)
            )
            last_end_minutes = last_start_minutes + wiz.slot_duration
            wiz.preview = _(
                "%(total)s slots across %(days)s day(s) — the last slot each day "
                "ends at %(end)s."
            ) % {
                "total": total,
                "days": len(days),
                "end": "%02d:%02d" % (int(last_end_minutes // 60) % 24, int(last_end_minutes % 60)),
            }

    def _working_days(self):
        self.ensure_one()
        days = []
        current = self.date_from
        while current <= self.date_to:
            if not (self.skip_weekends and current.weekday() >= 5):
                days.append(current)
            current += timedelta(days=1)
        return days

    def _local_to_utc_naive(self, day, minutes_from_midnight):
        """Combine a date with a minute offset in the user's timezone and
        return a naive UTC datetime, the way Datetime fields are stored."""
        tz_name = self.env.context.get("tz") or self.env.user.tz or "UTC"
        try:
            tz = pytz.timezone(tz_name)
        except pytz.UnknownTimeZoneError:
            tz = pytz.utc
        hour = int(minutes_from_midnight // 60) % 24
        minute = int(minutes_from_midnight % 60)
        extra_days = int(minutes_from_midnight // (24 * 60))
        naive_local = datetime.combine(day, time(hour, minute)) + timedelta(days=extra_days)
        localized = tz.localize(naive_local) if tz is not pytz.utc else pytz.utc.localize(naive_local)
        return localized.astimezone(pytz.utc).replace(tzinfo=None)

    def action_generate_slots(self):
        self.ensure_one()
        if self.date_to < self.date_from:
            raise UserError(_("'To Date' must be on or after 'From Date'."))
        if self.slots_per_day <= 0:
            raise UserError(_("Slots Per Day must be greater than zero."))
        if self.slot_duration <= 0:
            raise UserError(_("Slot Duration must be greater than zero minutes."))
        if self.capacity <= 0:
            raise UserError(_("Capacity Per Slot must be greater than zero."))
        if self.mode == "offline" and not self.venue:
            raise UserError(_("Please set a Venue for offline slots."))

        days = self._working_days()
        total_planned = len(days) * self.slots_per_day
        if total_planned > MAX_SLOTS_PER_RUN:
            raise UserError(
                _("This would create %(count)s slots in one run (limit %(max)s). "
                  "Narrow the date range, reduce slots per day, or run it in "
                  "batches.") % {"count": total_planned, "max": MAX_SLOTS_PER_RUN}
            )

        Slot = self.env["otm.placement.interview.slot"]

        # Avoid accidentally duplicating slots if this wizard is run twice
        # over an overlapping range: skip any (mode, exact start) pair that
        # already exists.
        existing_starts = set(
            Slot.search([
                ("mode", "=", self.mode),
                ("start_datetime", ">=", self._local_to_utc_naive(self.date_from, 0)),
                ("start_datetime", "<=", self._local_to_utc_naive(self.date_to, 24 * 60)),
            ]).mapped("start_datetime")
        )

        vals_list = []
        step = self.slot_duration + self.gap_minutes
        for day in days:
            for i in range(self.slots_per_day):
                start_minutes = self.day_start_time * 60 + i * step
                start_dt = self._local_to_utc_naive(day, start_minutes)
                end_dt = start_dt + timedelta(minutes=self.slot_duration)
                if start_dt in existing_starts:
                    continue
                vals = {
                    "start_datetime": start_dt,
                    "end_datetime": end_dt,
                    "mode": self.mode,
                    "capacity": self.capacity,
                    "interviewer_id": self.interviewer_id.id or False,
                }
                if self.mode == "online":
                    vals["meeting_platform"] = self.meeting_platform
                    vals["meeting_url"] = self.meeting_url or False
                else:
                    vals["venue"] = self.venue
                vals_list.append(vals)

        if not vals_list:
            raise UserError(
                _("Nothing to create — every slot in this range already exists. "
                  "Adjust the date range or time settings.")
            )

        created = Slot.create(vals_list)

        return {
            "type": "ir.actions.act_window",
            "name": _("Generated Interview Slots"),
            "res_model": "otm.placement.interview.slot",
            "view_mode": "list,calendar,form",
            "views": [(False, "list"), (False, "calendar"), (False, "form")],
            "domain": [("id", "in", created.ids)],
            "context": {},
        }
