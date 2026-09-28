# -*- coding: utf-8 -*-
"""One-time bulk import of candidates from the old Odoo 17 LPMS module
(logic_lpms, model lpms.access.application) into this module's
otm.placement.candidate, over the same XML-RPC connection already used
for the old-ERP student-verification check.

Mapping decisions (all deliberately conservative / non-destructive):
  - Duplicate (same phone + email already registered here) -> SKIPPED,
    never overwritten, so a real local edit is never clobbered.
  - LPMS course (logic.lpms.course) with no exactly-matching Program
    here -> a new Program is auto-created with that same name.
  - LPMS record with no course at all -> falls back to a single shared
    "Imported from LPMS (Unspecified)" Program, so nothing is dropped
    just because program_id is required here.
  - Stage mapping is intentionally narrow (no guessing into
    interview_completed/placement, which we have no reliable signal
    for): state == 'rejected' -> not_interested; interview_status ==
    'scheduled' -> interview_scheduled; everything else -> new.
  - Every original LPMS field that has no direct home here (place,
    logic_branch, year_of_pass, original state/interview_status, mock
    interview date/remarks) is preserved as readable text in
    Additional Requirements, so nothing is silently lost even though
    it isn't first-class here.
  - Mock interview slots/records are NOT fabricated from the old
    mock_interview_date, since we don't have a reliable mode/
    interviewer/meeting-link to attach it to.
"""
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

BATCH_SIZE = 200
FALLBACK_PROGRAM_NAME = "Imported from LPMS (Unspecified)"

LPMS_FIELDS = [
    "name", "phone_number", "email", "course_id", "state", "interview_status",
    "place", "logic_branch", "year_of_pass", "mock_interview_date",
    "mock_interview_remarks", "create_date",
]


class OtmPlacementLpmsImportWizard(models.TransientModel):
    _name = "otm.placement.lpms.import.wizard"
    _description = "Import Candidates from Old LPMS"

    state = fields.Selection(
        [("draft", "Draft"), ("done", "Done")], default="draft",
    )
    total_found = fields.Integer(readonly=True)
    imported_count = fields.Integer(readonly=True)
    skipped_count = fields.Integer(readonly=True)
    error_count = fields.Integer(readonly=True)
    created_program_count = fields.Integer(readonly=True)
    log = fields.Text(readonly=True)

    def action_check_count(self):
        self.ensure_one()
        Client = self.env["otm.placement.old.erp.client"]
        count = Client.search_count("lpms.access.application", [])
        if count is None:
            self.log = ("Could not reach the old ERP. Check Placement > "
                        "Configuration > Old ERP Connection, then try again.")
            self.total_found = 0
        else:
            self.total_found = count
            self.log = "%s candidate(s) found in the old LPMS. Click 'Run Import' to proceed." % count
        return self._reopen()

    def action_run_import(self):
        self.ensure_one()
        Client = self.env["otm.placement.old.erp.client"]
        Candidate = self.env["otm.placement.candidate"]
        Program = self.env["otm.placement.program"]

        imported = skipped = errors = created_programs = 0
        log_lines = []
        program_cache = {}  # course name -> program record
        admission_years = dict(Candidate._get_admission_year_selection())

        offset = 0
        while True:
            batch = Client.search_read(
                "lpms.access.application", [], LPMS_FIELDS,
                limit=BATCH_SIZE, offset=offset, order="id asc",
            )
            if batch is None:
                log_lines.append(
                    "Stopped: could not reach the old ERP (offset %s). "
                    "Re-run the import to resume — already-imported candidates "
                    "will be skipped as duplicates." % offset
                )
                break
            if not batch:
                break

            for rec in batch:
                try:
                    phone = (rec.get("phone_number") or "").replace(" ", "").strip()
                    email = (rec.get("email") or "").strip()
                    name = (rec.get("name") or "").strip()
                    if not phone or not email or not name:
                        errors += 1
                        log_lines.append(
                            "Skipped (missing name/phone/email): LPMS id %s" % rec.get("id")
                        )
                        continue

                    existing = Candidate.search(
                        [("phone", "=", phone), ("email", "=", email)], limit=1
                    )
                    if existing:
                        skipped += 1
                        continue

                    course = rec.get("course_id")
                    course_name = course[1] if course else False

                    if course_name:
                        program = program_cache.get(course_name)
                        if not program:
                            program = Program.search([("name", "=", course_name)], limit=1)
                            if not program:
                                program = Program.create({"name": course_name})
                                created_programs += 1
                            program_cache[course_name] = program
                    else:
                        program = program_cache.get(FALLBACK_PROGRAM_NAME)
                        if not program:
                            program = Program.search([("name", "=", FALLBACK_PROGRAM_NAME)], limit=1)
                            if not program:
                                program = Program.create({"name": FALLBACK_PROGRAM_NAME})
                                created_programs += 1
                            program_cache[FALLBACK_PROGRAM_NAME] = program

                    old_state = rec.get("state")
                    old_interview_status = rec.get("interview_status")
                    if old_state == "rejected":
                        stage = "not_interested"
                    elif old_interview_status == "scheduled":
                        stage = "interview_scheduled"
                    else:
                        stage = "new"

                    admission_year = False
                    year_of_pass = rec.get("year_of_pass")
                    if year_of_pass in admission_years:
                        admission_year = year_of_pass

                    note_parts = ["Imported from old LPMS (lpms.access.application id %s)." % rec.get("id")]
                    if rec.get("place"):
                        note_parts.append("Place: %s" % rec["place"])
                    if rec.get("logic_branch"):
                        note_parts.append("Logic Branch Studied: %s" % rec["logic_branch"])
                    if year_of_pass:
                        note_parts.append("Year of Pass: %s" % year_of_pass)
                    if course_name:
                        note_parts.append("LPMS Course: %s" % course_name)
                    note_parts.append("Original State: %s" % (old_state or "-"))
                    note_parts.append("Original Interview Status: %s" % (old_interview_status or "-"))
                    if rec.get("mock_interview_date"):
                        note_parts.append("Old Mock Interview Date: %s" % rec["mock_interview_date"])
                    if rec.get("mock_interview_remarks"):
                        note_parts.append("Old Mock Interview Remarks: %s" % rec["mock_interview_remarks"])

                    vals = {
                        "name": name,
                        "phone": phone,
                        "email": email,
                        "program_id": program.id,
                        "stage": stage,
                        "additional_support": "\n".join(note_parts),
                    }
                    if admission_year:
                        vals["admission_year"] = admission_year
                    if rec.get("create_date"):
                        try:
                            vals["registration_date"] = fields.Datetime.to_datetime(rec["create_date"])
                        except Exception:  # noqa: BLE001 - never let a bad date abort the import
                            pass

                    Candidate.create(vals)
                    imported += 1
                except Exception as exc:  # noqa: BLE001 - one bad record must not abort the batch
                    errors += 1
                    log_lines.append(
                        "Error importing LPMS id %s (%s): %s" % (rec.get("id"), rec.get("name"), exc)
                    )
                    _logger.exception("LPMS import error for record %s", rec.get("id"))

            offset += len(batch)
            self.env.cr.commit()  # persist progress so a later failure doesn't lose earlier work
            if len(batch) < BATCH_SIZE:
                break

        summary = (
            "Import finished. Imported: %s | Skipped (duplicate): %s | "
            "Errors: %s | New Programs created: %s"
            % (imported, skipped, errors, created_programs)
        )
        log_lines.insert(0, summary)

        self.write({
            "state": "done",
            "imported_count": imported,
            "skipped_count": skipped,
            "error_count": errors,
            "created_program_count": created_programs,
            "log": "\n".join(log_lines[:500]),  # cap so a huge error list can't blow up the field
        })
        return self._reopen()

    def _reopen(self):
        return {
            "type": "ir.actions.act_window",
            "name": "Import Candidates from Old LPMS",
            "res_model": "otm.placement.lpms.import.wizard",
            "view_mode": "form",
            "res_id": self.id,
            "target": "new",
        }
