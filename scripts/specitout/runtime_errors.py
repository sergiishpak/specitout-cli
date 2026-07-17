from __future__ import annotations


class SpecItOutRuntimeError(RuntimeError):
    """Raised when the local runtime cannot be bootstrapped safely."""
