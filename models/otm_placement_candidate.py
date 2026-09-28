# -*- coding: utf-8 -*-
import logging
import threading
import uuid
from datetime import date

from odoo import SUPERUSER_ID, api, fields, models
from odoo.modules.registry import Registry

_logger = logging.getLogger(__name__)


class OtmPlacementCandidate(models.Model):
    _name = "otm.placement.candidate"
    _description = "Placement Candidate"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "registration_date desc, id desc"
    _rec_name = "name"

    name = fields.Char(required=True, tracking=True)
    candidate_reference = fields.Char(
        string="Reference", readonly=True, copy=False, default="New"
    )
    phone = fields.Char(string="WhatsApp Number", required=True, tracking=True)
    email = fields.Char(string="Email Address", required=True, tracking=True)

    program_id = fields.Many2one(
        "otm.placement.program", string="Program", required=True, tracking=True
    )
    admission_year = fields.Selection(
        selection="_get_admission_year_selection",
        string="Admission Year",
        tracking=True,
    )
    qualification_status = fields.Selection(
        [
            ("partly_qualified", "Partly Qualified"),
            ("fully_qualified", "Fully Qualified"),
            ("not_qualified", "Not Qualified"),
        ],
        string="Current Status",
        tracking=True,
    )

    employment_status = fields.Selection(
        [
            ("jobseeker", "Jobseeker"),
            ("employed", "Employed"),
            ("intern", "Intern"),
        ],
        string="Employment Status",
        tracking=True,
    )
    company_name = fields.Char(string="Company Name")
    designation = fields.Char(string="Designation")

    interview_preference = fields.Selection(
        [("online", "Online"), ("offline", "Offline")],
        string="Preferred Mode",
        tracking=True,
    )

    support_area_ids = fields.Many2many(
        "otm.placement.support.area", string="Required Support Areas"
    )
    additional_support = fields.Text(string="Additional Requirements")

    stage = fields.Selection(
        [
            ("new", "New"),
            ("reviewed", "Reviewed"),
            ("contacted", "Contacted"),
            ("interview_scheduled", "Interview Scheduled"),
            ("interview_completed", "Interview Completed"),
            ("follow_up", "Follow-up"),
            ("placement", "Placement"),
            ("cancelled", "Cancelled"),
            ("not_interested", "Not Interested"),
        ],
        string="Stage",
        default="new",
        tracking=True,
        group_expand="_read_group_stage_ids",
    )

    user_id = fields.Many2one(
        "res.users", string="Assigned To", tracking=True,
        default=lambda self: self.env.user,
    )
    partner_id = fields.Many2one(
        "res.partner", string="Portal Contact", copy=False,
        help="Linked when a portal account is created for this candidate.",
    )
    active = fields.Boolean(default=True)
    registration_date = fields.Datetime(default=fields.Datetime.now, tracking=True)
    access_token = fields.Char(
        string="Access Token", copy=False, default=lambda self: str(uuid.uuid4())
    )

    erp_check_status = fields.Selection(
        [
            ("not_checked", "Not Checked"),
            ("unavailable", "Check Unavailable"),
            ("not_found", "New — Not Found"),
            ("lead_only", "Known Lead (Not Admitted)"),
            ("current_student", "Existing Student"),
            ("old_student", "Old Student (Alumni)"),
        ],
        string="Old ERP Status",
        default="not_checked",
        copy=False,
        tracking=True,
        help="Result of cross-checking this candidate's phone/email against "
             "the old ERP's Leads/Admission module.",
    )
    erp_check_note = fields.Char(string="Old ERP Match Details", copy=False)
    erp_checked_on = fields.Datetime(string="Old ERP Last Checked", copy=False)

    mock_interview_ids = fields.One2many(
        "otm.placement.mock.interview", "candidate_id", string="Mock Interview Records"
    )
    mock_interview_count = fields.Integer(
        string="Mock Interviews", compute="_compute_mock_interview_count"
    )
    placement_record_ids = fields.One2many(
        "otm.placement.record", "candidate_id", string="Placement Records"
    )
    placement_record_count = fields.Integer(
        string="Placements", compute="_compute_placement_record_count"
    )

    _phone_uniq = models.Constraint(
        "unique(phone, email)",
        "A candidate with this WhatsApp number and email is already registered.",
    )

    @api.model
    def _get_admission_year_selection(self):
        current_year = date.today().year
        years = range(current_year - 15, current_year + 2)
        return [(str(y), str(y)) for y in reversed(list(years))]

    def _compute_mock_interview_count(self):
        for candidate in self:
            candidate.mock_interview_count = len(candidate.mock_interview_ids)

    def _compute_placement_record_count(self):
        for candidate in self:
            candidate.placement_record_count = len(candidate.placement_record_ids)

    @api.model
    def _read_group_stage_ids(self, stages, domain):
        return [key for key, _ in self._fields["stage"].selection]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("candidate_reference", "New") == "New":
                vals["candidate_reference"] = (
                    self.env["ir.sequence"].sudo().next_by_code(
                        "otm.placement.candidate"
                    )
                    or "New"
                )
        candidates = super().create(vals_list)
        candidates._trigger_old_erp_check_async()
        return candidates

    def action_view_mock_interviews(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Mock Interviews",
            "res_model": "otm.placement.mock.interview",
            "view_mode": "list,calendar,form",
            "domain": [("candidate_id", "=", self.id)],
            "context": {"default_candidate_id": self.id},
        }

    def action_set_stage(self):
        """Generic stage-transition action. The target stage is passed via
        the calling button's context (context="{'target_stage': 'reviewed'}"),
        so one method backs every 'Mark as ...' header button."""
        target_stage = self.env.context.get("target_stage")
        valid_stages = dict(self._fields["stage"].selection)
        if target_stage in valid_stages:
            self.write({"stage": target_stage})
        return True

    def _apply_old_erp_check_result(self, result):
        self.ensure_one()
        valid_statuses = dict(self._fields["erp_check_status"].selection)
        status = result.get("status")
        self.write({
            "erp_check_status": status if status in valid_statuses else "unavailable",
            "erp_check_note": result.get("note"),
            "erp_checked_on": fields.Datetime.now(),
        })

    def _trigger_old_erp_check_async(self):
        """Kick off the old-ERP check in a background thread right after a
        candidate is created (public registration or backend), so the
        request that created the candidate never waits on a third-party
        server that could be slow or unreachable. Skipped entirely if the
        old-ERP connection isn't configured/enabled, so there's no overhead
        for clients who never set it up.

        The thread is only started via cr.postcommit (after the CURRENT
        transaction actually commits) rather than immediately: the
        background thread opens its own DB cursor/connection, which can't
        see a row from a transaction that hasn't committed yet. Starting
        the thread immediately caused a real MissingError race the first
        time many candidates were created in one transaction (the LPMS
        bulk-import wizard) — the background cursor tried to read a
        candidate the outer transaction hadn't committed yet.
        """
        Settings = self.env["otm.placement.old.erp.settings"].sudo()
        settings = Settings.search([], limit=1)
        if not settings or not settings.active:
            return

        candidate_ids = self.ids
        db_name = self.env.cr.dbname
        if not candidate_ids:
            return

        def run():
            try:
                registry = Registry(db_name)
                with registry.cursor() as cr:
                    env = api.Environment(cr, SUPERUSER_ID, {})
                    candidates = env[self._name].browse(candidate_ids)
                    Client = env["otm.placement.old.erp.client"]
                    for candidate in candidates:
                        try:
                            result = Client.check_student_status(candidate.phone, candidate.email)
                            candidate._apply_old_erp_check_result(result)
                        except Exception:
                            _logger.exception(
                                "Background old-ERP check failed for candidate %s", candidate.id
                            )
                    cr.commit()
            except Exception:
                _logger.exception("Background old-ERP check thread failed to start/run")

        self.env.cr.postcommit.add(lambda: threading.Thread(target=run, daemon=True).start())

    def action_check_old_erp_status(self):
        Client = self.env["otm.placement.old.erp.client"]
        for candidate in self:
            result = Client.check_student_status(candidate.phone, candidate.email)
            candidate._apply_old_erp_check_result(result)
        if len(self) == 1:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "Old ERP Check",
                    "message": self.erp_check_note or self.erp_check_status,
                    "type": "warning" if self.erp_check_status == "unavailable" else "info",
                    "sticky": False,
                },
            }
        return True

    def _send_registration_confirmation(self):
        self.ensure_one()
        template = self.env.ref(
            "otm_placement_management.registration_confirmation_mail_template",
            raise_if_not_found=False,
        )
        if template and self.email:
            template.sudo().send_mail(self.id, force_send=False)

    def action_view_placement_records(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Placement Records",
            "res_model": "otm.placement.record",
            "view_mode": "list,form",
            "domain": [("candidate_id", "=", self.id)],
            "context": {"default_candidate_id": self.id},
        }
