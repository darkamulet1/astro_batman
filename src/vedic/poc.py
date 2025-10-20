"""Proof-of-concept pipeline aligned with the Vedic architecture.

The sample demonstrates how the computation core stitches together the
``astro.ephemeris`` and ``astro.sidereal`` services to produce tropical and
sidereal longitudes for the Sun, Moon, and Ascendant.  A pytest regression
that compares the ascendant against Parāśara's Light can be written as::

    from datetime import datetime, timezone
    from vedic.poc import Location, compute_sample

    def test_mehran_chart_accuracy():
        dt = datetime(1979, 10, 12, 4, 30, tzinfo=timezone.utc)
        result = compute_sample(dt, Location(35.6892, 51.3890))
        assert abs(result.ascendant.sidereal_deg - 207.8667) < 1.0

The focus here is numerical correctness (Meeus 1998; BPHS ch. 3) and clean
integration hooks for future production services.
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional, Sequence

from skyfield.api import Time

from astro.ephemeris import KernelAcquisitionError, SkyfieldEphemeris
from astro.sidereal import AyanamsaService, LahiriFallbackAyanamsaService

__all__ = [
    "BodyLongitude",
    "Location",
    "VedicSample",
    "compute_sample",
    "format_dms",
    "main",
]

# ---------------------------------------------------------------------------
# Fundamental constants (Meeus, *Astronomical Algorithms*, 2nd ed.)
# ---------------------------------------------------------------------------
DEGREES_PER_CIRCLE = 360.0
DEGREES_PER_HOUR = 15.0
TWO_PI = 2.0 * math.pi


@dataclass(frozen=True)
class Location:
    """Observer location in geodetic degrees (latitude, longitude)."""

    latitude_deg: float
    longitude_deg: float  # East positive per IAU 2006 resolution.


@dataclass(frozen=True)
class BodyLongitude:
    """Container storing tropical and sidereal ecliptic longitudes."""

    tropical_deg: float
    sidereal_deg: float


@dataclass(frozen=True)
class VedicSample:
    """Bundle of values emitted by the proof-of-concept pipeline."""

    timestamp_tt_jd: float
    location: Location
    ayanamsa_deg: float
    sun: BodyLongitude
    moon: BodyLongitude
    ascendant: BodyLongitude


def compute_sample(
    dt: datetime,
    location: Location,
    *,
    ephemeris: Optional[SkyfieldEphemeris] = None,
    ayanamsa_service: Optional[AyanamsaService] = None,
) -> VedicSample:
    """Compute tropical/sidereal coordinates for the main Vedic pillars.

    Parameters
    ----------
    dt:
        Timestamp of interest.  Must be timezone-aware; internally converted to
        TT/TDB via Skyfield so that all coordinates live in the dynamical frame.
    location:
        Observer position.
    ephemeris:
        Optional Skyfield adapter.  A default instance is created otherwise.
    ayanamsa_service:
        Service that supplies Lahiri ayanamsa values.  Defaults to the
        polynomial fallback that mirrors BPHS/IAU 1976 precession.
    """

    ephem = ephemeris or SkyfieldEphemeris()
    ayanamsa_provider = ayanamsa_service or LahiriFallbackAyanamsaService()

    ts_time = ephem.to_time(_ensure_timezone(dt))
    true_obliquity = _true_obliquity_rad(ts_time)
    ayanamsa = ayanamsa_provider.lahiri(ts_time)

    sun_tropical = _wrap_degrees(ephem.ecliptic_longitude("sun", ts_time))
    moon_tropical = _wrap_degrees(ephem.ecliptic_longitude("moon", ts_time))
    asc_tropical = _compute_ascendant(ts_time, location, true_obliquity)

    sun_sidereal = _wrap_degrees(sun_tropical - ayanamsa)
    moon_sidereal = _wrap_degrees(moon_tropical - ayanamsa)
    asc_sidereal = _wrap_degrees(asc_tropical - ayanamsa)

    return VedicSample(
        timestamp_tt_jd=ts_time.tt,
        location=location,
        ayanamsa_deg=ayanamsa,
        sun=BodyLongitude(sun_tropical, sun_sidereal),
        moon=BodyLongitude(moon_tropical, moon_sidereal),
        ascendant=BodyLongitude(asc_tropical, asc_sidereal),
    )


def _ensure_timezone(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("datetime must be timezone-aware to avoid UTC/TT drift")
    return dt


def _true_obliquity_rad(time: Time) -> float:
    """Return the true obliquity of the ecliptic in radians.

    Skyfield exposes the mean obliquity and nutation delta-epsilon following the
    IAU 2000A series (see IERS Conventions 2010).  Their sum yields the true
    obliquity required for the ascendant calculation.
    """

    mean_obliquity = time._mean_obliquity_radians  # Skyfield internal (rad).
    _, delta_epsilon = time._nutation_angles_radians  # (Δψ, Δε) in radians.
    return mean_obliquity + delta_epsilon


def _compute_ascendant(time: Time, location: Location, obliquity_rad: float) -> float:
    """Compute the tropical ecliptic longitude of the ascendant (degrees).

    Formula based on Meeus (1998, ch. 12) & BPHS using local apparent sidereal
    time (LST), true obliquity (ε), and geodetic latitude (φ)::

        λasc = atan2(sin(LST)·cos ε − tan φ·sin ε, cos(LST))

    Parameters are supplied in radians with longitude east-positive.
    """

    lst_degrees = _local_sidereal_degrees(time, location.longitude_deg)
    lst_rad = math.radians(lst_degrees)
    latitude_rad = math.radians(location.latitude_deg)

    numerator = math.sin(lst_rad) * math.cos(obliquity_rad) - math.tan(
        latitude_rad
    ) * math.sin(obliquity_rad)
    denominator = math.cos(lst_rad)
    ascendant_rad = math.atan2(numerator, denominator)
    if ascendant_rad < 0.0:
        ascendant_rad += TWO_PI
    return _wrap_degrees(math.degrees(ascendant_rad))


def _local_sidereal_degrees(time: Time, longitude_deg: float) -> float:
    """Return local apparent sidereal time in degrees at the observer's meridian."""

    gast_hours = time.gast % 24.0
    gst_degrees = gast_hours * DEGREES_PER_HOUR
    return _wrap_degrees(gst_degrees + longitude_deg)


def _wrap_degrees(angle: float) -> float:
    wrapped = math.fmod(angle, DEGREES_PER_CIRCLE)
    return wrapped + DEGREES_PER_CIRCLE if wrapped < 0.0 else wrapped


def format_dms(angle: float, *, precision: int = 2) -> str:
    """Format a degree value as D°M′S″ with configurable precision."""

    wrapped = _wrap_degrees(angle)
    degrees = int(wrapped)
    minutes_total = (wrapped - degrees) * 60.0
    minutes = int(minutes_total)
    seconds = round((minutes_total - minutes) * 60.0, precision)

    if seconds >= 60.0:
        seconds -= 60.0
        minutes += 1
    if minutes >= 60:
        minutes -= 60
        degrees = (degrees + 1) % int(DEGREES_PER_CIRCLE)

    return f"{degrees:03d}°{minutes:02d}′{seconds:0{4 + precision}.{precision}f}″"


def _print_sample(result: VedicSample) -> None:
    print(f"TT Julian Day      : {result.timestamp_tt_jd:.8f}")
    print(f"Lahiri ayanamsa    : {format_dms(result.ayanamsa_deg)} ({result.ayanamsa_deg:.6f}°)")
    for name, body in _iter_bodies(result):
        print(
            f"{name:<11}tropical {format_dms(body.tropical_deg)}"
            f"  | sidereal {format_dms(body.sidereal_deg)}"
            f"  ({body.sidereal_deg:.6f}°)"
        )


def _iter_bodies(result: VedicSample) -> Iterable[tuple[str, BodyLongitude]]:
    yield "Sun", result.sun
    yield "Moon", result.moon
    yield "Ascendant", result.ascendant


def _parse_args(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--datetime", required=True, help="ISO-8601 timestamp with offset")
    parser.add_argument("--lat", type=float, required=True, help="Latitude in degrees (north +)")
    parser.add_argument("--lon", type=float, required=True, help="Longitude in degrees (east +)")
    return parser.parse_args(argv)


def _parse_datetime(value: str) -> datetime:
    normalised = value.strip()
    if normalised.endswith("Z"):
        normalised = normalised[:-1] + "+00:00"
    dt = datetime.fromisoformat(normalised)
    if dt.tzinfo is None:
        raise ValueError("Datetime must include a timezone offset")
    return dt


def main(argv: Optional[Sequence[str]] = None) -> VedicSample:
    args = _parse_args(argv)
    dt = _parse_datetime(args.datetime)
    location = Location(latitude_deg=args.lat, longitude_deg=args.lon)

    try:
        result = compute_sample(dt, location)
    except KernelAcquisitionError as exc:
        print(f"Kernel warning: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    _print_sample(result)
    return result


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
