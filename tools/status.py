"""Environment status helper for Vedic ephemeris tooling.

This CLI reports the active Python environment and ensures a usable Skyfield
kernel is available, downloading the public DE421 file when necessary.
"""

from __future__ import annotations

import argparse
import platform
import sys
from pathlib import Path
from typing import Optional

from astro.ephemeris import KernelAcquisitionError, ensure_kernel_available


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--print-only-path",
        action="store_true",
        help="Suppress environment info and print the kernel path only.",
    )
    args = parser.parse_args(argv)

    try:
        kernel_path = Path(ensure_kernel_available())
    except KernelAcquisitionError as exc:
        print(f"Kernel warning: {exc}", file=sys.stderr)
        return 2

    if args.print_only_path:
        print(str(kernel_path))
        return 0

    print(f"Python {platform.python_version()} ({sys.executable})")
    print(f"Kernel ready at: {kernel_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
