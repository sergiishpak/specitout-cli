from __future__ import annotations

from collections.abc import Callable


ImportProgressReporter = Callable[[str, int, int, str], None]
IndexProgressReporter = Callable[[str, int, int, str], None]
