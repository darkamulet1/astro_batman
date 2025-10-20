"""Skyfield-based ephemeris abstractions for Vedic calculations.

The goal of this module is to provide a thin adapter around Skyfield's
high-precision JPL Development ephemerides while keeping the rest of the code
agnostic to the underlying provider.  The design follows the layering defined
in ``docs/vedic_architecture.md`` where this module is part of the
``astro.ephemeris`` layer feeding higher level services.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional
from urllib.error import URLError
from urllib.request import urlopen

from skyfield.api import Loader, Time, Timescale, load_file
from skyfield.vectorlib import VectorFunction

__all__ = [
    "DEFAULT_EPHEMERIS_NAME",
    "ensure_kernel_available",
    "SKYFIELD_DATA_DIRECTORY",
    "SKYFIELD_HOME_DIRECTORY",
    "KernelAcquisitionError",
    "SkyfieldEphemeris",
]

# ---------------------------------------------------------------------------
# Module level constants
# ---------------------------------------------------------------------------
# Skyfield's official short ephemeris that spans 1550-2650 (see JPL DE440s).
# Source: Jet Propulsion Laboratory Development Ephemeris DE440 (Park et al.,
# 2021, JPL Interoffice Memorandum IOM 392R-20-003).
DEFAULT_EPHEMERIS_NAME = "de440s.bsp"

# Location to cache ephemeris data within the repository so the environment can
# pre-populate it without relying on network access at runtime.
SKYFIELD_DATA_DIRECTORY = (
    Path(__file__).resolve().parents[2] / "data" / "skyfield"
)
"""Directory for caching Skyfield binary ephemeris files."""

SKYFIELD_HOME_DIRECTORY = Path.home() / ".skyfield"
"""User-specific Skyfield cache directory (matches Skyfield defaults)."""

KERNEL_CANDIDATE_NAMES: tuple[str, ...] = (
    "de440s.bsp",
    "de440.bsp",
    "de421.bsp",
)
"""Preferred kernel filenames in descending accuracy order."""

JPL_DE421_URL = "https://ssd.jpl.nasa.gov/ftp/eph/planets/bsp/de421.bsp"
"""Canonical download endpoint for the public DE421 ephemeris."""


class KernelAcquisitionError(FileNotFoundError):
    """Raised when no suitable JPL kernel could be located or fetched."""


def ensure_kernel_available(
    preferred_name: str = DEFAULT_EPHEMERIS_NAME,
    *,
    extra_search_paths: Optional[Iterable[Path]] = None,
) -> str:
    """Return the filesystem path of a usable Skyfield kernel.

    Search order:

    1. Explicit :envvar:`VEDIC_EPHEMERIS_PATH` override.
    2. Extra directories supplied via ``extra_search_paths``.
    3. User cache ``~/.skyfield`` (auto-created if missing).
    4. Repository cache ``data/skyfield`` for offline CI scenarios.

    If no kernel is found, DE421 is downloaded to ``~/.skyfield``.  A clear
    warning is raised if the download fails (e.g. offline environment).
    """

    env_path = os.getenv("VEDIC_EPHEMERIS_PATH")
    if env_path:
        env_candidate = Path(env_path).expanduser()
        if env_candidate.exists():
            return str(env_candidate.resolve())
        raise KernelAcquisitionError(
            f"Configured ephemeris '{env_candidate}' does not exist."
        )

    search_directories: list[Path] = []
    if extra_search_paths:
        search_directories.extend(Path(p).expanduser() for p in extra_search_paths)
    search_directories.append(SKYFIELD_HOME_DIRECTORY)
    search_directories.append(SKYFIELD_DATA_DIRECTORY)

    search_names = _candidate_names(preferred_name)
    for directory in search_directories:
        if directory == SKYFIELD_HOME_DIRECTORY:
            directory.mkdir(parents=True, exist_ok=True)
        candidate = _find_kernel_in_directory(directory, search_names)
        if candidate is not None:
            return str(candidate)

    download_target = SKYFIELD_HOME_DIRECTORY / "de421.bsp"
    try:
        _download_kernel(JPL_DE421_URL, download_target)
    except KernelAcquisitionError:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        raise KernelAcquisitionError(
            f"Failed to download ephemeris: {exc}"
        ) from exc

    print("[auto] Downloaded de421.bsp to ~/.skyfield/")
    return str(download_target.resolve())


@dataclass
class EphemerisBodies:
    """Container for frequently used solar system bodies."""

    earth: VectorFunction
    sun: VectorFunction
    moon: VectorFunction


class SkyfieldEphemeris:
    """Adapter that exposes the subset of ephemeris functionality we need.

    Parameters
    ----------
    data_directory:
        Optional override for the directory where ephemeris files are cached.
    ephemeris_name:
        Name of the Skyfield ephemeris file to load when an explicit path is
        not provided via :envvar:`VEDIC_EPHEMERIS_PATH`.
    """

    def __init__(
        self,
        data_directory: Optional[Path] = None,
        ephemeris_name: str = DEFAULT_EPHEMERIS_NAME,
    ) -> None:
        kernel_path = self._resolve_kernel_path(
            ephemeris_name, data_directory=data_directory
        )
        self._data_directory = kernel_path.parent
        self._loader = Loader(str(self._data_directory))
        self._timescale = self._loader.timescale()

        self._ephemeris = load_file(str(kernel_path))
        self._bodies = EphemerisBodies(
            earth=self._ephemeris["earth"],
            sun=self._ephemeris["sun"],
            moon=self._ephemeris["moon"],
        )

    @property
    def bodies(self) -> EphemerisBodies:
        return self._bodies

    @property
    def timescale(self) -> Timescale:
        return self._timescale

    def to_time(self, dt: datetime) -> Time:
        """Convert a timezone-aware :class:`datetime` into Skyfield ``Time``.

        The input timestamp is normalised to UTC before feeding it to Skyfield.
        Skyfield internally propagates the instant into TT/TDB, ensuring the
        downstream calculations operate consistently in the dynamical frame.
        """

        if dt.tzinfo is None:
            raise ValueError("datetime must be timezone aware")
        dt_utc = dt.astimezone(timezone.utc)
        return self._timescale.from_datetime(dt_utc)

    def _resolve_kernel_path(
        self,
        ephemeris_name: str,
        *,
        data_directory: Optional[Path],
    ) -> Path:
        extra_paths: list[Path] = []
        if data_directory is not None:
            extra_paths.append(Path(data_directory))

        kernel_path = ensure_kernel_available(
            ephemeris_name, extra_search_paths=extra_paths
        )
        return Path(kernel_path).expanduser().resolve()

    def ecliptic_longitude(self, body: str, time: Time) -> float:
        """Return the true ecliptic longitude (degrees) of a solar system body.

        Parameters
        ----------
        body:
            Key in the loaded ephemeris (currently ``"sun"`` or ``"moon"``).
        time:
            Skyfield ``Time`` instance; computations are referenced to TT/TDB.
        """

        try:
            target = getattr(self._bodies, body)
        except AttributeError as exc:  # pragma: no cover - defensive branch
            raise ValueError(f"Body '{body}' is not available in the ephemeris") from exc
        lat, lon = _ecliptic_latlon_degrees(self._bodies.earth, target, time)
        return lon


def _ecliptic_latlon_degrees(
    earth: VectorFunction, target: VectorFunction, time: Time
) -> tuple[float, float]:
    """Helper returning latitude & longitude of ``target`` (degrees)."""

    apparent = earth.at(time).observe(target).apparent()
    lat_angle, lon_angle, _ = apparent.ecliptic_latlon(epoch=time)
    return lat_angle.degrees, lon_angle.degrees


def _candidate_names(preferred: str) -> tuple[str, ...]:
    names = [preferred]
    for fallback in KERNEL_CANDIDATE_NAMES:
        if fallback not in names:
            names.append(fallback)
    return tuple(names)


def _find_kernel_in_directory(
    directory: Path, candidates: Iterable[str]
) -> Optional[Path]:
    for name in candidates:
        path = directory / name
        if path.exists():
            return path.resolve()
    return None


def _download_kernel(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Optional[Path] = None
    try:
        with urlopen(url) as response:
            if getattr(response, "status", 200) >= 400:
                raise KernelAcquisitionError(
                    f"HTTP error {response.status} while downloading {url}"
                )
            with tempfile.NamedTemporaryFile(
                delete=False, dir=str(destination.parent)
            ) as tmp:
                shutil.copyfileobj(response, tmp)
                tmp_path = Path(tmp.name)
        if tmp_path is None:
            raise KernelAcquisitionError("Download failed: empty response.")
        tmp_path.replace(destination)
    except URLError as exc:
        if tmp_path:
            tmp_path.unlink(missing_ok=True)
        raise KernelAcquisitionError(
            "No JPL kernel available locally and network download failed. "
            "Please ensure internet connectivity or supply VEDIC_EPHEMERIS_PATH."
        ) from exc
    except OSError as exc:
        if tmp_path:
            tmp_path.unlink(missing_ok=True)
        raise KernelAcquisitionError(
            f"Unable to store downloaded kernel at {destination}: {exc}"
        ) from exc
