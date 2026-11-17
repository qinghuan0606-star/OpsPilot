"""Secret masking for ops content: tokens, keys, internal IPs, env lines."""

from app.core.constants import PII_MASK
from app.core.security import mask_env_lines, mask_pii, redact_mapping


def test_mask_phone_id_bank_and_internal_ip() -> None:
    text = (
        "联系 13812345678 身份证 11010119900307123X 卡号 6222021234567890 "
        "主机 10.20.30.40 sshd 监听 127.0.0.1"
    )
    masked = mask_pii(text)
    assert "13812345678" not in masked
    assert f"138{PII_MASK}5678" in masked
    assert "11010119900307123X" not in masked
    assert "6222021234567890" not in masked
    assert "10.20.30.40" not in masked
    # Loopback stays readable: it is not internal topology information.
    assert "127.0.0.1" in masked


def test_bearer_token_and_private_key_are_masked() -> None:
    pem = "-----BEGIN RSA PRIVATE KEY-----\n" "MIIEowIBAAKCAQEA\n" "-----END RSA PRIVATE KEY-----"
    text = f"Authorization: Bearer abcdefghijklmnopqrstuvwxyz012345\n{pem}"
    masked = mask_pii(text)
    assert "abcdefghijklmnopqrstuvwxyz012345" not in masked
    assert "MIIEowIBAAKCAQEA" not in masked
    assert "PRIVATE KEY" not in masked


def test_mask_env_lines_hides_credentials_only() -> None:
    env = "DB_HOST=10.1.2.3\nDB_PASSWORD=s3cr3t\nAPI_TOKEN=abcd1234\nPATH=/usr/bin"
    masked = mask_env_lines(env)
    assert "s3cr3t" not in masked
    assert "abcd1234" not in masked
    assert "PATH=/usr/bin" in masked


def test_redact_mapping_masks_secrets_and_nested_strings() -> None:
    payload = {
        "api_key": "sk-live-secret",
        "note": "电话 13900001111",
        "nested": {"password": "hunter2", "host": "10.20.30.40"},
        "count": 3,
    }
    redacted = redact_mapping(payload)
    assert redacted["api_key"] == PII_MASK
    assert "13900001111" not in str(redacted["note"])
    nested = redacted["nested"]
    assert isinstance(nested, dict)
    assert nested["password"] == PII_MASK
    assert "10.20.30.40" not in str(nested["host"])
    assert redacted["count"] == 3
