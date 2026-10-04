"""Safe constant-time comparison for request-derived service credentials."""

from __future__ import annotations

import hmac


def secure_compare_str(supplied: str, expected: str) -> bool:
    """Compare credentials without raising for non-ASCII request bytes."""

    return hmac.compare_digest(
        supplied.encode("utf-8", "surrogateescape"),
        expected.encode("utf-8", "surrogateescape"),
    )


__all__ = ["secure_compare_str"]
