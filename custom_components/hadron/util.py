"""Pure helpers for the Hadron integration.

Stdlib-only so the test suite can import this module without a Home
Assistant installation (mirrors the pattern used in
ha-gewaesserkundlicher-dienst-bayern).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit, urlunsplit

# Hadron trigger URLs look like https://<server>/hooks/<secret>/<name>,
# optionally with the shown-once platform token appended as ?hpt=<jwt>.
_HOOKS_PATH_RE = re.compile(r"^/hooks/(?P<secret>[^/]+)/(?P<name>[^/]+)/?$")


@dataclass(frozen=True)
class ParsedTriggerUrl:
    """A validated Hadron webhook trigger URL."""

    url: str  # scheme://host/hooks/<secret>/<name> — no query string
    secret: str
    name: str
    token: str | None  # hpt, when it was embedded in the pasted URL


class InvalidTriggerUrl(ValueError):
    """The pasted string is not a Hadron webhook trigger URL."""


def parse_trigger_url(raw: str) -> ParsedTriggerUrl:
    """Parse a pasted trigger URL, extracting an embedded ?hpt= token.

    Hadron prints the URL path and platform token once at webhook
    create/rotate; users may paste them combined or separately. Raises
    InvalidTriggerUrl when the path does not match /hooks/<secret>/<name>.
    """
    parts = urlsplit(raw.strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise InvalidTriggerUrl(f"not an absolute http(s) URL: {raw!r}")
    match = _HOOKS_PATH_RE.match(parts.path)
    if not match:
        raise InvalidTriggerUrl(
            f"path {parts.path!r} does not match /hooks/<secret>/<name>"
        )
    token: str | None = None
    if parts.query:
        hpt_values = parse_qs(parts.query).get("hpt")
        if hpt_values and hpt_values[0]:
            token = hpt_values[0]
    clean = urlunsplit(
        (parts.scheme, parts.netloc, parts.path.rstrip("/"), "", "")
    )
    return ParsedTriggerUrl(
        url=clean,
        secret=match.group("secret"),
        name=match.group("name"),
        token=token,
    )
