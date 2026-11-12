"""
Files shipped inside the mobile package (web page, guides, seed tickers).

Read through the package loader (pkgutil), so they work both from a folder on a desktop
and from inside the APK, where Chaquopy keeps packages zipped.
"""

from __future__ import annotations

import pkgutil
from typing import Optional


def read(path: str) -> Optional[bytes]:
    """Bytes of mobile/<path>, or None when it is not there."""
    try:
        return pkgutil.get_data("mobile", path)
    except (FileNotFoundError, OSError):
        return None


def plotly_js() -> Optional[bytes]:
    try:
        return pkgutil.get_data("plotly", "package_data/plotly.min.js")
    except (FileNotFoundError, OSError):
        return None
