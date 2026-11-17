"""Log redaction and secret masking for ops content.

Ops transcripts carry secrets: sudo passwords, API tokens in systemd
Environment= lines, private keys and internal host IP addresses. Mask those before they reach logs, audit rows or citations.
"""

from __future__ import annotations

import re

from app.core.constants import PII_MASK

_SECRET_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "access_token",
        "refresh_token",
        "password",
        "passwd",
        "cookie",
        "secret",
        "private_key",
        "token",
    }
)

_PHONE = re.compile(r"(?<!\d)(1[3-9]\d)\d{4}(\d{4})(?!\d)")
_ID_CARD = re.compile(r"\b(\d{6})\d{8,10}(\d{2}[\dXx])\b")
_BANK_CARD = re.compile(r"\b(\d{4})\d{8,11}(\d{4})\b")
# Bearer / api tokens and PEM private keys are the highest-risk leak.
_BEARER = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{12,}")
_PEM_KEY = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S
)
# Internal IPv4 addresses are masked by default; loopback stays readable.
_IPV4 = re.compile(r"\b(?!127\.0\.0\.1)((?:\d{1,3}\.){3}\d{1,3})\b")
_ENV_SECRET = re.compile(r"(?im)^(\s*)([A-Z0-9_]*(?:PASSWORD|PASSWD|SECRET|TOKEN|KEY))=(.+)$")


def redact_mapping(payload: dict[str, object]) -> dict[str, object]:
    redacted: dict[str, object] = {}
    for key, value in payload.items():
        if key.lower() in _SECRET_KEYS:
            redacted[key] = PII_MASK
        elif isinstance(value, str):
            redacted[key] = mask_pii(value)
        elif isinstance(value, dict):
            redacted[key] = redact_mapping(value)  # type: ignore[arg-type]
        else:
            redacted[key] = value
    return redacted


def mask_pii(text: str) -> str:
    """Mask phone/id/bank/bearer/private-key/internal-IP content in free text."""
    text = _PHONE.sub(rf"\1{PII_MASK}\2", text)
    text = _ID_CARD.sub(rf"\1{PII_MASK}\2", text)
    text = _BANK_CARD.sub(rf"\1{PII_MASK}\2", text)
    text = _BEARER.sub(rf"\1{PII_MASK}", text)
    text = _PEM_KEY.sub(PII_MASK, text)
    text = _IPV4.sub(PII_MASK, text)
    return text


def mask_env_lines(text: str) -> str:
    """Mask `FOO_PASSWORD=...` style lines, common in unit files and logs."""
    return _ENV_SECRET.sub(lambda m: f"{m.group(1)}{m.group(2)}={PII_MASK}", text)
