"""Namespace package wrapper that exposes the implementation under ``src``."""

from __future__ import annotations

from pathlib import Path

_pkg_dir = Path(__file__).resolve().parent
_src_pkg = _pkg_dir.parent / "src" / "vedic"
if _src_pkg.exists():
    __path__.append(str(_src_pkg))  # type: ignore[name-defined]
