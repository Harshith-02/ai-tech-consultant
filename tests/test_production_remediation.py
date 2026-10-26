import os
import sys
import time
import json
import uuid
import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from fastapi.testclient import TestClient

# Ensure root is in path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ["TESTING"] = "1"
os.environ["CRON_SECRET"] = "production-cron-secret-key-xyz987"
os.environ["GMAIL_ENCRYPTION_KEY"] = "prod-remediation-aes-key-32b-!"

from api.index import (
    app,
    create_session_jwt,
    decode_and_verify_jwt,
    check_rate_limit,
    RATE_LIMIT_BUCKETS
)
from retrieval.vector_store import vector_store

client = TestClient(app)

def test_storage_status_diagnostics_and_migrations():
    """Phase 1: Persistent Production Database & Migration Integrity."""
    res = client.get("/api/kb/storage-status")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    data = res.json()
    assert "status" in data
    assert "engine" in data
    assert "is_durable" in data
    assert "migrations_count" in data
    assert data["migrations_count"] >= 3

    # Verify migrations list includes baseline, multi-tenant, and auth
    mig_versions = [m["version"] for m in data["migrations"]]
    assert "001_baseline_schema" in mig_versions
    assert "002_multi_tenant_isolation" in mig_versions
    assert "003_auth_and_sessions" in mig_versions

def test_jwt_generation_verification_and_tampering():
    """Phase 3: Cryptographic JWT Session Token Security."""
    user_id = "user_test_42"
    account_id = "acc_acme_corp"
    email = "admin@acme.com"

    # 1. Create valid session token
    session = create_session_jwt(
        user_id=user_id,
        account_id=account_id,
        email=email,
        role="Administrator",
        expires_in_seconds=3600
    )
    token = session["token"]
    assert token.count(".") == 2, "JWT must have three dot-separated segments"

    # 2. Decode and verify valid token
    payload = decode_and_verify_jwt(token)
    assert payload["sub"] == user_id
    assert payload["acc"] == account_id
    assert payload["email"] == email
    assert payload["role"] == "Administrator"
    assert "jti" in payload
    assert payload["exp"] > int(time.time())

    # 3. Verify signature tampering rejection
    parts = token.split(".")
    tampered_sig = parts[2][:-4] + "AAAA"
    tampered_token = f"{parts[0]}.{parts[1]}.{tampered_sig}"
    with pytest.raises(ValueError, match="Invalid token signature"):
        decode_and_verify_jwt(tampered_token)

    # 4. Verify payload tampering rejection
    tampered_payload_token = f"{parts[0]}.eyJhZG1pbiI6dHJ1ZX0.{parts[2]}"
    with pytest.raises(ValueError, match="Invalid token signature"):
        decode_and_verify_jwt(tampered_payload_token)

    # 5. Verify expired token rejection
    expired_session = create_session_jwt(
        user_id=user_id,
        account_id=account_id,
        email=email,
        expires_in_seconds=-10  # Expired 10 seconds ago
    )
    with pytest.raises(ValueError, match="Session token has expired"):
        decode_and_verify_jwt(expired_session["token"])

def test_auth_login_logout_and_revocation():
    """Phase 3: Full login, logout, and token revocation lifecycle."""
    # 1. Login with credentials
    login_res = client.post("/api/auth/login", json={
        "username": "consultant@apex.io",
        "password": "consultant2026"
    })
    assert login_res.status_code == 200, f"Login failed: {login_res.text}"
    login_data = login_res.json()
    token = login_data["token"]
    assert token is not None
    assert login_data["token_type"] == "Bearer"
    assert "jti" in login_data

    # 2. Authenticated access with new JWT
    auth_headers = {"Authorization": f"Bearer {token}"}
    me_res = client.get("/api/auth/me", headers=auth_headers)
    assert me_res.status_code == 200
    assert me_res.json()["authenticated"] is True
    assert me_res.json()["user"]["email"] == "consultant@apex.io"

    # 3. Access protected sitemaps endpoint with token
    sitemaps_res = client.get("/api/kb/sitemap/sources", headers=auth_headers)
    assert sitemaps_res.status_code == 200

    # 4. Logout / Revoke token
    logout_res = client.post("/api/auth/logout", headers=auth_headers)
    assert logout_res.status_code == 200
    assert logout_res.json()["status"] == "logged_out"

    # 5. Subsequent access with revoked token MUST return 401
    post_logout_res = client.get("/api/kb/sitemap/sources", headers=auth_headers)
    assert post_logout_res.status_code == 401, "Revoked token must be rejected with HTTP 401"
    assert "revoked" in post_logout_res.json()["detail"].lower()

def test_multi_account_isolation_and_idor_protection():
    """Phase 2: Secure Multi-Account Architecture & IDOR Isolation."""
    # Generate tokens for two distinct tenants
    tenant_a_session = create_session_jwt(
        user_id="user_a",
        account_id="acc_tenant_alpha",
        email="lead@alpha.com"
    )
    headers_a = {"Authorization": f"Bearer {tenant_a_session['token']}"}

    tenant_b_session = create_session_jwt(
        user_id="user_b",
        account_id="acc_tenant_beta",
        email="lead@beta.com"
    )
    headers_b = {"Authorization": f"Bearer {tenant_b_session['token']}"}

    test_url = f"https://support.brilliantdirectories.com/sitemap-{uuid.uuid4().hex[:8]}.xml"

    # 1. Tenant A creates a sitemap source
    src_res_a = client.post("/api/kb/sitemap/sources", headers=headers_a, json={
        "name": "Alpha Corporation Knowledge Base",
        "root_sitemap_url": test_url,
        "refresh_interval_days": 15,
        "missing_threshold": 20
    })
    assert src_res_a.status_code == 200
    source_a_id = src_res_a.json()["source"]["id"]

    # 2. Tenant B lists sources — must NOT see Tenant A's source
    list_b = client.get("/api/kb/sitemap/sources", headers=headers_b)
    assert list_b.status_code == 200
    sources_b = list_b.json()["sources"]
    assert not any(s["id"] == source_a_id for s in sources_b), "Tenant B must not see Tenant A's sources"

    # 3. IDOR Attack: Tenant B tries to delete Tenant A's source — MUST receive 404
    idor_delete = client.delete(f"/api/kb/sitemap/sources/{source_a_id}", headers=headers_b)
    assert idor_delete.status_code == 404, "Tenant B must not be able to delete Tenant A's source (IDOR protection)"

    # 4. IDOR Attack: Tenant B tries to modify Tenant A's schedule — MUST receive 404
    idor_update = client.post(f"/api/kb/sitemap/sources/{source_a_id}/schedule", headers=headers_b, json={
        "refresh_interval_days": 1
    })
    assert idor_update.status_code == 404, "Tenant B must not be able to modify Tenant A's schedule"

    # 5. Shared Sitemap URL Handling: Tenant B can add the same root URL independently
    src_res_b = client.post("/api/kb/sitemap/sources", headers=headers_b, json={
        "name": "Beta Corporation Knowledge Base",
        "root_sitemap_url": test_url,
        "refresh_interval_days": 7
    })
    assert src_res_b.status_code == 200, "Shared sitemap URLs should be supported across different accounts"
    source_b_id = src_res_b.json()["source"]["id"]
    assert source_b_id != source_a_id, "Each tenant must receive their own isolated source ID"

    # 6. Tenant A can delete their source without affecting Tenant B
    del_a = client.delete(f"/api/kb/sitemap/sources/{source_a_id}", headers=headers_a)
    assert del_a.status_code == 200

    # Tenant B's source remains active
    list_b_after = client.get("/api/kb/sitemap/sources", headers=headers_b)
    assert any(s["id"] == source_b_id for s in list_b_after.json()["sources"]), "Tenant B's source must remain intact"

    # Clean up Tenant B's source
    client.delete(f"/api/kb/sitemap/sources/{source_b_id}", headers=headers_b)

def test_cron_secret_scheduler_authorization(monkeypatch):
    """Phase 4: Reliable Sitemap Scheduler & CRON_SECRET Protection."""
    from unittest.mock import patch
    cron_secret = os.environ["CRON_SECRET"]

    with patch("ingestion.crawler.PoliteResumableCrawler.crawl", return_value={"status": "completed", "crawled_this_run": 0, "failed_this_run": 0}):
        # 1. Trigger with valid CRON_SECRET in Authorization header
        cron_res_header = client.post(
            "/api/kb/sitemap/refresh-due",
            headers={"Authorization": f"Bearer {cron_secret}"}
        )
        assert cron_res_header.status_code == 200, f"Expected 200, got: {cron_res_header.text}"
        assert "refreshed_count" in cron_res_header.json()

        # 2. Trigger with valid X-Cron-Secret header
        cron_res_x = client.post(
            "/api/kb/sitemap/refresh-due",
            headers={"X-Cron-Secret": cron_secret}
        )
        assert cron_res_x.status_code == 200

    # 3. Trigger without CRON_SECRET and without user credentials MUST be rejected with 401
    cron_res_unauth = client.post("/api/kb/sitemap/refresh-due")
    assert cron_res_unauth.status_code == 401, "Unauthenticated cron trigger must be rejected with HTTP 401"

    # 4. Trigger with invalid CRON_SECRET MUST be rejected
    cron_res_invalid = client.post(
        "/api/kb/sitemap/refresh-due",
        headers={"Authorization": "Bearer completely-wrong-cron-secret"}
    )
    assert cron_res_invalid.status_code in (401, 403), "Invalid cron secret must be rejected"

def test_rate_limiting_enforcement():
    """Phase 3: Rate Limiting on Sensitive Endpoints."""
    import sqlite3
    from app.config import settings
    RATE_LIMIT_BUCKETS.clear()
    with sqlite3.connect(settings.DB_PATH) as conn:
        conn.execute("DELETE FROM rate_limits WHERE key LIKE 'login_%'")
        conn.commit()

    # Simulate 15 rapid login attempts
    for i in range(15):
        res = client.post("/api/auth/login", json={
            "username": f"user_{i}@example.com",
            "password": "wrongpassword"
        })
        assert res.status_code == 401

    # The 16th attempt from same IP must hit HTTP 429
    res_limited = client.post("/api/auth/login", json={
        "username": "user_16@example.com",
        "password": "wrongpassword"
    })
    assert res_limited.status_code == 429, "16th login attempt must trigger HTTP 429 Rate Limit Exceeded"
    assert "rate limit" in res_limited.json()["detail"].lower()
    RATE_LIMIT_BUCKETS.clear()
    with sqlite3.connect(settings.DB_PATH) as conn:
        conn.execute("DELETE FROM rate_limits WHERE key LIKE 'login_%'")
        conn.commit()

def test_legacy_token_backward_compatibility(monkeypatch):
    """Hardcoded backdoor token must be rejected; configured API_SECRET_KEY must succeed."""
    # 1. Hardcoded insecure token must be rejected
    insecure_legacy_key = "lead-consultant-sec-token-2026"
    res = client.get("/api/kb/sitemap/sources", headers={"Authorization": f"Bearer {insecure_legacy_key}"})
    assert res.status_code == 403, "Hardcoded backdoor token must be rejected with HTTP 403"

    # 2. Configured API_SECRET_KEY must be accepted
    custom_key = "valid-custom-api-secret-key-32chars"
    monkeypatch.setenv("API_SECRET_KEY", custom_key)
    res_valid = client.get("/api/kb/sitemap/sources", headers={"Authorization": f"Bearer {custom_key}"})
    assert res_valid.status_code == 200
    assert "sources" in res_valid.json()
