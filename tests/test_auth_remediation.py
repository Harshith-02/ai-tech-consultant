import os
import sys
import time
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "task1-knowledge-brain"))

from fastapi.testclient import TestClient
from api.index import (
    app,
    create_session_jwt,
    decode_and_verify_jwt,
    get_jwt_secret,
    get_api_secret_key
)
from retrieval.vector_store import (
    vector_store,
    hash_password,
    verify_password
)
from ingestion.crawler import is_safe_external_url, safe_http_get

client = TestClient(app)

# ==============================================================================
# 1. PASSWORD HASHING & CREDENTIAL VERIFICATION TESTS
# ==============================================================================

def test_bcrypt_hash_and_verify():
    """Verify standard Bcrypt password hashing generates valid salted hashes and verifies cleanly."""
    pw = "SuperSecurePassword2026!"
    hashed = hash_password(pw)
    assert hashed.startswith("$2b$") or hashed.startswith("$2a$")
    assert verify_password(pw, hashed) is True
    assert verify_password("WrongPassword123!", hashed) is False
    assert verify_password("", hashed) is False
    assert verify_password(pw, "") is False

def test_verify_password_rejects_legacy_unmigrated_hashes():
    """Legacy plaintext or mock hashes must be rejected immediately."""
    assert verify_password("consultant2026", "demo_hash_consultant") is False
    assert verify_password("admin", "plain_admin") is False
    assert verify_password("secret", "md5:1234567890abcdef") is False

def test_login_rejects_empty_password():
    """Login must reject empty or missing password with HTTP 401."""
    res_empty = client.post("/api/auth/login", json={
        "username": "consultant@apex.io",
        "password": ""
    })
    assert res_empty.status_code == 401
    assert "empty" in res_empty.json()["detail"].lower()

    res_none = client.post("/api/auth/login", json={
        "username": "consultant@apex.io"
    })
    assert res_none.status_code == 401
    assert "empty" in res_none.json()["detail"].lower()

def test_login_rejects_incorrect_password():
    """Login must reject incorrect passwords with HTTP 401."""
    res = client.post("/api/auth/login", json={
        "username": "consultant@apex.io",
        "password": "definitely_wrong_password_999"
    })
    assert res.status_code == 401
    assert "invalid" in res.json()["detail"].lower()

def test_login_rejects_unknown_user():
    """Login must reject unknown email addresses even with a non-empty password."""
    res = client.post("/api/auth/login", json={
        "username": "unknown_attacker@domain.com",
        "password": "SomeValidLookingPassword123"
    })
    assert res.status_code == 401
    assert "invalid" in res.json()["detail"].lower()

def test_login_rejects_legacy_hash_and_provides_migration_message():
    """Users with legacy unmigrated hashes cannot authenticate and receive migration guidance."""
    with patch.object(vector_store, "verify_user_credentials", return_value=(False, {"id": "u1"}, "legacy_hash")):
        res = client.post("/api/auth/login", json={
            "username": "legacy_user@apex.io",
            "password": "anypassword"
        })
        assert res.status_code == 401
        assert "migration" in res.json()["detail"].lower()

def test_login_succeeds_with_valid_credentials():
    """Valid credentials verified against bcrypt hash return authenticated JWT."""
    res = client.post("/api/auth/login", json={
        "username": "consultant@apex.io",
        "password": "consultant2026"
    })
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "authenticated"
    assert "token" in data
    assert data["token_type"] == "Bearer"
    assert data["user"]["email"] == "consultant@apex.io"

    # Verify returned token can authenticate a protected request
    auth_headers = {"Authorization": f"Bearer {data['token']}"}
    me_res = client.get("/api/auth/me", headers=auth_headers)
    assert me_res.status_code == 200
    assert me_res.json()["authenticated"] is True

# ==============================================================================
# 2. SECRET MANAGEMENT & PRODUCTION FAIL-CLOSED TESTS
# ==============================================================================

def test_production_fails_closed_when_jwt_secret_is_missing():
    """In production mode, missing JWT_SECRET must raise RuntimeError."""
    with patch.dict(os.environ, {"ENVIRONMENT": "production", "JWT_SECRET": "", "API_SECRET_KEY": ""}):
        with pytest.raises(RuntimeError) as exc:
            get_jwt_secret()
        assert "JWT_SECRET must be explicitly configured" in str(exc.value)

def test_production_fails_closed_on_insecure_default_jwt_secret():
    """In production mode, known insecure fallback secret must raise RuntimeError."""
    with patch.dict(os.environ, {"ENVIRONMENT": "production", "JWT_SECRET": "lead-consultant-sec-token-2026"}):
        with pytest.raises(RuntimeError) as exc:
            get_jwt_secret()
        assert "JWT_SECRET must be explicitly configured" in str(exc.value)

def test_local_development_uses_ephemeral_key_without_hardcoded_defaults():
    """In local development without explicit secret, an ephemeral cryptographic key is generated."""
    with patch.dict(os.environ, {"ENVIRONMENT": "development", "JWT_SECRET": "", "API_SECRET_KEY": ""}, clear=False):
        secret = get_jwt_secret()
        assert secret is not None
        assert len(secret) >= 32
        assert secret not in ("lead-consultant-sec-token-2026", "secret", "change-me")

def test_backdoor_prefix_tokens_are_strictly_rejected():
    """Tokens starting with legacy prefixes like lead_consultant_ must be rejected with HTTP 403."""
    bad_headers = {"Authorization": "Bearer lead_consultant_bypass_token_12345"}
    res = client.get("/api/kb/sitemap/sources", headers=bad_headers)
    assert res.status_code == 403
    assert "forbidden" in res.json()["detail"].lower()

def test_expired_session_token_rejected():
    """Expired session tokens must be rejected with HTTP 401."""
    expired_session = create_session_jwt(
        user_id="consultant_lead_01",
        account_id="acc_default",
        email="consultant@apex.io",
        expires_in_seconds=-60
    )
    headers = {"Authorization": f"Bearer {expired_session['token']}"}
    res = client.get("/api/kb/sitemap/sources", headers=headers)
    assert res.status_code == 401
    assert "expired" in res.json()["detail"].lower()

def test_tampered_jwt_signature_rejected():
    """Tampering with token signature or payload must return HTTP 403."""
    valid_session = create_session_jwt(
        user_id="consultant_lead_01",
        account_id="acc_default",
        email="consultant@apex.io"
    )
    parts = valid_session["token"].split(".")
    tampered_sig = parts[2][:-4] + "AAAA"
    tampered_token = f"{parts[0]}.{parts[1]}.{tampered_sig}"

    res = client.get("/api/kb/sitemap/sources", headers={"Authorization": f"Bearer {tampered_token}"})
    assert res.status_code == 403
    assert "forbidden" in res.json()["detail"].lower()

# ==============================================================================
# 3. SENSITIVE ROUTE AUTHORIZATION ENFORCEMENT
# ==============================================================================

def test_sensitive_routes_require_authentication():
    """Management, ingestion, and operational endpoints must return HTTP 401 for anonymous calls."""
    unauth_client = TestClient(app)

    # 1. Sitemap sources list & create
    assert unauth_client.get("/api/kb/sitemap/sources").status_code == 401
    assert unauth_client.post("/api/kb/sitemap/sources", json={"name": "test", "root_sitemap_url": "https://example.com/sitemap.xml"}).status_code == 401

    # 2. Ingestion inspect & run
    assert unauth_client.post("/api/kb/ingestion/inspect", json={"sitemap_url": "https://example.com/sitemap.xml"}).status_code == 401
    assert unauth_client.post("/api/kb/ingestion/run", json={"sitemap_urls": ["https://example.com/sitemap.xml"]}).status_code == 401

    # 3. Escalations resolve
    assert unauth_client.post("/api/kb/escalations/resolve", json={"escalation_id": "ESC-1", "resolution_notes": "fixed"}).status_code == 401

    # 4. Inbox folders, email list, and processing
    assert unauth_client.get("/api/inbox/folders").status_code == 401
    assert unauth_client.get("/api/inbox/emails").status_code == 401
    assert unauth_client.post("/api/inbox/process-email", json={"emailId": "EM-1"}).status_code == 401
    assert unauth_client.post("/api/inbox/test-email", json={"subject": "test", "body": "test"}).status_code == 401

    # 5. Task 3 Scope endpoints: Transcripts, analysis & approval
    assert unauth_client.get("/api/scope/transcripts").status_code == 401
    assert unauth_client.post("/api/scope/analyze-meeting", json={"project_id": "APEX-01"}).status_code == 401
    assert unauth_client.post("/api/scope/analyze-followup", json={"project_id": "APEX-01"}).status_code == 401
    assert unauth_client.post("/api/scope/approve-proposal", json={"proposal_id": "PROP-APEX-01"}).status_code == 401

def test_scope_routes_succeed_with_valid_auth():
    """Authenticated requests to /api/scope/* endpoints must succeed."""
    session = create_session_jwt(user_id="consultant_lead_01", account_id="acc_default")
    auth_headers = {"Authorization": f"Bearer {session['token']}"}

    # Transcripts
    res_transcripts = client.get("/api/scope/transcripts", headers=auth_headers)
    assert res_transcripts.status_code == 200
    assert "transcripts" in res_transcripts.json()

    # Proposal approval
    res_approve = client.post("/api/scope/approve-proposal", json={"proposal_id": "PROP-APEX-TEST-01", "reviewer_name": "Test Reviewer"}, headers=auth_headers)
    assert res_approve.status_code == 200
    assert res_approve.json()["is_client_ready"] is True

def test_cors_allowlist_configuration():
    """Verify CORS origins and credentials interactions."""
    from api.index import get_allowed_origins
    with patch.dict(os.environ, {"ENVIRONMENT": "production", "ALLOWED_ORIGINS": "https://client.apex.io,https://app.apex.io"}):
        origins = get_allowed_origins()
        assert origins == ["https://client.apex.io", "https://app.apex.io"]
        assert "*" not in origins

# ==============================================================================
# 4. SSRF DEFENSE & REDIRECT CHAIN HARDENING
# ==============================================================================

def test_ssrf_rejects_loopback_private_and_metadata_targets():
    """Verify SSRF defense rejects loopback, RFC 1918 private, link-local, and cloud metadata targets."""
    # IPv4 loopback & private
    assert is_safe_external_url("http://127.0.0.1:8000") is False
    assert is_safe_external_url("http://localhost:8000") is False
    assert is_safe_external_url("http://10.0.0.5/sitemap.xml") is False
    assert is_safe_external_url("http://192.168.1.1/sitemap.xml") is False
    assert is_safe_external_url("http://172.16.0.1/sitemap.xml") is False

    # IPv6 loopback & link-local
    assert is_safe_external_url("http://[::1]/") is False
    assert is_safe_external_url("http://[fe80::1]/") is False

    # Cloud metadata endpoints
    assert is_safe_external_url("http://169.254.169.254/latest/meta-data/") is False
    assert is_safe_external_url("http://metadata.google.internal/computeMetadata/v1/") is False
    assert is_safe_external_url("http://100.100.100.200/latest/meta-data/") is False
    assert is_safe_external_url("http://[fd00:ec2::254]/") is False

    # Carrier-grade NAT (RFC 6598)
    assert is_safe_external_url("http://100.64.0.1/sitemap.xml") is False

    # Non-standard dangerous ports
    assert is_safe_external_url("https://example.com:22/sitemap.xml") is False
    assert is_safe_external_url("https://example.com:3306/sitemap.xml") is False

    # Valid public HTTPS targets
    assert is_safe_external_url("https://support.brilliantdirectories.com/support/sitemap.xml") is True
    assert is_safe_external_url("https://www.google.com/sitemap.xml") is True

def test_sitemap_endpoints_reject_ssrf_payloads():
    """API endpoints must return HTTP 400 when submitted unsafe SSRF URLs."""
    session = create_session_jwt(user_id="consultant_lead_01", account_id="acc_default")
    auth_headers = {"Authorization": f"Bearer {session['token']}"}

    # /api/kb/sitemap/sources
    res1 = client.post("/api/kb/sitemap/sources", json={
        "name": "Malicious Metadata Source",
        "root_sitemap_url": "http://169.254.169.254/latest/meta-data"
    }, headers=auth_headers)
    assert res1.status_code == 400
    assert "ssrf" in res1.json()["detail"].lower()

    # /api/kb/ingestion/inspect
    res2 = client.post("/api/kb/ingestion/inspect", json={
        "sitemap_url": "http://127.0.0.1:8000/internal-data"
    }, headers=auth_headers)
    assert res2.status_code == 400
    assert "ssrf" in res2.json()["detail"].lower()

    # /api/kb/ingestion/run
    res3 = client.post("/api/kb/ingestion/run", json={
        "sitemap_urls": ["http://[::1]/internal-sitemap.xml"]
    }, headers=auth_headers)
    assert res3.status_code == 400
    assert "ssrf" in res3.json()["detail"].lower()

def test_safe_http_get_blocks_ssrf_redirect_chain():
    """safe_http_get must intercept HTTP redirects pointing to loopback or metadata endpoints."""
    mock_redirect = MagicMock()
    mock_redirect.status_code = 302
    mock_redirect.headers = {"location": "http://169.254.169.254/latest/meta-data/"}

    with patch("httpx.Client.get", return_value=mock_redirect):
        with pytest.raises(ValueError) as exc:
            safe_http_get("https://support.brilliantdirectories.com/support/sitemap.xml")
        assert "Blocked unsafe SSRF destination" in str(exc.value)
