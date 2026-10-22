"""g3xn: build, edit and play Zoom G3n / G3Xn patches from code.

    from g3xn import Pedal, Patch, catalog

    catalog().get("TS Drive").params      # every knob, range and default
    p = Patch.blank("CRUNCH")
    p.add("TS Drive", Gain=30)
    p.add("MS 1959", Gain=60)

    with Pedal() as pedal:
        pedal.audition(p)                 # hear it on the scratch slot
"""
from .catalog import Catalog, Effect, Param, catalog
from .patch import ChainEffect, Patch, Slot
from .pedal import Pedal, PedalError

__all__ = ["Catalog", "ChainEffect", "Effect", "Param", "Patch", "Pedal", "PedalError", "Slot", "catalog"]
__version__ = "0.1.0"
