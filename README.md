Odoo-side changes for the Placement Console (Next.js frontend)
================================================================

Copy these into otm_placement_management/controllers/ on the Odoo server
(this __init__.py just adds one import line vs. the existing file - merge
it rather than overwriting if you've changed that file since):

  controllers/api_bff.py   <- new file
  controllers/__init__.py  <- added "from . import api_bff"

Then upgrade the module and set the otm_placement_management.bff_secret
system parameter. Full steps are in the Next.js app's README.md, section 1.
