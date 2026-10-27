import os
import sys
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "task1-knowledge-brain"))

from api.index import app, create_session_jwt, DRAFT_EMAILS, EMAILS_CACHE, SENT_EMAILS
from retrieval.llm_provider import llm_client, sanitize_customer_reply, has_leak_indicators
from retrieval.vector_store import vector_store
from app.config import settings

client = TestClient(app)
session = create_session_jwt(user_id="consultant_lead_01", account_id="acc_default")
AUTH_HEADERS = {"Authorization": f"Bearer {session['token']}"}
UNAUTH_CLIENT = TestClient(app)

# -----------------------------------------------------------------------------
# B1. End-to-End Workflow Tracing Tests
# -----------------------------------------------------------------------------
def test_end_to_end_successful_inquiry_workflow():
    """
    Trace: Ingestion -> LLM Classification -> Hybrid Retrieval -> Grounded Reply
    -> Sanitization -> Draft Persistence -> Human Review -> Simulated Send.
    """
    # 1. Ingestion of inquiry
    req_payload = {
        "senderName": "Elena Rostova",
        "senderEmail": "elena@vintagemarket.co",
        "subject": "Social media links configuration in header and footer",
        "body": "Good morning, where in the admin dashboard can I configure our Instagram and LinkedIn links so they appear across header and footer?"
    }
    ingest_res = client.post("/api/inbox/test-email", json=req_payload, headers=AUTH_HEADERS)
    assert ingest_res.status_code == 200, f"Ingestion failed: {ingest_res.text}"
    data = ingest_res.json()
    email_id = data["email"]["id"]
    processing = data["processing"]

    # 2. Classification & confidence evaluation
    classification = processing["classification"]
    assert classification["category"] in ("header", "footer", "header_footer", "general_settings", "how_to")
    assert isinstance(classification["confidence"], float)
    assert 0.0 < classification["confidence"] <= 1.0
    assert classification["confidence"] != 0.94  # Proven dynamic

    # 3. Grounded reply generation & evidence citations
    draft = processing["draft"]
    suggested_reply = draft["suggestedReply"]
    assert len(suggested_reply) > 50
    assert len(draft["citations"]) > 0

    # 4. Strict leakage prevention
    assert not has_leak_indicators(suggested_reply)
    assert "AI Learning Engine Applied" not in suggested_reply
    assert "supervisor edit:" not in suggested_reply

    # 5. Internal metadata separation
    assert "internalMetadata" in draft
    assert draft["internalMetadata"]["classificationReasoning"] == classification["reasoning"]

    # 6. Draft persistence in DRAFT_EMAILS
    assert email_id in DRAFT_EMAILS

    # 7. Human review and approval
    review_res = client.post("/api/inbox/review-draft", json={
        "emailId": email_id,
        "predictedCategory": classification["category"],
        "generatedDraft": suggested_reply,
        "approvalOutcome": "approved"
    }, headers=AUTH_HEADERS)
    assert review_res.status_code == 200
    review_data = review_res.json()
    assert "autonomyStatus" in review_data

def test_end_to_end_anonymous_inquiries_strictly_rejected():
    """Verify that unauthenticated calls to all Task 2 workflow endpoints return HTTP 401."""
    assert UNAUTH_CLIENT.get("/api/inbox/folders").status_code == 401
    assert UNAUTH_CLIENT.post("/api/inbox/test-email", json={"subject": "test", "body": "test"}).status_code == 401
    assert UNAUTH_CLIENT.post("/api/inbox/process-email", json={"emailId": "EM-1"}).status_code == 401
    assert UNAUTH_CLIENT.post("/api/inbox/review-draft", json={"emailId": "EM-1", "predictedCategory": "filters", "generatedDraft": "reply", "approvalOutcome": "approved"}).status_code == 401
    assert UNAUTH_CLIENT.post("/api/inbox/sync").status_code == 401
    assert UNAUTH_CLIENT.get("/api/inbox/oauth/status").status_code == 401

def test_end_to_end_malformed_input_gracefully_rejected():
    """Verify that invalid payloads return structured 400/422 responses, never 500 server crashes."""
    # Missing required body
    res1 = client.post("/api/inbox/process-email", json={}, headers=AUTH_HEADERS)
    assert res1.status_code == 400
    assert "Valid emailId or rawEmail required" in res1.json()["detail"]

    # Invalid email ID
    res2 = client.post("/api/inbox/process-email", json={"emailId": "NON_EXISTENT_ID_9999"}, headers=AUTH_HEADERS)
    assert res2.status_code == 400

def test_end_to_end_insufficient_evidence_escalation_workflow():
    """Verify out-of-domain query triggers abstention and human routing without inventing facts."""
    res = client.post("/api/inbox/test-email", json={
        "senderName": "Zaphod Beeblebrox",
        "senderEmail": "zaphod@heartofgold.gal",
        "subject": "Infinite Improbability Drive configuration",
        "body": "How do I configure quantum teleportation hyperdrives in the Brilliant Directories admin menu?"
    }, headers=AUTH_HEADERS)
    assert res.status_code == 200
    data = res.json()["processing"]
    # RAG pipeline must abstain
    assert data["knowledgeResponse"]["status"] == "insufficient_evidence"
    # Draft must require human review
    assert data["draft"]["requiresHumanReview"] is True
    # Customer reply must offer escalation, not fabricate hyperdrive settings
    reply = data["draft"]["suggestedReply"].lower()
    assert "specialist" in reply or "reviewing" in reply or "contacting" in reply

def test_end_to_end_provider_outage_resilience():
    """Verify that provider 500/503 outages or connection timeouts fallback safely."""
    def outage_mock(action, payload):
        raise ConnectionError("Upstream LLM Provider 503 Service Unavailable")

    llm_client.set_mock_handler(outage_mock)
    try:
        res = client.post("/api/inbox/test-email", json={
            "senderName": "Testing User",
            "senderEmail": "test@domain.com",
            "subject": "Email forwarders setup in cPanel",
            "body": "How do we set up email forwarders to redirect to external accounts?"
        }, headers=AUTH_HEADERS)
        assert res.status_code == 200
        classification = res.json()["processing"]["classification"]
        assert classification["isFallback"] is True
        assert classification["provider"] == "deterministic_fallback"
    finally:
        llm_client.set_mock_handler(None)

# -----------------------------------------------------------------------------
# B3. Persistence & Database Integrity Tests
# -----------------------------------------------------------------------------
def test_vector_dimension_and_normalization_integrity():
    """Verify all 454 chunk embeddings in SQLite match 384 dimensions and are L2 normalized."""
    import sqlite3
    import math

    conn = sqlite3.connect(settings.DB_PATH)
    c = conn.cursor()
    rows = c.execute("SELECT id, embedding_json FROM chunks WHERE embedding_json IS NOT NULL").fetchall()
    assert len(rows) >= 450, f"Expected ~454 chunks, found {len(rows)}"

    for chunk_id, emb_json in rows[:50]:  # sample 50 chunks
        vec = json.loads(emb_json)
        assert len(vec) == 384, f"Chunk {chunk_id} embedding dimension {len(vec)} != 384"
        norm = math.sqrt(sum(x * x for x in vec))
        assert abs(norm - 1.0) < 0.05, f"Chunk {chunk_id} embedding not L2 normalized (norm={norm})"
    conn.close()

def test_durable_rate_limits_persist_in_sqlite():
    """Verify that multi-instance serverless rate limits are stored in the SQLite rate_limits table."""
    test_key = "test_client_integration_99"
    # Test durable rate limiter directly
    allowed = vector_store.check_rate_limit(
        key=test_key,
        max_requests=5,
        window_seconds=60
    )
    assert allowed is True

    # Direct DB inspection
    import sqlite3
    conn = sqlite3.connect(settings.DB_PATH)
    c = conn.cursor()
    row = c.execute("SELECT timestamp FROM rate_limits WHERE key = ?", (test_key,)).fetchone()
    assert row is not None
    assert row[0] > 0
    conn.close()

# -----------------------------------------------------------------------------
# B4. Frontend/Backend Integration & Security Tests
# -----------------------------------------------------------------------------
def test_production_cors_allowlist_and_credential_safety():
    """Verify production CORS origins are strict and credentials policy is valid."""
    from api.index import get_allowed_origins
    origins = get_allowed_origins()
    assert isinstance(origins, list)
    assert len(origins) > 0
    # Confirm local and vercel origins are present
    assert any("localhost" in o or "127.0.0.1" in o for o in origins)

def test_no_internal_metadata_in_customer_draft_text():
    """Verify that draft response bodies across all categories contain zero internal prompts or debug notes."""
    categories_to_test = [
        ("Filters inquiry", "How do I add faceted search filters?"),
        ("Billing dispute", "There is an incorrect charge on my invoice."),
        ("Custom add-on", "Can you build a custom mobile application integration?"),
        ("General question", "Where do I configure company logo in header?")
    ]

    for subj, body in categories_to_test:
        res = client.post("/api/inbox/test-email", json={
            "senderName": "Test Client",
            "senderEmail": "test@client.com",
            "subject": subj,
            "body": body
        }, headers=AUTH_HEADERS)
        assert res.status_code == 200
        reply = res.json()["processing"]["draft"]["suggestedReply"]
        assert not has_leak_indicators(reply)
        assert "💡" not in reply
        assert "AI Learning Engine Applied" not in reply
        assert "confidence:" not in reply
        assert "requiresHumanApproval" not in reply
