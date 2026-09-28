{
    "name": "Placement & Mock Interview Management",
    "version": "19.0.1.0.0",
    "category": "Human Resources",
    "summary": "Career & Placement Support: registration portal, mock interview booking, interview scheduling, placement tracking",
    "description": """
Placement & Mock Interview Management (Otomater)
=================================================
* Public career/placement registration portal (multi-step, mobile-first)
* Online/offline mock interview slot booking with double-booking protection
* Interview scheduling, calendar, reminders
* Placement tracking and dashboard/reporting
* Candidate portal (My Interview, My Placement Status)
* Email notifications, WhatsApp-ready notification architecture
""",
    "author": "Otomater",
    "website": "https://otomater.com",
    "license": "OPL-1",
    "depends": ["base", "mail", "web", "website", "portal"],
    "data": [
        "security/otm_placement_security.xml",
        "security/ir.model.access.csv",
        "data/otm_placement_sequence.xml",
        "data/otm_placement_config_data.xml",
        "data/otm_placement_mail_templates.xml",
        "data/otm_placement_cron.xml",
        "views/otm_placement_config_views.xml",
        "views/otm_placement_candidate_views.xml",
        "views/otm_placement_interview_slot_views.xml",
        "wizard/otm_placement_slot_generator_views.xml",
        "views/otm_placement_mock_interview_views.xml",
        "views/otm_placement_reschedule_request_views.xml",
        "views/otm_placement_record_views.xml",
        "views/otm_placement_dashboard_views.xml",
        "views/otm_placement_menus.xml",
        "views/otm_placement_portal_templates.xml",
        "views/otm_placement_website_templates.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "otm_placement_management/static/src/css/placement.css",
            "otm_placement_management/static/src/js/placement.js",
            "otm_placement_management/static/src/js/placement_book_interview.js",
        ],
        "web.assets_backend": [
            "otm_placement_management/static/src/css/otm_placement_dashboard.css",
            "otm_placement_management/static/src/js/dashboard/otm_placement_dashboard.js",
            "otm_placement_management/static/src/xml/otm_placement_dashboard.xml",
        ],
    },
    "installable": True,
    "application": True,
    "auto_install": False,
}
