import os
import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "task1-knowledge-brain"))

from api.index import app, create_session_jwt

client = TestClient(app)

def test_unauthenticated_sitemap_inspection_returns_401():
    """Requirement 4 & 7: Protected inspection endpoint must reject unauthenticated requests with HTTP 401."""
    res = client.post("/api/kb/ingestion/inspect", json={
        "sitemap_url": "https://help.elegantthemes.com/sitemap.xml"
    })
    assert res.status_code == 401, f"Expected 401, got {res.status_code}: {res.text}"
    detail = res.json().get("detail", "")
    assert "Authentication required" in detail
    assert "bearer token or API key" in detail

def test_invalid_and_tampered_token_sitemap_inspection():
    """Invalid, tampered, or expired tokens must fail closed."""
    # 1. Random garbage token
    bad_res = client.post(
        "/api/kb/ingestion/inspect",
        json={"sitemap_url": "https://help.elegantthemes.com/sitemap.xml"},
        headers={"Authorization": "Bearer not-a-valid-jwt-token"}
    )
    assert bad_res.status_code in (401, 403)

    # 2. Expired JWT token
    expired = create_session_jwt(
        user_id="consultant_lead_01",
        account_id="acc_default",
        email="consultant@apex.io",
        expires_in_seconds=-100
    )
    exp_res = client.post(
        "/api/kb/ingestion/inspect",
        json={"sitemap_url": "https://help.elegantthemes.com/sitemap.xml"},
        headers={"Authorization": f"Bearer {expired['token']}"}
    )
    assert exp_res.status_code == 401
    assert "expired" in exp_res.json().get("detail", "").lower()

def test_authenticated_inspection_elegant_themes_sitemap():
    """Requirement 8: Verify inspection works for the Elegant Themes sitemap with valid consultant auth."""
    # Authenticate via /api/auth/login
    login_res = client.post("/api/auth/login", json={
        "username": "consultant@apex.io",
        "password": "consultant2026"
    })
    assert login_res.status_code == 200, f"Login failed: {login_res.text}"
    token = login_res.json()["token"]
    assert token and "." in token

    # Check session cookie set
    assert "session_token" in login_res.cookies

    # Inspect Elegant Themes sitemap
    res = client.post(
        "/api/kb/ingestion/inspect",
        json={"sitemap_url": "https://help.elegantthemes.com/sitemap.xml"},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res.status_code == 200, f"Inspection failed: {res.text}"
    data = res.json()

    assert data["total_urls_found"] >= 900
    assert data["total_sitemaps_found"] >= 1
    assert data["first_url"] and data["first_url"].startswith("http")
    assert data["last_url"] and data["last_url"].startswith("http")

    speed = data.get("speed_estimates", {})
    assert speed.get("pages_per_5_min", 0) > 0
    assert speed.get("pages_per_hour", 0) > 0
    assert speed.get("pages_per_24_hours", 0) > 0
    assert "estimated_time_text" in speed
    assert "pipeline_stages" in speed

def test_authenticated_inspection_via_session_cookie():
    """Verify session_token cookie provides transparent browser session authentication."""
    login_res = client.post("/api/auth/login", json={
        "username": "consultant@apex.io",
        "password": "consultant2026"
    })
    assert login_res.status_code == 200
    cookie_token = login_res.cookies["session_token"]

    # Call inspect with cookie instead of Authorization header
    res = client.post(
        "/api/kb/ingestion/inspect",
        json={"sitemap_url": "https://help.elegantthemes.com/sitemap.xml"},
        cookies={"session_token": cookie_token}
    )
    assert res.status_code == 200
    assert res.json()["total_urls_found"] >= 900

def test_authenticated_inspection_generic_sitemap():
    """Verify generic sitemap inspection on Brilliant Directories sitemap."""
    session = create_session_jwt(user_id="consultant_lead_01", account_id="acc_default")
    res = client.post(
        "/api/kb/ingestion/inspect",
        json={"sitemap_url": "https://support.brilliantdirectories.com/support/sitemap.xml"},
        headers={"Authorization": f"Bearer {session['token']}"}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["total_urls_found"] > 0
    assert "speed_estimates" in data
