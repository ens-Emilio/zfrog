"""Polite browser identity for capture.

zfrog captures the visual design of public pages. That needs no evasion: a
single stable user-agent, a fixed desktop viewport, and the polite crawl delay
the orchestrator already applies between requests. Anything beyond that —
fingerprint spoofing, human-behavior simulation, CAPTCHA handling, alternate
browser binaries — belongs to scraping against a site's will, which is not what
this tool does.
"""

from __future__ import annotations

#: One stable identity, sent on every request. Stable on purpose: rotating it
#: per request is what evasion looks like, and a design capture has no reason
#: to hide which client it is.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

#: Fixed desktop viewport for captures. Per-device viewports are a capture
#: option of the future multi-resolution feature, not randomization.
VIEWPORT = {"width": 1440, "height": 900}

#: Locale for rendering. Fixed for the same reason as the user-agent.
LOCALE = "en-US"


def user_agent() -> str:
    """Return the browser identity sent on every request."""
    return USER_AGENT


def viewport() -> dict:
    """Return a copy of the default capture viewport."""
    return dict(VIEWPORT)


def locale() -> str:
    """Return the locale used for rendering."""
    return LOCALE


__all__ = ["LOCALE", "USER_AGENT", "VIEWPORT", "locale", "user_agent", "viewport"]
