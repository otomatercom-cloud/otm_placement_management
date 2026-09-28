# -*- coding: utf-8 -*-
from odoo import api, fields, models


class OtmPlacementRecord(models.Model):
    _name = "otm.placement.record"
    _description = "Placement Record"
    _inherit = ["mail.thread"]
    _order = "joining_date desc, id desc"

    candidate_id = fields.Many2one(
        "otm.placement.candidate", string="Candidate", required=True,
        ondelete="cascade", tracking=True, index=True,
    )
    company_name = fields.Char(tracking=True)
    designation = fields.Char(tracking=True)
    employment_type = fields.Selection(
        [
            ("full_time", "Full Time"),
            ("part_time", "Part Time"),
            ("internship", "Internship"),
            ("contract", "Contract"),
        ],
        string="Employment Type",
    )
    joining_date = fields.Date(string="Joining Date")
    currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.company.currency_id
    )
    salary = fields.Monetary(
        currency_field="currency_id",
        groups="otm_placement_management.group_placement_manager",
    )
    placement_status = fields.Selection(
        [
            ("not_placed", "Not Placed"),
            ("interviewing", "Interviewing"),
            ("selected", "Selected"),
            ("placed", "Placed"),
            ("declined", "Declined"),
        ],
        default="not_placed",
        tracking=True,
    )
    remarks = fields.Text()

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.filtered(
            lambda r: r.placement_status == "placed"
        )._sync_candidate_stage()
        return records

    def write(self, vals):
        res = super().write(vals)
        if vals.get("placement_status") == "placed":
            self._sync_candidate_stage()
        return res

    def _sync_candidate_stage(self):
        self.candidate_id.filtered(
            lambda c: c.stage != "placement"
        ).write({"stage": "placement"})
