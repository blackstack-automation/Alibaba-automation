from flask import current_app
from cryptography.fernet import Fernet, InvalidToken
from alibabacloud_dm20151123.client import Client as DmClient
from alibabacloud_dm20151123 import models as dm_models
from alibabacloud_tea_openapi import models as open_api_models
from Tea.exceptions import TeaException


def _fernet() -> Fernet:
    key = current_app.config["ENCRYPTION_KEY"]
    if not key:
        raise RuntimeError("ENCRYPTION_KEY is not configured")
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_secret(plain_value: str) -> str:
    return _fernet().encrypt(plain_value.encode()).decode()


def decrypt_secret(encrypted_value: str) -> str:
    try:
        return _fernet().decrypt(encrypted_value.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Could not decrypt stored AccessKey secret") from exc


def get_client_for_account(account) -> DmClient:
    """account is an Account model instance."""
    config = open_api_models.Config(
        access_key_id=account.access_key_id,
        access_key_secret=decrypt_secret(account.access_key_secret_encrypted),
        endpoint=account.region_endpoint,
    )
    return DmClient(config)


def test_connection(access_key_id: str, access_key_secret: str, region_endpoint: str) -> dict:
    """
    Side-effect-free credential check via DescAccountSummary (no required
    params). Returns {"ok": True, "daily_quota": ..., "month_quota": ...}
    on success, or {"ok": False, "error": "..."} on failure.
    """
    config = open_api_models.Config(
        access_key_id=access_key_id,
        access_key_secret=access_key_secret,
        endpoint=region_endpoint,
    )
    client = DmClient(config)
    try:
        response = client.desc_account_summary(dm_models.DescAccountSummaryRequest())
        body = response.body
        return {
            "ok": True,
            "daily_quota": body.daily_quota,
            "month_quota": body.month_quota,
        }
    except TeaException as exc:
        # Network failures arrive as an UnretryableException with no code.
        if exc.code:
            return {"ok": False, "error": f"{exc.code}: {exc.message}"}
        return {"ok": False, "error": str(exc) or type(exc).__name__}
    except Exception as exc:  # network errors, etc.
        return {"ok": False, "error": str(exc)}
