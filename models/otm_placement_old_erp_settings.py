# -*- coding: utf-8 -*-
from odoo import api, fields, models


class OtmPlacementOldErpSettings(models.Model):
    """Connection settings for the separate (Odoo 17) Leads/Admission ERP.

    Singleton-style config record — always id=1, created lazily by
    get_settings(). Kept as a plain Model (not res.config.settings) so it
    has its own menu under Placement > Configuration, matching how the
    rest of this module's configuration is organised.
    """

    _name = "otm.placement.old.erp.settings"
    _description = "Old ERP (Leads) Connection Settings"

    name = fields.Char(default="Old ERP Connection", required=True)
    url = fields.Char(
        string="Old ERP URL",
        help="Base URL of the Odoo 17 ERP, e.g. https://erp.example.com "
             "(no trailing slash, no /xmlrpc suffix).",
    )
    database = fields.Char(string="Database Name")
    username = fields.Char(string="API Username", help="Login of an Odoo 17 user with read access to the Leads module.")
    api_key = fields.Char(
        string="API Key / Password",
        help="API key (recommended) or password for the above user.",
    )
    active = fields.Boolean(
        string="Enabled", default=True,
        help="Turn off to stop the placement module from trying to reach the old ERP.",
    )

    @api.model
    def get_settings(self):
        """Return the singleton settings record, creating it if missing."""
        settings = self.search([], limit=1)
        if not settings:
            settings = self.create({})
        return settings

    def action_open_settings(self):
        """Always open the singleton record (creating it if missing),
        instead of a blank 'new record' form."""
        settings = self.get_settings()
        return {
            "type": "ir.actions.act_window",
            "name": "Old ERP Connection",
            "res_model": "otm.placement.old.erp.settings",
            "view_mode": "form",
            "res_id": settings.id,
            "target": "current",
        }

    def action_test_connection(self):
        self.ensure_one()
        result = self.env["otm.placement.old.erp.client"].test_connection(self)
        if result.get("ok"):
            message = "Connected successfully as user id %s." % result.get("uid")
            notif_type = "success"
        else:
            message = result.get("error") or "Connection failed."
            notif_type = "danger"
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Old ERP Connection",
                "message": message,
                "type": notif_type,
                "sticky": False,
            },
        }
