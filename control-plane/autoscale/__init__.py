from autoscale.policy import AutoscaleConfig, Decision, clamp_to_capacity, decide
from autoscale.signal import LoadObservation, LoadSignal

# `loop` is deliberately not re-exported here: it is the module run as
# `python -m autoscale.loop`, and importing it from the package __init__ makes
# runpy execute it twice. Import from autoscale.loop directly.
__all__ = [
    "AutoscaleConfig",
    "Decision",
    "LoadObservation",
    "LoadSignal",
    "clamp_to_capacity",
    "decide",
]
