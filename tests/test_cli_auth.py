from __future__ import annotations

from fleet.cli import _mask_secret


def test_mask_secret_redacts_short_values():
    assert _mask_secret("short-key") == "[redacted]"


def test_mask_secret_keeps_prefix_and_suffix_for_long_values():
    assert _mask_secret("abcdefgh1234567890") == "abcdefgh...7890"
