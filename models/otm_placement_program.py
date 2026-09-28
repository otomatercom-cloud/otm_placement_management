# -*- coding: utf-8 -*-
from odoo import fields, models


class OtmPlacementProgram(models.Model):
    _name = "otm.placement.program"
    _description = "Placement Program"
    _order = "sequence, name"

    name = fields.Char(required=True)
    code = fields.Char(help="Short code, e.g. ACCA, CMA")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    _name_uniq = models.Constraint(
        "unique(name)", "A program with this name already exists."
    )
