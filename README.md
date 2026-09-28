# Placement & Mock Interview Management (`otm_placement_management`)

Odoo 19 Community module for Career & Placement Support: a public
registration portal, online/offline mock interview booking with
double-booking protection, interview scheduling, placement tracking,
a candidate portal, and a management dashboard.

Otomater · OPL-1 license · model prefix `otm.`

## What's included

- **Public portal** — `/placement/register`: a mobile-first, animated
  multi-step registration + slot-booking flow (no login required).
- **Booking success page** — `/placement/booking/success/<token>`,
  secured by an unguessable per-candidate token (never a raw database id).
- **Candidate portal** — `/my-placement`, `/my-placement/interview` for
  logged-in portal users, with cancel/reschedule requests.
- **Backend**: Candidates (Kanban/list/form + chatter), Interview Slots
  (list/calendar), Mock Interviews (calendar/list/form), Reschedule
  Requests, Placement Records, a Dashboard (pivot/graph), and
  Configuration (Programs, Support Areas, Interviewers).
- **Security**: three groups (Placement User / Manager / Administrator)
  built on the Odoo 19 `res.groups.privilege` pattern, with record rules
  limiting a Placement User's write access to their own assigned
  candidates.
- **Notifications**: 5 mail templates (registration, booking confirmed,
  reminder, rescheduled, cancelled) plus provider-agnostic
  `action_send_whatsapp_*` stub methods ready to wire to a real WhatsApp
  integration (e.g. an existing `otm_whatsapp_coexistence`-style module)
  without touching anything else.
- **Cron**: hourly reminder job, idempotent via a `reminder_sent` flag.

## Booking concurrency

Slot booking (`otm.placement.mock.interview.book_slot()`) uses a real
`SELECT ... FOR UPDATE` row lock plus a raw atomic `UPDATE` to increment
the booked count, so two simultaneous requests for the last seat can
never both succeed — this was verified with a real Postgres-backed test
that books a slot with capacity 1 twice in a row and confirms the second
attempt is rejected with no overbooking.

## Verification performed

This module was verified against a **real Odoo 19.0 install** (a fresh
`odoo/odoo@19.0` checkout + local PostgreSQL), not just static checks:

1. Clean `-i` install: 0 errors, 0 warnings for this module.
2. Clean `-u` upgrade: 0 errors, 0 warnings.
3. A real `odoo-bin shell` test script covering: candidate creation +
   sequence numbering, atomic slot booking, a rejected double-booking on
   a full slot, offline booking with venue, the reschedule-approval flow
   (frees the old slot, books the new one), placement-record → candidate
   stage sync, the reminder cron method, and record-rule access as a real
   non-superuser "Placement User".
4. A real HTTP-level test: a live `odoo-bin` server, hit with `curl` —
   `GET /placement/register` (real page render, CSRF token present),
   `POST /placement/register/submit`, `GET /placement/slots`,
   `POST /placement/book`, and `GET /placement/booking/success/<token>`,
   confirming the slot flips from available to booked and the
   confirmation page renders correctly.

Several real Odoo 19 issues were found and fixed this way that no static
checker would have caught, including: `ir.cron` no longer has a
`numbercall` field; a search-view filter can't reference a non-stored
compute field; and — the subtlest one — a stored compute field
(`available_count`) that gets lazily computed and queued as a pending
ORM write can be silently flushed back over a raw SQL value later in the
same transaction unless the whole record is flushed *before* the raw SQL
runs.

## Known limitations / next steps

- **WhatsApp**: architecture is in place (`action_send_whatsapp_*`
  methods, called at the right points), but no real provider is wired in
  — it currently just logs to the chatter. Point it at your WhatsApp
  Business API/BSP of choice.
- **Portal account creation**: candidates are not auto-provisioned a
  portal login. The anonymous, token-secured booking-success page covers
  the "view my booking" need without one; for a full logged-in portal
  experience, grant portal access to the candidate's linked contact
  through the standard Odoo "Grant Portal Access" action and the
  `/my-placement` pages will pick them up automatically (matched by
  email on first visit).
- **Dashboard**: built from native Odoo pivot/graph/kanban views rather
  than a hand-rolled OWL dashboard widget, deliberately — this sandbox
  has no browser to verify client-side JavaScript against (a real
  browser-only bug class per this project's own Odoo 19 findings log),
  so native views were chosen as the lower-risk, still fully functional
  option. It can be upgraded to a custom OWL dashboard later if desired.
- **PDF reports**: not included in this build (not requested in scope).

## Installation

```
python3 odoo-bin -d <db> --addons-path=addons,<path-to-this-module's-parent> \
    -i otm_placement_management
```

Requires: `base`, `mail`, `web`, `website`, `portal` (all core Odoo 19
Community modules — no Enterprise dependency).
