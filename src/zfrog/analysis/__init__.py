"""Analyses built on top of clones, snapshots and versions.

Each module here is independent: :mod:`zfrog.analysis.trends` follows a term
across a site's snapshot history, :mod:`zfrog.analysis.competitive` puts several
clones side by side. Import them by name (``from zfrog.analysis import
competitive``) — the package re-exports nothing on purpose, so using one
analysis never drags another one's imports in.
"""

from __future__ import annotations
