# -*- coding: utf-8 -*-
from odoo import fields, models


class OtmPlacementSupportArea(models.Model):
    _name = "otm.placement.support.area"
    _description = "Placement Support Area"
    _order = "sequence, name"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    _name_uniq = models.Constraint(
        "unique(name)", "A support area with this name already exists."
    )
