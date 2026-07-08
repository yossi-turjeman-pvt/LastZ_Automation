"""
DEPRECATED — this file is kept only as a compatibility shim.

Import from the package instead:
    from lastz.flows.battle_rewards import run_battle_rewards_flow
"""
import warnings
warnings.warn(
    "battle_rewards_auto.py is deprecated. "
    "Use 'from lastz.flows.battle_rewards import run_battle_rewards_flow'.",
    DeprecationWarning,
    stacklevel=2,
)

from lastz.flows.battle_rewards import run_battle_rewards_flow
