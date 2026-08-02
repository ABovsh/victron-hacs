"""Tests for encryption-key validation in the config flow."""

import pytest

from custom_components.victron_ble.config_flow import InvalidKey, validate_key

VALID = "0123456789abcdef0123456789abcdef"


def test_accepts_a_16_byte_hex_key():
    assert validate_key(VALID) == VALID


def test_normalises_case_and_whitespace():
    """VictronConnect shows the key in groups; users paste it verbatim."""
    assert validate_key("  0123456789ABCDEF0123456789abcdef ") == VALID


@pytest.mark.parametrize(
    "key",
    [
        "",
        "not-hex-at-all",
        "0123456789abcdef",  # 8 bytes, too short
        "0123456789abcdef0123456789abcdefab",  # 17 bytes, too long
        "0123456789abcdef0123456789abcdeg",  # right length, bad char
    ],
)
def test_rejects_malformed_keys(key):
    """A bad key otherwise yields a configured device with no entities at all."""
    with pytest.raises(InvalidKey):
        validate_key(key)
