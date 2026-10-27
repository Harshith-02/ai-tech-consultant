import os
import sys
import base64
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "task1-knowledge-brain"))

from fastapi.testclient import TestClient
from api.index import app, encrypt_secret, decrypt_secret, get_aes_gcm_cipher, create_session_jwt
from ingestion.crawler import is_safe_external_url, safe_http_get


client = TestClient(app)

def test_missing_encryption_key_fails_safely():
    """Verify that absent GMAIL_ENCRYPTION_KEY in production mode refuses to encrypt and raises RuntimeError."""
    with patch.dict(os.environ, {"GMAIL_ENCRYPTION_KEY": "", "TESTING": "0"}, clear=False):
        with patch("api.index.GMAIL_ENCRYPTION_KEY", ""):
            # When pytest is running, get_aes_gcm_cipher checks PYTEST_CURRENT_TEST;
            # patch that to simulate real production cold start without key
            with patch.dict(os.environ, {"PYTEST_CURRENT_TEST": ""}):
                cipher = get_aes_gcm_cipher()
                assert cipher is None, "Cipher should be None when GMAIL_ENCRYPTION_KEY is unset in production"
                with pytest.raises(RuntimeError) as exc_info:
                    encrypt_secret("secret_oauth_token_xyz")
                assert "GMAIL_ENCRYPTION_KEY is not configured" in str(exc_info.value)

def test_aes_256_gcm_encryption_and_decryption():
    """Verify standard AES-256-GCM encryption with version prefix v1: and roundtrip decryption."""
    with patch.dict(os.environ, {"GMAIL_ENCRYPTION_KEY": "production-grade-32-byte-secret-key-12345!"}):
        original = "ya29.a0AfH6SMB_SAMPLE_GMAIL_OAUTH_ACCESS_TOKEN_2026"
        encrypted = encrypt_secret(original)
        
        assert encrypted.startswith("v1:"), f"Ciphertext must have version prefix v1:, got: {encrypted[:10]}"
        raw_b64 = encrypted[3:]
        raw_bytes = base64.b64decode(raw_b64.encode("ascii"))
        
        # 12 bytes nonce + at least 16 bytes auth tag + ciphertext
        assert len(raw_bytes) >= 28
        
        # Verify clean decryption
        decrypted = decrypt_secret(encrypted)
        assert decrypted == original, "Decrypted text must match original plaintext"

def test_ciphertext_tampering_and_invalid_auth_tag():
    """Verify that tampering with any byte in ciphertext or authentication tag safely rejects decryption."""
    with patch.dict(os.environ, {"GMAIL_ENCRYPTION_KEY": "production-grade-32-byte-secret-key-12345!"}):
        original = "sensitive-refresh-token-value-999"
        encrypted = encrypt_secret(original)
        
        raw_bytes = bytearray(base64.b64decode(encrypted[3:].encode("ascii")))
        # Tamper with the last byte (part of AES-GCM 16-byte authentication tag)
        raw_bytes[-1] ^= 0xFF
        tampered_encrypted = "v1:" + base64.b64encode(bytes(raw_bytes)).decode("ascii")
        
        # Must fail safely and return empty string without leaking exceptions
        tampered_result = decrypt_secret(tampered_encrypted)
        assert tampered_result == "", "Tampered ciphertext must be safely rejected by AES-GCM tag verification"

def test_legacy_ciphertext_backward_compatibility():
    """Verify that legacy XOR-HMAC tokens can be decrypted during key transition."""
    key = "ai-tech-consultant-oauth-secret-key-2026"
    with patch.dict(os.environ, {"GMAIL_ENCRYPTION_KEY": key}):
        # Construct a legacy token (iv(16) + mac(32) + cipher_bytes)
        import hmac, hashlib
        iv = b"\x01" * 16
        text = b"legacy-token-data-12345"
        keystream = bytearray()
        counter = 0
        while len(keystream) < len(text):
            block = hmac.new(key.encode("utf-8"), iv + counter.to_bytes(4, "big"), hashlib.sha256).digest()
            keystream.extend(block)
            counter += 1
        cipher_bytes = bytes([b ^ k for b, k in zip(text, keystream[:len(text)])])
        mac = hmac.new(key.encode("utf-8"), iv + cipher_bytes, hashlib.sha256).digest()
        legacy_token = base64.b64encode(iv + mac + cipher_bytes).decode("ascii")
        
        decrypted = decrypt_secret(legacy_token)
        assert decrypted == "legacy-token-data-12345", "Legacy XOR-HMAC token must be decrypted cleanly"

def test_sitemap_ssrf_blocking_private_and_metadata_destinations():
    """Verify that private IP ranges, loopback, link-local, and cloud metadata are blocked."""
    assert is_safe_external_url("http://127.0.0.1:8000/internal") is False
    assert is_safe_external_url("http://localhost:5000/admin") is False
    assert is_safe_external_url("http://0.0.0.0:8000") is False
    assert is_safe_external_url("http://169.254.169.254/latest/meta-data") is False
    assert is_safe_external_url("http://metadata.google.internal/computeMetadata/v1/") is False
    assert is_safe_external_url("http://10.0.0.1/sitemap.xml") is False
    assert is_safe_external_url("http://192.168.1.1/sitemap.xml") is False
    assert is_safe_external_url("http://172.16.0.1/sitemap.xml") is False
    assert is_safe_external_url("ftp://example.com/sitemap.xml") is False
    assert is_safe_external_url("file:///etc/passwd") is False
    assert is_safe_external_url("https://support.brilliantdirectories.com/support/sitemap.xml") is True

def test_sitemap_redirect_ssrf_protection():
    """Verify that safe_http_get intercepts redirects pointing to internal/metadata endpoints."""
    mock_resp_redirect = MagicMock()
    mock_resp_redirect.status_code = 301
    mock_resp_redirect.headers = {"location": "http://169.254.169.254/latest/meta-data"}

    with patch("httpx.Client.get", return_value=mock_resp_redirect):
        with pytest.raises(ValueError) as exc_info:
            safe_http_get("https://support.brilliantdirectories.com/support/sitemap.xml")
        assert "Blocked unsafe SSRF destination" in str(exc_info.value)
        assert "169.254.169.254" in str(exc_info.value)

def test_sitemap_redirect_loop_protection():
    """Verify that safe_http_get detects and aborts redirect loops."""
    mock_resp_loop = MagicMock()
    mock_resp_loop.status_code = 302
    mock_resp_loop.headers = {"location": "https://support.brilliantdirectories.com/loop"}

    with patch("httpx.Client.get", return_value=mock_resp_loop):
        with pytest.raises(ValueError) as exc_info:
            safe_http_get("https://support.brilliantdirectories.com/loop")
        assert "Redirect loop detected" in str(exc_info.value)

def test_authentication_enforcement_on_protected_endpoints():
    """Verify that protected management endpoints return HTTP 401 when no auth credentials are provided."""
    isolated_client = TestClient(app)
    
    # Protected sitemap management
    res_sources = isolated_client.get("/api/kb/sitemap/sources")
    assert res_sources.status_code == 401, f"Expected 401 Unauthorized, got {res_sources.status_code}"
    assert "Authentication required" in res_sources.json()["detail"]

    # Protected email retrieval
    res_emails = isolated_client.get("/api/inbox/emails")
    assert res_emails.status_code == 401, f"Expected 401 Unauthorized, got {res_emails.status_code}"

    # Protected review draft
    res_review = isolated_client.post("/api/inbox/review-draft", json={"emailId": "EM-001", "predictedCategory": "filters", "approvalOutcome": "approved", "generatedDraft": "Draft content"})
    assert res_review.status_code == 401, f"Expected 401 Unauthorized, got {res_review.status_code}"

def test_authorization_rejection_on_invalid_credentials():
    """Verify that invalid tokens return HTTP 403 Forbidden."""
    isolated_client = TestClient(app)
    bad_headers = {"Authorization": "Bearer completely-invalid-secret-token-xyz"}

    res = isolated_client.get("/api/kb/sitemap/sources", headers=bad_headers)
    assert res.status_code == 403, f"Expected 403 Forbidden, got {res.status_code}"
    assert "Forbidden" in res.json()["detail"]

def test_authorized_access_succeeds():
    """Verify that valid tokens return HTTP 200 OK and allow access."""
    isolated_client = TestClient(app)
    session = create_session_jwt(user_id="consultant_lead_01", account_id="acc_default")
    valid_headers = {"Authorization": f"Bearer {session['token']}"}

    res = isolated_client.get("/api/kb/sitemap/sources", headers=valid_headers)
    assert res.status_code == 200, f"Expected 200 OK, got {res.status_code}: {res.text}"
    assert "sources" in res.json()


def test_public_health_endpoints_remain_accessible():
    """Verify that public health endpoints do not require authentication."""
    isolated_client = TestClient(app)
    
    res1 = isolated_client.get("/health")
    assert res1.status_code == 200
    assert res1.json()["status"] == "ok"

    res2 = isolated_client.get("/api/kb/health")
    assert res2.status_code == 200
    assert res2.json()["status"] == "ok"
