# -*- coding: utf-8 -*-
import logging
import xmlrpc.client

from odoo import models

_logger = logging.getLogger(__name__)

CONNECT_TIMEOUT = 8  # seconds — never let a public/staff action hang on a dead ERP


class _TimeoutTransport(xmlrpc.client.Transport):
    """xmlrpc.client has no built-in timeout; wire one through http.client."""

    def __init__(self, timeout, use_https=True):
        super().__init__()
        self._timeout = timeout
        self._use_https = use_https

    def make_connection(self, host):
        import http.client

        if self._use_https:
            conn = http.client.HTTPSConnection(host, timeout=self._timeout)
        else:
            conn = http.client.HTTPConnection(host, timeout=self._timeout)
        return conn


def _server_proxy(url, timeout=CONNECT_TIMEOUT):
    transport = _TimeoutTransport(timeout, use_https=url.startswith("https"))
    return xmlrpc.client.ServerProxy(url, transport=transport, allow_none=True)


class OtmPlacementOldErpClient(models.AbstractModel):
    """XML-RPC bridge to the separate Odoo 17 Leads/Admission ERP.

    Every public method here is defensive: a missing configuration, a
    network failure, or an unexpected response from the remote ERP is
    caught and turned into a friendly 'unavailable' result rather than
    raised, so this integration can never break candidate registration
    or the backend UI.
    """

    _name = "otm.placement.old.erp.client"
    _description = "Old ERP (Leads) XML-RPC Bridge"

    # ------------------------------------------------------------------
    # Connection helpers
    # ------------------------------------------------------------------
    def _get_settings(self):
        Settings = self.env["otm.placement.old.erp.settings"].sudo()
        settings = Settings.search([], limit=1)
        if not settings or not settings.active:
            return None
        if not (settings.url and settings.database and settings.username and settings.api_key):
            return None
        return settings

    def _authenticate(self, settings):
        common = _server_proxy("%s/xmlrpc/2/common" % settings.url.rstrip("/"))
        uid = common.authenticate(settings.database, settings.username, settings.api_key, {})
        return uid

    @staticmethod
    def _normalize_phone(phone):
        digits = "".join(ch for ch in (phone or "") if ch.isdigit())
        return digits[-10:] if len(digits) >= 10 else digits

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def test_connection(self, settings=None):
        settings = settings or self._get_settings()
        if not settings or not (settings.url and settings.database and settings.username and settings.api_key):
            return {"ok": False, "error": "Connection is not fully configured."}
        try:
            uid = self._authenticate(settings)
        except Exception as exc:  # noqa: BLE001 - never let this raise
            _logger.warning("Old ERP test connection failed: %s", exc)
            return {"ok": False, "error": "Could not reach the old ERP: %s" % exc}
        if not uid:
            return {"ok": False, "error": "Authentication failed — check username/API key."}
        return {"ok": True, "uid": uid}

    def check_student_status(self, phone, email):
        """Look up `phone`/`email` in the old ERP's leads.logic model.

        Returns a dict:
            status: unavailable | not_found | lead_only | current_student | old_student
            found: bool
            label: short human label
            note: one-line human summary (or reason it's unavailable)
            raw: the matched leads.logic record dict, if any
        """
        settings = self._get_settings()
        if not settings:
            return {
                "status": "unavailable", "found": False,
                "label": "Not Configured",
                "note": "Old ERP connection is not configured or is disabled "
                        "(Placement > Configuration > Old ERP Connection).",
            }

        phone10 = self._normalize_phone(phone)
        or_terms = []
        if phone10:
            or_terms.append(("phone_number", "like", phone10))
        if email:
            or_terms.append(("email_address", "=", email))
        if not or_terms:
            return {
                "status": "unavailable", "found": False,
                "label": "No Match Criteria",
                "note": "Candidate has no phone or email to search with.",
            }
        domain = ["|"] + or_terms if len(or_terms) == 2 else or_terms

        try:
            uid = self._authenticate(settings)
            if not uid:
                return {
                    "status": "unavailable", "found": False,
                    "label": "Connection Failed",
                    "note": "Could not authenticate with the old ERP. Check the connection settings.",
                }

            models_proxy = _server_proxy("%s/xmlrpc/2/object" % settings.url.rstrip("/"))
            leads = models_proxy.execute_kw(
                settings.database, uid, settings.api_key,
                "leads.logic", "search_read",
                [domain],
                {
                    "fields": [
                        "name", "reference_no", "phone_number", "email_address",
                        "admission_status", "lead_stage_category",
                        "student_category", "student_id",
                    ],
                    "limit": 5,
                    "order": "id desc",
                },
            )
        except Exception as exc:  # noqa: BLE001 - integration must never raise
            _logger.warning("Old ERP (leads.logic) lookup failed for phone=%s: %s", phone, exc)
            return {
                "status": "unavailable", "found": False,
                "label": "Lookup Failed",
                "note": "Could not reach the old ERP right now. Please try again later.",
            }

        if not leads:
            return {
                "status": "not_found", "found": False,
                "label": "New — Not Found",
                "note": "No matching lead/student found in the old ERP.",
            }

        lead = leads[0]
        stage = lead.get("lead_stage_category")
        if stage == "alumni":
            status, label = "old_student", "Old Student (Alumni)"
        elif stage == "admission_done" or lead.get("admission_status"):
            status, label = "current_student", "Existing Student (Admission Done)"
        elif lead.get("student_id"):
            status, label = "current_student", "Existing Student"
        else:
            status, label = "lead_only", "Known Lead (Not Yet Admitted)"

        note_parts = [
            "Matched %s" % (lead.get("name") or "lead"),
        ]
        if lead.get("reference_no"):
            note_parts.append("Ref: %s" % lead["reference_no"])
        if stage:
            note_parts.append("Stage: %s" % stage)
        if lead.get("student_category"):
            note_parts.append("Category: %s" % lead["student_category"])

        return {
            "status": status,
            "found": True,
            "label": label,
            "note": " | ".join(note_parts),
            "raw": lead,
        }
