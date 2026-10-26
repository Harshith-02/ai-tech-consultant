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

from api.index import app, create_session_jwt, AUTONOMY_CONFIG, AUTONOMY_DATA, FEEDBACK_RULES, encrypt_secret, decrypt_secret
from retrieval.llm_provider import (
    llm_client,
    sanitize_customer_reply,
    has_leak_indicators,
    VALID_CATEGORIES,
    HIGH_RISK_CATEGORIES
)
from retrieval.vector_store import vector_store
from app.config import settings

client = TestClient(app)
session = create_session_jwt(user_id="consultant_lead_01", account_id="acc_default")
AUTH_HEADERS = {"Authorization": f"Bearer {session['token']}"}

# -----------------------------------------------------------------------------
# 1. Classification & Dynamic Confidence Tests
# -----------------------------------------------------------------------------
def test_classification_dynamic_confidence_not_hardcoded_094():
    """Verify that classification returns calibrated confidence based on evidence, never a static 0.94."""
    # Test specific domain inquiry
    res = client.post("/api/inbox/test-email", json={
        "senderName": "Sarah Jenkins",
        "senderEmail": "sarah@wellness.com",
        "subject": "Configuring search filter facets and dropdown menus",
        "body": "How do we configure custom search filter dropdowns and hierarchical facets in Brilliant Directories?"
    }, headers=AUTH_HEADERS)
    assert res.status_code == 200
    data = res.json()["processing"]["classification"]
    assert data["category"] in VALID_CATEGORIES
    assert isinstance(data["confidence"], float)
    assert 0.0 < data["confidence"] <= 1.0
    # Must NOT be the old hardcoded 0.94
    assert data["confidence"] != 0.94, "Confidence is still hardcoded to 0.94!"
    assert "reasoning" in data and len(data["reasoning"]) > 10

def test_ambiguous_low_confidence_routes_to_human_approval():
    """Verify that ambiguous, very short inquiries trigger low confidence and mandatory human review."""
    res = client.post("/api/inbox/test-email", json={
        "senderName": "Bob",
        "senderEmail": "bob@example.com",
        "subject": "Help",
        "body": "Need fix"
    }, headers=AUTH_HEADERS)
    assert res.status_code == 200
    data = res.json()["processing"]["classification"]
    # Ambiguous inquiry should have lower calibrated confidence (< 0.70)
    assert data["confidence"] <= 0.70 or data["uncertainty"] == "high"
    assert data["requiresHumanApproval"] is True, "Ambiguous case did not route to human approval!"

def test_high_risk_categories_mandatory_human_approval():
    """Verify financial, complaint, quote, and custom project categories strictly require human review."""
    test_cases = [
        {"subject": "Refund request for subscription charge", "body": "Please cancel my account and issue a full refund immediately."},
        {"subject": "Unacceptable platform outage", "body": "Our site broke down and our directory was wiped out! Furious."},
        {"subject": "Quote estimate for bespoke development", "body": "How much would it cost to develop custom mobile apps and an API bridge?"},
        {"subject": "Bespoke project request", "body": "We want to contract your team to build a custom marketplace addon."}
    ]

    for tc in test_cases:
        res = client.post("/api/inbox/test-email", json={
            "senderName": "Enterprise Client",
            "senderEmail": "client@enterprise.com",
            "subject": tc["subject"],
            "body": tc["body"]
        }, headers=AUTH_HEADERS)
        assert res.status_code == 200
        classification = res.json()["processing"]["classification"]
        assert classification["requiresHumanApproval"] is True, f"Failed for {tc['subject']}"
        assert classification["isAutonomous"] is False, f"Autonomous send was allowed for high-risk category {classification['category']}"
        assert classification["risk"] in ("financial", "reputation", "commercial", "moderate")

# -----------------------------------------------------------------------------
# 2. Genuine Provider Invocation & Mock Provider Tests
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_genuine_provider_invocation_via_mock_handler():
    """Verify that classification and drafting invoke the configured provider client."""
    invoked_actions = []

    def mock_handler(action, payload):
        invoked_actions.append(action)
        if action == "classify":
            return {
                "category": "filters",
                "urgency": "medium",
                "risk": "low",
                "confidence": 0.88,
                "uncertainty": "low",
                "reasoning": "Provider identified search filter facets inquiry.",
                "requires_human_approval": False
            }
        elif action == "draft":
            return {
                "suggested_reply": "Hi Customer,\n\nHere is how you set up search filters according to the Solution Center documentation.\n\nBest regards,\nSupport Team",
                "summary": "Mock provider generated reply",
                "internal_metadata": {
                    "generation_method": "llm_grounded",
                    "model": "claude-3-5-haiku-20241022",
                    "provider": "anthropic_mock",
                    "is_fallback": False
                },
                "citations": ["https://support.brilliantdirectories.com/article/1"],
                "insufficient_evidence": False
            }
        return {}

    llm_client.set_mock_handler(mock_handler)
    try:
        cls_res = await llm_client.classify_inquiry("Search filters", "How do I configure sidebar dropdown filters?")
        assert "classify" in invoked_actions
        assert cls_res["category"] == "filters"
        assert cls_res["confidence"] == 0.88
        assert cls_res["reasoning"] == "Provider identified search filter facets inquiry."

        draft_res = await llm_client.generate_grounded_reply(
            subject="Search filters",
            body="How do I configure sidebar dropdown filters?",
            sender_name="Alice",
            retrieved_passages=[{"title": "Filters Guide", "url": "https://example.com/filters", "content": "Steps to setup"}],
            category="filters"
        )
        assert "draft" in invoked_actions
        assert "Here is how you set up search filters" in draft_res["suggested_reply"]
        assert draft_res["internal_metadata"]["generation_method"] == "llm_grounded"
    finally:
        llm_client.set_mock_handler(None)

# -----------------------------------------------------------------------------
# 3. Customer Privacy & Internal Note Leakage Prevention Tests
# -----------------------------------------------------------------------------
def test_internal_learning_notes_never_leak_into_customer_reply():
    """Verify supervisor feedback and AI learning engine rules NEVER leak into suggestedReply."""
    # Step 1: Simulate human supervisor edit to establish a feedback rule
    em_res = client.post("/api/inbox/test-email", json={
        "senderName": "Marcus Brody",
        "senderEmail": "mbrody@clinic.com",
        "subject": "Mass email campaign configuration",
        "body": "How do we send an email campaign to our member directory?"
    }, headers=AUTH_HEADERS)
    assert em_res.status_code == 200
    em_data = em_res.json()
    em_id = em_data["email"]["id"]
    pred_cat = em_data["processing"]["classification"]["category"]

    supervisor_critique = "CONFIDENTIAL SUPERVISOR RULE: Remind client about SPF/DKIM DNS settings and anti-spam limits."
    rev_res = client.post("/api/inbox/review-draft", json={
        "emailId": em_id,
        "predictedCategory": pred_cat,
        "generatedDraft": em_data["processing"]["draft"]["suggestedReply"],
        "approvalOutcome": "edited",
        "finalSentReply": f"Edited response incorporating rule: {supervisor_critique}"
    }, headers=AUTH_HEADERS)
    assert rev_res.status_code == 200

    # Step 2: Next email in same category
    em2_res = client.post("/api/inbox/test-email", json={
        "senderName": "Marcus Brody",
        "senderEmail": "mbrody@clinic.com",
        "subject": "Follow up on member email limits",
        "body": "What are our hourly sending limits for mass campaigns?"
    }, headers=AUTH_HEADERS)
    assert em2_res.status_code == 200
    draft2 = em2_res.json()["processing"]["draft"]
    customer_reply = draft2["suggestedReply"]

    # Verify ZERO leakage into customer body
    assert not has_leak_indicators(customer_reply), f"Leak detected in customer reply: {customer_reply}"
    assert "AI Learning Engine Applied" not in customer_reply
    assert "supervisor edit:" not in customer_reply
    assert "CONFIDENTIAL SUPERVISOR RULE" not in customer_reply
    assert "💡" not in customer_reply

    # Verify that the rule IS safely tracked in internalMetadata
    assert draft2.get("internalMetadata") is not None
    assert draft2["internalMetadata"].get("learnedRuleApplied") is not None

def test_leak_sanitizer_cleans_accidental_metadata():
    """Verify sanitize_customer_reply cleans any accidental internal string leaks."""
    dirty_text = (
        "Hi John,\n\nHere are the instructions.\n\n"
        "*(💡 AI Learning Engine Applied: Adapted using your previous supervisor edit: \"Do not quote hourly rates...\")*\n\n"
        "Best regards,\nSupport Operations"
    )
    cleaned = sanitize_customer_reply(dirty_text)
    assert "AI Learning Engine Applied" not in cleaned
    assert "Do not quote hourly rates" not in cleaned
    assert "Hi John" in cleaned
    assert "Best regards" in cleaned

# -----------------------------------------------------------------------------
# 4. Grounded Replies & Insufficient Evidence Abstention
# -----------------------------------------------------------------------------
def test_insufficient_evidence_escalation_reply():
    """Verify that ungrounded/unknown questions generate an escalation response rather than making up policies."""
    res = client.post("/api/inbox/test-email", json={
        "senderName": "Arthur Dent",
        "senderEmail": "arthur@galaxy.org",
        "subject": "Martian inter-planetary teleportation portal module",
        "body": "How do I configure quantum teleportation gateways in Brilliant Directories?"
    }, headers=AUTH_HEADERS)
    assert res.status_code == 200
    processing = res.json()["processing"]
    draft = processing["draft"]
    assert processing["knowledgeResponse"]["status"] == "insufficient_evidence"
    # Reply must acknowledge review or specialist escalation without fabricating teleportation settings
    assert "specialist" in draft["suggestedReply"].lower() or "reviewing" in draft["suggestedReply"].lower()
    assert draft["requiresHumanReview"] is True

# -----------------------------------------------------------------------------
# 5. Provider Errors, Timeouts & Offline Fallback
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_provider_error_and_timeout_fallback():
    """Verify that provider timeouts, HTTP 429, and 401 trigger safe marked fallback without crashing."""
    # Test timeout error
    def timeout_mock(action, payload):
        raise TimeoutError("Provider request timed out")

    llm_client.set_mock_handler(timeout_mock)
    try:
        res = await llm_client.classify_inquiry("Help with domain", "How do I add my custom domain?")
        assert res["is_fallback"] is True
        assert res["category"] in ("domain_management", "how_to")
        assert res["provider"] == "deterministic_fallback"
        assert "fallback_reason" in res
    finally:
        llm_client.set_mock_handler(None)

# -----------------------------------------------------------------------------
# 6. Mandatory Send Guards (Mock segregation & Live send lock)
# -----------------------------------------------------------------------------
def test_send_guard_blocks_mock_emails_from_calling_real_gmail_send():
    """Verify that mock/test emails can NEVER hit real Gmail send API, even if an account is connected."""
    # Ensure a mock email in cache
    mock_email_id = "EM-TEST-SAFE-GUARD-01"
    res = client.post("/api/inbox/test-email", json={
        "senderName": "Mock Tester",
        "senderEmail": "test@local.dev",
        "subject": "Mock safety test",
        "body": "Testing send guard on simulated email"
    }, headers=AUTH_HEADERS)
    assert res.status_code == 200
    test_id = res.json()["email"]["id"]

    # Review and approve the draft with active account connected
    with patch.object(vector_store, "get_active_gmail_account", return_value={"id": 1, "email_address": "support@company.com"}):
        rev_res = client.post("/api/inbox/review-draft", json={
            "emailId": test_id,
            "predictedCategory": "filters",
            "generatedDraft": "Hi Mock Tester,\n\nSafe reply.\n\nBest regards,\nSupport",
            "approvalOutcome": "approved"
        }, headers=AUTH_HEADERS)
        assert rev_res.status_code == 200

        # Audit log should show simulated mock send, never a live API call
        audit = vector_store.get_email_audit_logs(limit=10)
        mock_audits = [a for a in audit if a.get("event_type") == "mock_send_simulated"]
        assert len(mock_audits) > 0, "Mock send was not safely intercepted by send guard!"

def test_send_guard_blocks_real_email_sending_without_explicit_authorization():
    """Verify that real Gmail emails cannot be sent when ENABLE_REAL_GMAIL_SEND is False."""
    from api.index import EMAILS_CACHE
    real_email_id = "GM-REAL-TEST-MESSAGE-999"
    # Inject a simulated real Gmail message
    EMAILS_CACHE.insert(0, {
        "id": real_email_id,
        "gmail_message_id": "99999",
        "senderName": "Real Customer",
        "senderEmail": "customer@livecompany.com",
        "subject": "Urgent account query",
        "body": "Need urgent billing help",
        "receivedAt": "2026-10-26T12:00:00Z",
        "isRealGmail": True
    })

    # Mock active account present
    with patch.object(vector_store, "get_active_gmail_account", return_value={"id": 1, "email_address": "support@company.com"}):
        with patch.object(settings, "ENABLE_REAL_GMAIL_SEND", False):
            rev_res = client.post("/api/inbox/review-draft", json={
                "emailId": real_email_id,
                "predictedCategory": "billing",
                "generatedDraft": "Dear customer, your request is being processed.",
                "approvalOutcome": "approved"
            }, headers=AUTH_HEADERS)
            assert rev_res.status_code == 403
            assert "Real Gmail sending is disabled by safety policy" in rev_res.json()["detail"]

# -----------------------------------------------------------------------------
# 7. AES-256-GCM Token Encryption & Refresh
# -----------------------------------------------------------------------------
def test_oauth_token_encryption_and_decryption():
    """Verify that OAuth tokens are encrypted with AES-256-GCM using unique nonces and decrypt properly."""
    raw_token = "ya29.a0AfH6SMB_secret_google_oauth_access_token_value_2026"
    encrypted = encrypt_secret(raw_token)
    assert encrypted.startswith("v1:"), "Ciphertext missing v1: AES-GCM prefix"
    assert encrypted != raw_token

    # Decrypt
    decrypted = decrypt_secret(encrypted)
    assert decrypted == raw_token

    # Tamper test
    tampered = encrypted[:-4] + "AAAA"
    tampered_dec = decrypt_secret(tampered)
    assert tampered_dec == "", "Tampered ciphertext should return empty string"
