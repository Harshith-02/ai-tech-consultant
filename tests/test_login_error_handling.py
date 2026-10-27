import pytest
from fastapi.testclient import TestClient
from api.index import app

client = TestClient(app)

def test_cors_headers_for_port_3000():
    """Verify that requests from port 3000 receive valid CORS headers."""
    response = client.options(
        "/api/auth/login",
        headers={
            "Origin": "http://127.0.0.1:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type",
        }
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://127.0.0.1:3000"
    assert response.headers.get("access-control-allow-credentials") == "true"

def test_login_successful_json_response():
    """Verify successful login returns JSON and sets cookie."""
    response = client.post(
        "/api/auth/login",
        json={"username": "consultant@apex.io", "password": "consultant2026"},
        headers={"Origin": "http://127.0.0.1:3000"}
    )
    assert response.status_code == 200
    assert "application/json" in response.headers.get("content-type", "")
    data = response.json()
    assert data["status"] == "authenticated"
    assert "token" in data
    assert data["user"]["email"] == "consultant@apex.io"
    assert "session_token" in response.cookies

def test_login_invalid_password_returns_json_error():
    """Verify invalid password returns JSON 401, never HTML."""
    response = client.post(
        "/api/auth/login",
        json={"username": "consultant@apex.io", "password": "wrong_password_123"},
        headers={"Origin": "http://127.0.0.1:3000"}
    )
    assert response.status_code == 401
    assert "application/json" in response.headers.get("content-type", "")
    data = response.json()
    assert "detail" in data
    assert "Invalid email or password" in data["detail"]
    # Ensure it is not HTML
    assert not response.text.strip().startswith("<!DOCTYPE")
    assert not response.text.strip().startswith("<html")

def test_login_empty_credentials_returns_json_error():
    """Verify empty credentials return JSON 401, never HTML."""
    response = client.post(
        "/api/auth/login",
        json={"username": "", "password": ""},
        headers={"Origin": "http://127.0.0.1:3000"}
    )
    assert response.status_code == 401
    assert "application/json" in response.headers.get("content-type", "")
    data = response.json()
    assert "detail" in data
