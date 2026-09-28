# -*- coding: utf-8 -*-
import uuid
from datetime import date

from odoo import api, fields, models


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
        return super().create(vals_list)

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

    def action_check_old_erp_status(self):
        Client = self.env["otm.placement.old.erp.client"]
        valid_statuses = dict(self._fields["erp_check_status"].selection)
        for candidate in self:
            result = Client.check_student_status(candidate.phone, candidate.email)
            status = result.get("status")
            candidate.write({
                "erp_check_status": status if status in valid_statuses else "unavailable",
                "erp_check_note": result.get("note"),
                "erp_checked_on": fields.Datetime.now(),
            })
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
