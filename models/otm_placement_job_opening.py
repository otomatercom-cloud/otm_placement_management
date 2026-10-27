# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class OtmPlacementJobOpening(models.Model):
    _name = "otm.placement.job.opening"
    _description = "Job Opening"
    _inherit = ["mail.thread"]
    _order = "published_date desc, id desc"

    name = fields.Char(string="Job Title", required=True, tracking=True)
    company_name = fields.Char(string="Company", required=True, tracking=True)
    location = fields.Char()
    employment_type = fields.Selection(
        [
            ("full_time", "Full Time"),
            ("part_time", "Part Time"),
            ("internship", "Internship"),
            ("contract", "Contract"),
        ],
        string="Employment Type",
        default="full_time",
        required=True,
    )
    salary_range = fields.Char(
        string="Salary / Stipend",
        help="Shown to approved candidates as typed, e.g. '3 - 4 LPA'.",
    )
    openings = fields.Integer(string="Vacancies", default=1)
    description = fields.Text(string="Job Description")
    requirements = fields.Text(string="Requirements")
    program_ids = fields.Many2many(
        "otm.placement.program",
        relation="otm_placement_job_program_rel",
        column1="job_id",
        column2="program_id",
        string="Eligible Programs",
        help="Leave empty to open this job to every approved candidate.",
    )
    last_date = fields.Date(string="Last Date to Apply", tracking=True)
    apply_link = fields.Char(
        string="External Link",
        help="Optional company careers/application page shown alongside the "
             "in-app Apply button.",
    )
    state = fields.Selection(
        [("draft", "Draft"), ("published", "Published"), ("closed", "Closed")],
        default="draft",
        required=True,
        tracking=True,
        copy=False,
    )
    published_date = fields.Datetime(readonly=True, copy=False)
    user_id = fields.Many2one(
        "res.users", string="Responsible", default=lambda self: self.env.user
    )
    active = fields.Boolean(default=True)
    application_ids = fields.One2many(
        "otm.placement.job.application", "job_id", string="Applications"
    )
    application_count = fields.Integer(compute="_compute_application_count")

    _openings_positive = models.Constraint(
        "CHECK(openings >= 0)", "Vacancies cannot be negative."
    )

    @api.depends("application_ids")
    def _compute_application_count(self):
        for job in self:
            job.application_count = len(job.application_ids)

    # --- State actions ------------------------------------------------------
    def action_publish(self):
        today = fields.Date.context_today(self)
        for job in self:
            if job.last_date and job.last_date < today:
                raise UserError(
                    _("The last date to apply for '%s' is already in the past.", job.name)
                )
        self.write({"state": "published", "published_date": fields.Datetime.now()})
        return True

    def action_close(self):
        self.write({"state": "closed"})
        return True

    def action_set_draft(self):
        self.write({"state": "draft"})
        return True

    def action_view_applications(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Applications"),
            "res_model": "otm.placement.job.application",
            "view_mode": "list,form",
            "domain": [("job_id", "=", self.id)],
            "context": {"default_job_id": self.id},
        }

    # --- Candidate-facing helpers (used by the BFF controller) -------------
    @api.model
    def _open_jobs_domain(self, candidate):
        """Jobs a candidate may currently see/apply to: published, not past
        the deadline, and either open to every program or to theirs."""
        today = fields.Date.context_today(self)
        return [
            ("state", "=", "published"),
            "|", ("last_date", "=", False), ("last_date", ">=", today),
            "|", ("program_ids", "=", False),
            ("program_ids", "in", candidate.program_id.ids),
        ]

    def _public_data(self, application_state=False):
        self.ensure_one()
        types = dict(self._fields["employment_type"].selection)
        return {
            "id": self.id,
            "title": self.name,
            "company": self.company_name,
            "location": self.location or "",
            "employment_type": types.get(self.employment_type, ""),
            "salary_range": self.salary_range or "",
            "openings": self.openings,
            "description": self.description or "",
            "requirements": self.requirements or "",
            "last_date": str(self.last_date) if self.last_date else "",
            "apply_link": self.apply_link or "",
            "applied": bool(application_state),
            "application_state": application_state or "",
        }


class OtmPlacementJobApplication(models.Model):
    _name = "otm.placement.job.application"
    _description = "Job Application"
    _inherit = ["mail.thread"]
    _order = "applied_date desc, id desc"

    job_id = fields.Many2one(
        "otm.placement.job.opening", string="Job Opening", required=True,
        ondelete="cascade", index=True, tracking=True,
    )
    candidate_id = fields.Many2one(
        "otm.placement.candidate", string="Candidate", required=True,
        ondelete="cascade", index=True, tracking=True,
    )
    state = fields.Selection(
        [
            ("applied", "Applied"),
            ("shortlisted", "Shortlisted"),
            ("selected", "Selected"),
            ("rejected", "Rejected"),
        ],
        default="applied",
        required=True,
        tracking=True,
    )
    applied_date = fields.Datetime(default=fields.Datetime.now, readonly=True)
    note = fields.Text(string="Candidate Note")

    _job_candidate_uniq = models.Constraint(
        "unique(job_id, candidate_id)",
        "This candidate has already applied for this job opening.",
    )

    @api.depends("candidate_id.name", "job_id.name")
    def _compute_display_name(self):
        for app in self:
            app.display_name = "%s - %s" % (
                app.candidate_id.name or "", app.job_id.name or ""
            )
