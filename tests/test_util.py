"""Tests for the stdlib-only URL parsing helpers."""
import os
import sys

import pytest

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "custom_components", "hadron"),
)

from util import InvalidTriggerUrl, parse_trigger_url  # noqa: E402


def test_parse_plain_url():
    parsed = parse_trigger_url(
        "https://hadronmemory.com/hooks/whs_abc123/desk-light"
    )
    assert parsed.url == "https://hadronmemory.com/hooks/whs_abc123/desk-light"
    assert parsed.secret == "whs_abc123"
    assert parsed.name == "desk-light"
    assert parsed.token is None


def test_parse_url_with_embedded_token():
    parsed = parse_trigger_url(
        "https://hadronmemory.com/hooks/whs_abc/notify?hpt=eyJ0.abc.def"
    )
    assert parsed.url == "https://hadronmemory.com/hooks/whs_abc/notify"
    assert parsed.token == "eyJ0.abc.def"


def test_parse_strips_trailing_slash_and_whitespace():
    parsed = parse_trigger_url(
        "  https://example.com/hooks/whs_x/morning-briefing/  "
    )
    assert parsed.url == "https://example.com/hooks/whs_x/morning-briefing"
    assert parsed.name == "morning-briefing"


def test_parse_keeps_port_and_http_scheme():
    parsed = parse_trigger_url("http://localhost:4000/hooks/whs_dev/test")
    assert parsed.url == "http://localhost:4000/hooks/whs_dev/test"


@pytest.mark.parametrize(
    "raw",
    [
        "not a url",
        "ftp://example.com/hooks/whs_a/b",
        "https://example.com/hooks/whs_a",  # missing name
        "https://example.com/hooks/whs_a/b/c",  # extra segment
        "https://example.com/api/hooks/whs_a/b",  # wrong prefix
        "https://example.com/",
    ],
)
def test_parse_rejects_non_trigger_urls(raw):
    with pytest.raises(InvalidTriggerUrl):
        parse_trigger_url(raw)


def test_other_query_params_do_not_count_as_token():
    parsed = parse_trigger_url("https://example.com/hooks/whs_a/b?foo=bar")
    assert parsed.token is None
    assert parsed.url == "https://example.com/hooks/whs_a/b"
