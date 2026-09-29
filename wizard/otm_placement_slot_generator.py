# -*- coding: utf-8 -*-
from datetime import datetime, time, timedelta

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import UserError

MAX_SLOTS_PER_RUN = 500

WEEKDAY_SELECTION = [
    ("0", "Monday"),
    ("1", "Tuesday"),
    ("2", "Wednesday"),
    ("3", "Thursday"),
    ("4", "Friday"),
    ("5", "Saturday"),
    ("6", "Sunday"),
]


class OtmPlacementSlotGenerator(models.TransientModel):
    """Bulk-create interview slots across a date range, in one of two modes:

    - "Same Schedule Every Day" (uniform): pick how many slots per day and
      how long each one is, and every selected weekday in the range gets
      the same back-to-back schedule starting at one time.
    - "Custom Time Slots" (custom): define one or more explicit time
      windows (e.g. "Monday 2:30 PM - 4:30 PM"), each tied to a single
      weekday; that window repeats on that weekday every week across the
      date range, either as one slot spanning the whole window or split
      into several slots the same way the uniform mode does.

    Either mode lets you assign an internal Odoo user as interviewer, or a
    guest/external interviewer who isn't a system user (just a name and a
    phone/email), per line in custom mode or once for the whole batch.
    """

    _name = "otm.placement.slot.generator"
    _description = "Generate Interview Slots"

    generation_mode = fields.Selection(
        [("uniform", "Same Schedule Every Day"), ("custom", "Custom Time Slots")],
        required=True, default="uniform",
    )

    date_from = fields.Date(
        string="From Date", required=True, default=fields.Date.context_today
    )
    date_to = fields.Date(
        string="To Date", required=True,
        default=lambda self: fields.Date.context_today(self) + timedelta(days=6),
    )
    weekday_mon = fields.Boolean(string="Mon", default=True)
    weekday_tue = fields.Boolean(string="Tue", default=True)
    weekday_wed = fields.Boolean(string="Wed", default=True)
    weekday_thu = fields.Boolean(string="Thu", default=True)
    weekday_fri = fields.Boolean(string="Fri", default=True)
    weekday_sat = fields.Boolean(string="Sat", default=True)
    weekday_sun = fields.Boolean(string="Sun", default=True)

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
        help="Also used to split a custom time window into several slots, "
             "when that line isn't marked 'One Slot For Whole Window'.",
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
    interviewer_id = fields.Many2one(
        "res.users", string="Interviewer",
        help="Default interviewer for the whole run. In Custom Time Slots "
             "mode, a line can override this with its own interviewer.",
    )
    external_interviewer_name = fields.Char(
        string="External Interviewer",
        help="Name of a guest/external interviewer who isn't an Odoo user "
             "here. Leave Interviewer blank when using this. Default for "
             "the whole run; a custom-mode line can override it.",
    )
    external_interviewer_contact = fields.Char(string="External Interviewer Contact")
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

    time_line_ids = fields.One2many(
        "otm.placement.slot.generator.line", "generator_id",
        string="Custom Time Slots",
    )

    preview = fields.Char(string="Preview", compute="_compute_preview")

    @api.depends(
        "generation_mode",
        "date_from", "date_to", "slots_per_day",
        "slot_duration", "gap_minutes", "day_start_time",
        "weekday_mon", "weekday_tue", "weekday_wed", "weekday_thu",
        "weekday_fri", "weekday_sat", "weekday_sun",
        "time_line_ids.weekday", "time_line_ids.start_time",
        "time_line_ids.end_time", "time_line_ids.single_slot",
    )
    def _compute_preview(self):
        for wiz in self:
            if not (wiz.date_from and wiz.date_to) or wiz.date_to < wiz.date_from:
                wiz.preview = ""
                continue
            try:
                if wiz.generation_mode == "custom":
                    wiz.preview = wiz._preview_custom()
                else:
                    wiz.preview = wiz._preview_uniform()
            except UserError as exc:
                wiz.preview = str(exc)

    def _preview_uniform(self):
        self.ensure_one()
        if self.slots_per_day <= 0:
            return ""
        days = self._working_days()
        if not days:
            return _("No days match the selected weekdays in this date range.")
        total = len(days) * self.slots_per_day
        last_start_minutes = (
            self.day_start_time * 60
            + (self.slots_per_day - 1) * (self.slot_duration + self.gap_minutes)
        )
        last_end_minutes = last_start_minutes + self.slot_duration
        return _(
            "%(total)s slots across %(days)s day(s) — the last slot each day "
            "ends at %(end)s."
        ) % {
            "total": total,
            "days": len(days),
            "end": "%02d:%02d" % (int(last_end_minutes // 60) % 24, int(last_end_minutes % 60)),
        }

    def _preview_custom(self):
        self.ensure_one()
        if not self.time_line_ids:
            return _("Add at least one time line below (e.g. Monday, 2:30 PM - 4:30 PM).")
        total = 0
        line_count = 0
        for line in self.time_line_ids:
            if not line.weekday or line.end_time <= line.start_time:
                continue
            matching_dates = self._dates_for_weekday(int(line.weekday))
            slots_per_occurrence = 1 if line.single_slot else self._slots_in_window(
                line.start_time, line.end_time
            )
            total += len(matching_dates) * slots_per_occurrence
            line_count += 1
        if not line_count:
            return _("Add at least one valid time line (end time after start time).")
        return _(
            "%(total)s slots across %(lines)s time line(s), recurring weekly "
            "over the date range."
        ) % {"total": total, "lines": line_count}

    def _slots_in_window(self, start_time, end_time):
        """How many back-to-back slot_duration+gap_minutes slots fit
        between start_time and end_time (both in hours, e.g. 14.5 = 2:30 PM)."""
        if self.slot_duration <= 0:
            return 0
        step = self.slot_duration + self.gap_minutes
        cursor = start_time * 60
        end_minutes = end_time * 60
        count = 0
        while cursor + self.slot_duration <= end_minutes + 1e-6:
            count += 1
            cursor += step
        return count

    def _selected_weekdays(self):
        """Python's date.weekday(): Monday=0 ... Sunday=6."""
        self.ensure_one()
        return {
            0: self.weekday_mon,
            1: self.weekday_tue,
            2: self.weekday_wed,
            3: self.weekday_thu,
            4: self.weekday_fri,
            5: self.weekday_sat,
            6: self.weekday_sun,
        }

    def _working_days(self):
        self.ensure_one()
        allowed = self._selected_weekdays()
        return [d for d in self._all_dates() if allowed.get(d.weekday())]

    def _dates_for_weekday(self, weekday):
        self.ensure_one()
        return [d for d in self._all_dates() if d.weekday() == weekday]

    def _all_dates(self):
        self.ensure_one()
        days = []
        current = self.date_from
        while current <= self.date_to:
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

    def _base_slot_vals(self, interviewer_id=False, external_name=False, external_contact=False):
        self.ensure_one()
        vals = {
            "mode": self.mode,
            "capacity": self.capacity,
            "interviewer_id": interviewer_id or self.interviewer_id.id or False,
            "external_interviewer_name": external_name or self.external_interviewer_name or False,
            "external_interviewer_contact": external_contact or self.external_interviewer_contact or False,
        }
        if self.mode == "online":
            vals["meeting_platform"] = self.meeting_platform
            vals["meeting_url"] = self.meeting_url or False
        else:
            vals["venue"] = self.venue
        return vals

    def _build_uniform_vals(self, days):
        self.ensure_one()
        base = self._base_slot_vals()
        step = self.slot_duration + self.gap_minutes
        vals_list = []
        for day in days:
            for i in range(self.slots_per_day):
                start_minutes = self.day_start_time * 60 + i * step
                start_dt = self._local_to_utc_naive(day, start_minutes)
                end_dt = start_dt + timedelta(minutes=self.slot_duration)
                vals_list.append(dict(base, start_datetime=start_dt, end_datetime=end_dt))
        return vals_list

    def _build_custom_vals(self):
        self.ensure_one()
        vals_list = []
        for line in self.time_line_ids:
            if not line.weekday:
                raise UserError(_("Every time line needs a weekday."))
            if line.end_time <= line.start_time:
                raise UserError(
                    _("On the %s line, End Time must be after Start Time.")
                    % dict(WEEKDAY_SELECTION).get(line.weekday)
                )
            base = self._base_slot_vals(
                interviewer_id=line.interviewer_id.id,
                external_name=line.external_interviewer_name,
                external_contact=line.external_interviewer_contact,
            )
            dates = self._dates_for_weekday(int(line.weekday))
            for day in dates:
                if line.single_slot:
                    start_dt = self._local_to_utc_naive(day, line.start_time * 60)
                    end_dt = self._local_to_utc_naive(day, line.end_time * 60)
                    vals_list.append(dict(base, start_datetime=start_dt, end_datetime=end_dt))
                else:
                    step = self.slot_duration + self.gap_minutes
                    cursor = line.start_time * 60
                    end_minutes = line.end_time * 60
                    while cursor + self.slot_duration <= end_minutes + 1e-6:
                        start_dt = self._local_to_utc_naive(day, cursor)
                        end_dt = start_dt + timedelta(minutes=self.slot_duration)
                        vals_list.append(dict(base, start_datetime=start_dt, end_datetime=end_dt))
                        cursor += step
        return vals_list

    def action_generate_slots(self):
        self.ensure_one()
        if self.date_to < self.date_from:
            raise UserError(_("'To Date' must be on or after 'From Date'."))
        if self.capacity <= 0:
            raise UserError(_("Capacity Per Slot must be greater than zero."))
        if self.mode == "offline" and not self.venue:
            raise UserError(_("Please set a Venue for offline slots."))

        if self.generation_mode == "custom":
            if not self.time_line_ids:
                raise UserError(
                    _("Add at least one custom time line (e.g. Monday, 2:30 PM - 4:30 PM).")
                )
            if self.slot_duration <= 0:
                raise UserError(_("Slot Duration must be greater than zero minutes."))
            vals_list = self._build_custom_vals()
        else:
            if self.slots_per_day <= 0:
                raise UserError(_("Slots Per Day must be greater than zero."))
            if self.slot_duration <= 0:
                raise UserError(_("Slot Duration must be greater than zero minutes."))
            if not any(self._selected_weekdays().values()):
                raise UserError(_("Select at least one weekday to generate slots on."))
            days = self._working_days()
            if not days:
                raise UserError(
                    _("No dates in the selected range fall on the chosen weekdays. "
                      "Adjust the date range or weekday selection.")
                )
            vals_list = self._build_uniform_vals(days)

        if len(vals_list) > MAX_SLOTS_PER_RUN:
            raise UserError(
                _("This would create %(count)s slots in one run (limit %(max)s). "
                  "Narrow the date range or the schedule, or run it in "
                  "batches.") % {"count": len(vals_list), "max": MAX_SLOTS_PER_RUN}
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
        vals_list = [v for v in vals_list if v["start_datetime"] not in existing_starts]

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


class OtmPlacementSlotGeneratorLine(models.TransientModel):
    """One explicit recurring time window for Custom Time Slots mode, e.g.
    "Monday, 2:30 PM - 4:30 PM". Repeats on that weekday every week across
    the wizard's date range - either as a single slot spanning the whole
    window, or split into several slots using the wizard's Slot Duration /
    Gap settings."""

    _name = "otm.placement.slot.generator.line"
    _description = "Generate Interview Slots - Custom Time Line"

    generator_id = fields.Many2one(
        "otm.placement.slot.generator", required=True, ondelete="cascade"
    )
    weekday = fields.Selection(WEEKDAY_SELECTION, required=True)
    start_time = fields.Float(string="Start Time", required=True, default=14.5)
    end_time = fields.Float(string="End Time", required=True, default=16.5)
    single_slot = fields.Boolean(
        string="One Slot For Whole Window",
        help="On: creates exactly one slot spanning Start Time to End Time. "
             "Off: splits the window into several slots using the wizard's "
             "Slot Duration / Gap Between Slots.",
    )
    interviewer_id = fields.Many2one(
        "res.users", string="Interviewer",
        help="Leave blank to use the wizard's default interviewer.",
    )
    external_interviewer_name = fields.Char(
        string="External Interviewer",
        help="Name of a guest/external interviewer for this line only. "
             "Leave blank to use the wizard's default.",
    )
    external_interviewer_contact = fields.Char(string="Contact")
