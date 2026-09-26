"""Tests for :mod:`zfrog.totp`.

The RFC 4226 Appendix D and RFC 6238 Appendix B vectors are the backbone here: they
prove the implementation agrees with the published standard rather than merely with
itself.
"""

from __future__ import annotations

import base64
import json
import stat

import pytest

from zfrog.config import settings
from zfrog.totp import (
    MIN_DIGITS,
    STORE_FILE_MODE,
    TotpStore,
    hotp,
    normalize_secret,
    parse_provisioning_uri,
    provisioning_uri,
    redact,
    seconds_remaining,
    totp,
    totp_at,
    verify,
)

# Both RFCs use the same ASCII secret: "12345678901234567890".
RFC_SECRET = b"12345678901234567890"
RFC_SECRET_B32 = base64.b32encode(RFC_SECRET).decode("ascii")  # 32 chars, no padding
# A secret whose base32 spelling does need "=" padding, for the URI round trip.
PADDED_SECRET = "JBSWY3DPEHPK3PXZ"
PADDED_SECRET_B32 = base64.b32encode(PADDED_SECRET.encode("ascii")).decode("ascii")

# RFC 4226 Appendix D.
RFC4226_VECTORS = [
    (0, "755224"),
    (1, "287082"),
    (2, "359152"),
    (3, "969429"),
    (4, "338314"),
    (5, "254676"),
    (6, "287922"),
    (7, "162583"),
    (8, "399871"),
    (9, "520489"),
]

# RFC 6238 Appendix B, SHA-1, 8 digits.
RFC6238_VECTORS = [
    (59, "94287082"),
    (1111111109, "07081804"),
    (1111111111, "14050471"),
    (1234567890, "89005924"),
    (2000000000, "69279037"),
    (20000000000, "65353130"),
]

@pytest.fixture()
def store_file(tmp_path, monkeypatch):
    """A store path under ``tmp_path``, with ``settings.output_dir`` pointed there."""
    monkeypatch.setattr(settings, "output_dir", tmp_path)
    return tmp_path / "totp.json"

# ── RFC 4226 / RFC 6238 ──────────────────────────────────────────────────────

@pytest.mark.parametrize(("counter", "expected"), RFC4226_VECTORS)
def test_rfc4226_appendix_d_vectors(counter: int, expected: str) -> None:
    assert hotp(RFC_SECRET, counter) == expected

@pytest.mark.parametrize(("counter", "expected"), RFC4226_VECTORS)
def test_rfc4226_vectors_from_base32_secret(counter: int, expected: str) -> None:
    """The same vectors must hold for the base32 spelling a user actually pastes."""
    assert hotp(RFC_SECRET_B32, counter) == expected

@pytest.mark.parametrize(("when", "expected"), RFC6238_VECTORS)
def test_rfc6238_appendix_b_vectors(when: int, expected: str) -> None:
    assert totp(RFC_SECRET, when, digits=8) == expected
    assert totp_at(RFC_SECRET, when, digits=8) == expected

def test_hotp_counter_zero_is_the_first_rfc_vector() -> None:
    """Sanity anchor: RFC 4226's counter 0 is ``755224`` for the test secret."""
    assert hotp(RFC_SECRET, 0) == "755224"

def test_six_digit_codes_are_zero_padded() -> None:
    codes = [hotp(RFC_SECRET, counter) for counter in range(50)]
    assert all(len(code) == 6 and code.isdigit() for code in codes)

    small = [code for code in codes if int(code) < 10000]
    assert small, "expected at least one code below 10000 in the first 50 counters"
    assert all(code.startswith("00") for code in small)
    # Counter 36 truncates to 3784: the padding is not theoretical.
    assert hotp(RFC_SECRET, 36) == "003784"

def test_digits_seven_and_eight_change_length_only() -> None:
    seven = hotp(RFC_SECRET, 5, digits=7)
    eight = hotp(RFC_SECRET, 5, digits=8)
    assert (seven, eight) == ("8254676", "68254676")
    # Truncation, not a different digest: the 8-digit code ends with the 7-digit one.
    assert eight[-7:] == seven

# ── secret normalization ─────────────────────────────────────────────────────

def test_normalize_secret_decodes_the_rfc_secret() -> None:
    assert normalize_secret(RFC_SECRET_B32) == RFC_SECRET

@pytest.mark.parametrize(
    "variant",
    [
        "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ",
        "gezdgnbvgy3tqojqgezdgnbvgy3tqojq",
        "GEZD GNBV GY3T QOJQ GEZD GNBV GY3T QOJQ",
        "GEZD-GNBV-GY3T-QOJQ-GEZD-GNBV-GY3T-QOJQ",
        "  gezd gnbv-gy3t qojq gezd gnbv gy3t qojq  ",
        "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ=",
    ],
)
def test_normalize_secret_accepts_pasted_spellings(variant: str) -> None:
    assert normalize_secret(variant) == RFC_SECRET

def test_every_spelling_yields_the_same_code() -> None:
    variants = [
        RFC_SECRET_B32,
        RFC_SECRET_B32.lower(),
        " ".join(RFC_SECRET_B32[i : i + 4] for i in range(0, 32, 4)),
        "-".join(RFC_SECRET_B32[i : i + 4] for i in range(0, 32, 4)),
    ]
    assert {totp(variant, 1111111109) for variant in variants} == {totp(RFC_SECRET, 1111111109)}

@pytest.mark.parametrize("bad", ["", "   ", "-", "not-base32!!", "GEZDGNBV1", "ABC", "A"])
def test_invalid_secret_raises_value_error(bad: str) -> None:
    with pytest.raises(ValueError):
        normalize_secret(bad)

def test_secret_must_be_text() -> None:
    with pytest.raises(ValueError):
        normalize_secret(b"GEZDGNBV")  # type: ignore[arg-type]

# ── argument validation ──────────────────────────────────────────────────────

@pytest.mark.parametrize("digits", [0, 1, 5, 9, 10])
def test_digits_outside_supported_range_raise(digits: int) -> None:
    assert MIN_DIGITS == 6
    with pytest.raises(ValueError):
        hotp(RFC_SECRET, 0, digits=digits)
    with pytest.raises(ValueError):
        totp(RFC_SECRET, 59, digits=digits)

@pytest.mark.parametrize("period", [0, -1, -30])
def test_non_positive_period_raises(period: int) -> None:
    with pytest.raises(ValueError):
        totp(RFC_SECRET, 59, period=period)
    with pytest.raises(ValueError):
        seconds_remaining(59, period=period)

def test_negative_counter_raises() -> None:
    with pytest.raises(ValueError):
        hotp(RFC_SECRET, -1)

# ── countdown ────────────────────────────────────────────────────────────────

def test_seconds_remaining_is_within_one_period() -> None:
    assert seconds_remaining(when=0, period=30) == 30
    assert seconds_remaining(when=29, period=30) == 1
    assert seconds_remaining(when=29.999, period=30) == 1
    assert seconds_remaining(when=30, period=30) == 30
    assert 1 <= seconds_remaining() <= 30

def test_seconds_remaining_decreases_within_a_step() -> None:
    values = [seconds_remaining(when=when) for when in (0, 10, 20, 29)]
    assert values == [30, 20, 10, 1]
    assert values == sorted(values, reverse=True)

def test_seconds_remaining_honours_a_custom_period() -> None:
    assert seconds_remaining(when=0, period=60) == 60
    assert seconds_remaining(when=59, period=60) == 1

# ── verification with drift ──────────────────────────────────────────────────

def test_verify_accepts_current_previous_and_next_step() -> None:
    when = 1234567890
    assert verify(RFC_SECRET_B32, totp(RFC_SECRET_B32, when), when)
    assert verify(RFC_SECRET_B32, totp(RFC_SECRET_B32, when - 30), when)
    assert verify(RFC_SECRET_B32, totp(RFC_SECRET_B32, when + 30), when)

def test_verify_rejects_two_steps_away_with_default_window() -> None:
    when = 1234567890
    assert not verify(RFC_SECRET_B32, totp(RFC_SECRET_B32, when - 60), when)
    assert not verify(RFC_SECRET_B32, totp(RFC_SECRET_B32, when + 60), when)
    # ... but a wider window accepts them, proving the rejection was the window.
    assert verify(RFC_SECRET_B32, totp(RFC_SECRET_B32, when - 60), when, window=2)
    assert verify(RFC_SECRET_B32, totp(RFC_SECRET_B32, when + 60), when, window=2)

def test_verify_rejects_a_wrong_code() -> None:
    when = 1234567890
    current = totp(RFC_SECRET_B32, when)
    wrong = ("0" if current[0] != "0" else "1") + current[1:]
    assert wrong != current
    assert not verify(RFC_SECRET_B32, wrong, when)

@pytest.mark.parametrize("bad", ["", "12345", "1234567", "abcdef", "12 456", "12345a", "１２３４５６"])
def test_verify_rejects_bad_input_without_raising(bad: str) -> None:
    assert not verify(RFC_SECRET_B32, bad, 1234567890)

def test_verify_rejects_non_string_code() -> None:
    assert not verify(RFC_SECRET_B32, None, 1234567890)  # type: ignore[arg-type]
    assert not verify(RFC_SECRET_B32, 123456, 1234567890)  # type: ignore[arg-type]

def test_verify_uses_the_requested_digit_count() -> None:
    when = 1234567890
    eight = totp(RFC_SECRET, when, digits=8)
    assert verify(RFC_SECRET, eight, when, digits=8)
    assert not verify(RFC_SECRET, eight, when)  # 8 chars never matches 6 digits

def test_verify_accepts_a_leading_zero_code() -> None:
    # Counter 36 is "003784"; the comparison must not go through int().
    when = 36 * 30
    assert hotp(RFC_SECRET, 36) == "003784"
    assert verify(RFC_SECRET, "003784", when)
    assert not verify(RFC_SECRET, "3784", when)

# ── provisioning URIs ────────────────────────────────────────────────────────

def test_provisioning_uri_round_trips_special_characters() -> None:
    uri = provisioning_uri(RFC_SECRET_B32, "alice@example.com", issuer="Acme Corp")
    assert uri.startswith("otpauth://totp/")
    assert "%40" in uri and "%20" in uri
    assert parse_provisioning_uri(uri) == {
        "secret": RFC_SECRET_B32,
        "account": "alice@example.com",
        "issuer": "Acme Corp",
        "digits": 6,
        "period": 30,
    }

@pytest.mark.parametrize("secret", [RFC_SECRET_B32, PADDED_SECRET_B32, PADDED_SECRET_B32.lower()])
def test_provisioning_uri_secret_survives_a_round_trip(secret: str) -> None:
    uri = provisioning_uri(secret, "me@example.com")
    parsed = parse_provisioning_uri(uri)
    assert "=" not in parsed["secret"]  # padding is not carried in the URI
    assert normalize_secret(parsed["secret"]) == normalize_secret(secret)
    assert totp(parsed["secret"], 1111111109) == totp(secret, 1111111109)

def test_provisioning_uri_carries_digits_and_period() -> None:
    uri = provisioning_uri(RFC_SECRET_B32, "alice@example.com", issuer="Acme", digits=8, period=60)
    parsed = parse_provisioning_uri(uri)
    assert (parsed["digits"], parsed["period"]) == (8, 60)
    assert totp(parsed["secret"], 59, digits=8, period=60) == totp(RFC_SECRET_B32, 59, digits=8, period=60)

def test_provisioning_uri_without_issuer_omits_it() -> None:
    uri = provisioning_uri(RFC_SECRET_B32, "alice@example.com", issuer="")
    assert "issuer=" not in uri
    parsed = parse_provisioning_uri(uri)
    assert parsed["issuer"] == ""
    assert parsed["account"] == "alice@example.com"

def test_parse_reads_issuer_from_the_label_when_the_parameter_is_missing() -> None:
    uri = f"otpauth://totp/Acme%20Corp:alice%40example.com?secret={RFC_SECRET_B32}"
    parsed = parse_provisioning_uri(uri)
    assert parsed["issuer"] == "Acme Corp"
    assert parsed["account"] == "alice@example.com"
    assert parsed["digits"] == 6 and parsed["period"] == 30

@pytest.mark.parametrize(
    "bad",
    [
        "",
        "   ",
        "https://example.com/totp?secret=GEZDGNBV",
        "otpauth://hotp/alice?secret=GEZDGNBV",
        "otpauth://totp/?secret=GEZDGNBV",
        "otpauth://totp/alice",
        "otpauth://totp/alice?secret=!!!!",
        "otpauth://totp/alice?secret=GEZDGNBV&digits=abc",
        "otpauth://totp/alice?secret=GEZDGNBV&digits=4",
        "otpauth://totp/alice?secret=GEZDGNBV&period=0",
    ],
)
def test_malformed_uri_raises_value_error(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_provisioning_uri(bad)

def test_provisioning_uri_requires_an_account() -> None:
    with pytest.raises(ValueError):
        provisioning_uri(RFC_SECRET_B32, "  ")
    with pytest.raises(ValueError):
        provisioning_uri("", "alice@example.com")

# ── store ────────────────────────────────────────────────────────────────────

def test_store_uses_settings_output_dir_by_default(store_file) -> None:
    store = TotpStore()
    assert store.path == store_file
    assert store.list() == []
    assert not store_file.exists()  # reading must not create the file


def test_store_add_get_list_remove_round_trip(store_file) -> None:
    store = TotpStore()
    account = store.add("github", RFC_SECRET_B32, issuer="GitHub")
    assert account.name == "github"
    assert account.issuer == "GitHub"
    assert account.created_at
    assert normalize_secret(account.secret) == RFC_SECRET

    fetched = store.get("github")
    assert fetched is not None
    assert fetched.secret == account.secret

    assert [entry["name"] for entry in store.list()] == ["github"]
    assert store.remove("github") is True
    assert store.get("github") is None
    assert store.list() == []
    assert store.remove("github") is False


def test_store_persists_across_instances(store_file) -> None:
    TotpStore().add("mail", RFC_SECRET_B32, issuer="Acme")
    reopened = TotpStore(store_file)
    fetched = reopened.get("mail")
    assert fetched is not None
    assert normalize_secret(fetched.secret) == RFC_SECRET
    assert fetched.issuer == "Acme"


def test_store_file_is_mode_0600(store_file) -> None:
    store = TotpStore()
    store.add("bank", RFC_SECRET_B32)
    assert STORE_FILE_MODE == 0o600
    assert stat.S_IMODE(store_file.stat().st_mode) == 0o600


def test_store_rejects_duplicate_names(store_file) -> None:
    store = TotpStore()
    store.add("bank", RFC_SECRET_B32)
    with pytest.raises(ValueError):
        store.add("bank", RFC_SECRET_B32)
    assert len(store.list()) == 1


def test_store_rejects_invalid_secret_without_touching_the_file(store_file) -> None:
    store = TotpStore()
    with pytest.raises(ValueError):
        store.add("broken", "not-base32!!")
    assert not store_file.exists()

    store.add("good", RFC_SECRET_B32)
    before = store_file.read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        store.add("broken", "")
    with pytest.raises(ValueError):
        store.add("   ", RFC_SECRET_B32)
    assert store_file.read_text(encoding="utf-8") == before


def test_store_code_matches_module_level_totp(store_file) -> None:
    store = TotpStore()
    store.add("bank", RFC_SECRET_B32)
    for when in (59, 1111111109, 1234567890, 20000000000):
        assert store.code("bank", when) == totp(RFC_SECRET_B32, when)
    assert store.code("bank") == totp(RFC_SECRET_B32)


def test_store_code_for_unknown_account_raises(store_file) -> None:
    store = TotpStore()
    with pytest.raises(ValueError):
        store.code("nobody")
    with pytest.raises(ValueError):
        store.uri("nobody")


def test_store_uri_round_trips(store_file) -> None:
    store = TotpStore()
    store.add("mail", RFC_SECRET_B32, issuer="Acme Corp")
    parsed = parse_provisioning_uri(store.uri("mail"))
    assert parsed["account"] == "mail"
    assert parsed["issuer"] == "Acme Corp"
    assert parsed["digits"] == settings.totp_digits
    assert parsed["period"] == settings.totp_period_s
    assert totp(parsed["secret"], 1234567890) == store.code("mail", 1234567890)


def test_store_list_never_exposes_a_secret(store_file) -> None:
    store = TotpStore()
    account = store.add("bank", RFC_SECRET_B32, issuer="Bank")
    listed = store.list()
    assert [entry["name"] for entry in listed] == ["bank"]
    assert listed[0]["issuer"] == "Bank"
    assert listed[0]["created_at"] == account.created_at
    assert account.secret not in json.dumps(listed)
    assert RFC_SECRET_B32 not in json.dumps(listed)
    assert listed[0]["secret"] != account.secret

    redacted = redact(account)
    assert redacted["name"] == "bank" and redacted["issuer"] == "Bank"
    assert account.secret not in json.dumps(redacted)


def test_repr_never_leaks_the_secret(store_file) -> None:
    store = TotpStore()
    account = store.add("bank", RFC_SECRET_B32)
    assert account.secret not in repr(account)
    assert RFC_SECRET_B32 not in repr(account)
    assert RFC_SECRET_B32 not in repr(store)
    assert "bank" in repr(account)
    assert "totp.json" in repr(store)


def test_store_survives_a_corrupt_file(store_file) -> None:
    store_file.parent.mkdir(parents=True, exist_ok=True)
    store_file.write_text("{not json", encoding="utf-8")
    store = TotpStore(store_file)
    assert store.list() == []
    store.add("bank", RFC_SECRET_B32)
    assert [entry["name"] for entry in store.list()] == ["bank"]


def test_store_writes_a_versioned_document(store_file) -> None:
    TotpStore().add("bank", RFC_SECRET_B32)
    payload = json.loads(store_file.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert [item["name"] for item in payload["accounts"]] == ["bank"]
