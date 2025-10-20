"""Sidereal support utilities, including ayanamsa computations.

The fallback ayanamsa matches the commonly cited Lahiri mean sidereal offset
and is intended to be swapped with a nutation-aware service in production.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

from skyfield.api import Time

__all__ = [
    "AyanamsaService",
    "LahiriFallbackAyanamsaService",
    "LAHIRI_REFERENCE_EPOCH_JD",
    "lahiri_mean_ayanamsa",
]

# ---------------------------------------------------------------------------
# Module level constants (Meeus 1998, ch. 27; Lahiri ayanamsa definition)
# ---------------------------------------------------------------------------
LAHIRI_REFERENCE_EPOCH_JD = 2415020.5
"""Julian day of 1900-01-01 00:00 TT (BPHS Lahiri reference)."""

LAHIRI_C0 = 22.460148  # degrees at epoch 1900.0 (22°27'36.53")
LAHIRI_C1 = 1.396042   # degrees/century (mean precession in longitude)
LAHIRI_C2 = 0.000308   # degrees/century^2 (Meeus eq. 27.3)
LAHIRI_C3 = 0.00000002 # degrees/century^3 (empirical refinement)


class AyanamsaService(Protocol):
    """Protocol used by the computation core to request ayanamsa values."""

    def lahiri(self, time: Time) -> float:
        """Return Lahiri ayanamsa in degrees for the supplied TT instant."""


@dataclass
class LahiriFallbackAyanamsaService:
    """Fallback implementation using the historical polynomial formula.

    The implementation mirrors the Meeus/IAU 1976 precession polynomial that is
    widely used in jyotiṣa software when no nutation-aware model is provided.
    Production deployments are expected to replace this class with one that
    calls into ``astro.sidereal.AyanamsaService`` backed by nutation-aware
    models (e.g., Swiss Ephemeris or IAU 2006 precession-nutation).
    """

    def lahiri(self, time: Time) -> float:  # type: ignore[override]
        return lahiri_mean_ayanamsa(time)


def lahiri_mean_ayanamsa(time: Time) -> float:
    """Return the Lahiri ayanamsa (mean sidereal offset) in degrees.

    Parameters
    ----------
    time:
        Skyfield ``Time`` instance measured in TT.  The polynomial below uses
        Julian centuries from 1900.0 TT, matching the canonical Lahiri
        reference.  The result is wrapped to ``[0, 360)`` degrees.
    """

    centuries = (time.tt - LAHIRI_REFERENCE_EPOCH_JD) / 36525.0
    ayanamsa = (
        LAHIRI_C0
        + centuries
        * (
            LAHIRI_C1
            + centuries * (LAHIRI_C2 - centuries * LAHIRI_C3)
        )
    )
    wrapped = math.fmod(ayanamsa, 360.0)
    return wrapped + 360.0 if wrapped < 0.0 else wrapped
