"""
DEPRECATED — this file is kept only as a compatibility shim.

Import from the package instead:
    from lastz.flows.alliance_gifts import run_alliance_gifts_flow
"""
import warnings
warnings.warn(
    "alliance_gifts_auto.py is deprecated. "
    "Use 'from lastz.flows.alliance_gifts import run_alliance_gifts_flow'.",
    DeprecationWarning,
    stacklevel=2,
)

from lastz.flows.alliance_gifts import run_alliance_gifts_flow, _claim_tab as claim_gifts_with_templates
