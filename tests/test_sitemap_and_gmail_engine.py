import sys
import os
from pathlib import Path

# Add project root and task directories to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "task1-knowledge-brain"))

from fastapi.testclient import TestClient
from api.index import app, AUTONOMY_CONFIG, AUTONOMY_DATA, FEEDBACK_RULES, SENT_EMAILS

client = TestClient(app)

def test_sitemap_inspection():
    print("\n--- Test 1: Sitemap Inspection & ETA Calculation ---")
    res = client.post("/kb/ingestion/inspect", json={
        "sitemap_url": "https://support.brilliantdirectories.com/support/sitemap.xml"
    })
    assert res.status_code == 200, f"Inspect failed: {res.text}"
    data = res.json()
    print("Inspected result:", data.get("total_urls_found"), "URLs found")
    print("First URL:", data.get("first_url"))
    print("Last URL:", data.get("last_url"))
    print("Speed estimates:", data.get("speed_estimates"))
    assert data["total_urls_found"] > 0
    assert "speed_estimates" in data
    assert data["speed_estimates"]["pages_per_5_min"] == 50
    assert data["speed_estimates"]["pages_per_hour"] == 600
    assert data["speed_estimates"]["pages_per_24_hours"] == 14400
    print("✓ Test 1 Passed!")

def test_chat_ai_reasoning_engine():
    print("\n--- Test 2: Chat AI Reasoning Engine & Prompt Engineering ---")
    res = client.post("/kb/query", json={
        "question": "How do I configure search filter dropdowns and import categories via CSV?",
        "top_k": 3
    })
    assert res.status_code == 200
    data = res.json()
    assert "thinking_process" in data, "thinking_process missing from query response"
    tp = data["thinking_process"]
    if isinstance(tp, dict):
        print("Thinking Process dictionary:", list(tp.keys()))
        assert len(tp) > 0
    else:
        print("Thinking Process snippet:\n", str(tp)[:200], "...")
        assert len(tp) > 50
    print("Answer snippet:\n", data["answer"][:150], "...")
    assert data["status"] in ["answered", "insufficient_evidence"]
    print("✓ Test 2 Passed!")

def test_gmail_engine_and_autonomy_learning():
    print("\n--- Test 3: Authentic Gmail Engine, 8 Setting Labels, Autonomy & Learning ---")
    # Reset config for clean test
    AUTONOMY_CONFIG["threshold_x"] = 3
    AUTONOMY_CONFIG["auto_send_enabled"] = True
    for cat in AUTONOMY_DATA.values():
        cat["consecutiveUneditedCount"] = 0
        cat["isEligibleForAutonomy"] = False
        cat["threshold"] = 3

    # Check folders
    folders_res = client.get("/inbox/folders")
    assert folders_res.status_code == 200
    print("Folders status:", folders_res.json())

    # Step A: Dispatch 1st test email for 'filters' category
    em1_res = client.post("/inbox/test-email", json={
        "senderName": "Fiona Gallagher",
        "senderEmail": "fiona@localgrowth.com",
        "subject": "Custom search filters dropdown configuration",
        "body": "Hi, how do we configure custom search filter dropdowns in the sidebar?"
    })
    assert em1_res.status_code == 200
    em1_data = em1_res.json()
    em1_id = em1_data["email"]["id"]
    cat = em1_data["processing"]["classification"]["category"]
    print(f"Email 1 received: ID={em1_id}, Classified Label={cat}")
    assert cat == "filters"
    assert em1_data["processing"]["classification"]["requiresHumanApproval"] is True

    # Step B: Human reviews and APPROVES unedited -> Streak becomes 1
    rev1 = client.post("/inbox/review-draft", json={
        "emailId": em1_id,
        "predictedCategory": cat,
        "generatedDraft": em1_data["processing"]["draft"]["suggestedReply"],
        "approvalOutcome": "approved"
    })
    assert rev1.status_code == 200
    st1 = rev1.json()["autonomyStatus"]
    print(f"After unedited approval 1: Streak = {st1['consecutiveUneditedCount']}/3, Autonomy = {st1['isEligibleForAutonomy']}")
    assert st1["consecutiveUneditedCount"] == 1
    assert st1["isEligibleForAutonomy"] is False

    # Step C: Human EDITS a draft -> AI Learns diff, streak resets to 0
    em2_res = client.post("/inbox/test-email", json={
        "senderName": "Fiona Gallagher",
        "senderEmail": "fiona@localgrowth.com",
        "subject": "Dropdown facet radius filter",
        "body": "Can radius distance filters be added to dropdown search filters?"
    })
    em2_id = em2_res.json()["email"]["id"]
    gen_draft = em2_res.json()["processing"]["draft"]["suggestedReply"]
    edited_reply = gen_draft + "\n\nP.S. Remember to re-index your Google sitemap under SEO Settings."

    rev2 = client.post("/inbox/review-draft", json={
        "emailId": em2_id,
        "predictedCategory": cat,
        "generatedDraft": gen_draft,
        "approvalOutcome": "edited",
        "finalSentReply": edited_reply
    })
    st2 = rev2.json()["autonomyStatus"]
    print(f"After human EDIT: Streak = {st2['consecutiveUneditedCount']}/3 (Reset!), Rules count = {len(rev2.json()['learnedRules'])}")
    assert st2["consecutiveUneditedCount"] == 0
    assert len(rev2.json()["learnedRules"]) >= 1

    # Step D: Next email in this category should include the AI Learning note!
    em3_res = client.post("/inbox/test-email", json={
        "senderName": "Fiona Gallagher",
        "senderEmail": "fiona@localgrowth.com",
        "subject": "Multilevel category search filter",
        "body": "How do sub-level category search filters work?"
    })
    draft3 = em3_res.json()["processing"]["draft"]["suggestedReply"]
    print("Draft 3 incorporates learned rules:", "AI Learning Engine Applied" in draft3)
    assert "AI Learning Engine Applied" in draft3 or "Adapted using your previous supervisor edit" in draft3

    # Step E: Approve unedited 3 times consecutively to unlock AUTONOMY!
    em3_id = em3_res.json()["email"]["id"]
    client.post("/inbox/review-draft", json={
        "emailId": em3_id, "predictedCategory": cat,
        "generatedDraft": draft3, "approvalOutcome": "approved"
    })

    # Send 2 more unedited
    for i in range(2):
        temp_res = client.post("/inbox/test-email", json={
            "senderName": "Fiona Gallagher",
            "senderEmail": "fiona@localgrowth.com",
            "subject": f"Filter search test {i+4}",
            "body": "Quick question on filter checkbox settings."
        })
        temp_id = temp_res.json()["email"]["id"]
        temp_draft = temp_res.json()["processing"]["draft"]["suggestedReply"]
        rev = client.post("/inbox/review-draft", json={
            "emailId": temp_id, "predictedCategory": cat,
            "generatedDraft": temp_draft, "approvalOutcome": "approved"
        })

    final_st = rev.json()["autonomyStatus"]
    print(f"After 3 unedited approvals: Streak = {final_st['consecutiveUneditedCount']}/3, Autonomy = {final_st['isEligibleForAutonomy']}")
    assert final_st["consecutiveUneditedCount"] >= 3
    assert final_st["isEligibleForAutonomy"] is True
    print("🎉 AUTONOMY SUCCESSFULLY UNLOCKED!")

    # Step F: Next email in 'filters' category MUST now automatically send!
    auto_res = client.post("/inbox/test-email", json={
        "senderName": "Fiona Gallagher",
        "senderEmail": "fiona@localgrowth.com",
        "subject": "Automated filter question",
        "body": "Does the system automatically dispatch this?"
    })
    auto_data = auto_res.json()
    assert auto_data["processing"]["classification"]["isAutonomous"] is True
    assert auto_data["processing"]["draft"].get("autoSent") is True
    print("✓ Email auto-sent without waiting for human review!")
    print("✓ Test 3 Passed Completely!")

def test_multi_source_sitemap_endpoints():
    print("\n--- Test 4: Multi-Source Sitemap Endpoints & Scheduling ---")
    # 1. List sources
    res = client.get("/api/kb/sitemap/sources")
    assert res.status_code == 200
    data = res.json()
    assert "sources" in data
    initial_count = data["total"]
    print(f"Initial sitemap sources count: {initial_count}")

    # 2. Create new source
    create_res = client.post("/api/kb/sitemap/sources", json={
        "name": "Integration Test Docs",
        "root_sitemap_url": "https://example.com/test-sitemap.xml",
        "refresh_interval_days": 15,
        "missing_threshold": 30
    })
    assert create_res.status_code == 200
    src = create_res.json()["source"]
    src_id = src["id"]
    assert src["name"] == "Integration Test Docs"
    assert src["refresh_interval_days"] == 15
    assert src["missing_threshold"] == 30
    print(f"Created new source: ID={src_id}")

    # 3. Update schedule
    sched_res = client.post(f"/api/kb/sitemap/sources/{src_id}/schedule", json={
        "refresh_interval_days": 30,
        "missing_threshold": 15,
        "refresh_enabled": False
    })
    assert sched_res.status_code == 200
    updated_src = sched_res.json()["source"]
    assert updated_src["refresh_interval_days"] == 30
    assert updated_src["missing_threshold"] == 15
    assert updated_src["refresh_enabled"] == 0

    # 4. List runs
    runs_res = client.get("/api/kb/sitemap/runs")
    assert runs_res.status_code == 200
    assert "runs" in runs_res.json()

    # 5. Delete source
    del_res = client.delete(f"/api/kb/sitemap/sources/{src_id}")
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "deleted"
    print("✓ Test 4 Passed Completely!")

def test_oauth_encryption_and_endpoints():
    print("\n--- Test 5: OAuth Token Encryption & Endpoints ---")
    from api.index import encrypt_secret, decrypt_secret

    # Crypto roundtrip
    secret = "ya29.a0AfH6SMD_test_token_access_xyz123"
    enc = encrypt_secret(secret)
    assert enc != secret, "Token was not encrypted"
    dec = decrypt_secret(enc)
    assert dec == secret, f"Decrypted token '{dec}' does not match original '{secret}'"

    # Tamper detection
    tampered = enc[:-4] + "AAAA"
    dec_tampered = decrypt_secret(tampered)
    assert dec_tampered == "", "Tampered token was not rejected"

    # Empty handling
    assert encrypt_secret("") == ""
    assert decrypt_secret("") == ""
    print("✓ Crypto roundtrip and HMAC authentication verified!")

    # Authorize endpoint
    auth_res = client.get("/api/inbox/oauth/authorize")
    assert auth_res.status_code == 200
    auth_data = auth_res.json()
    assert "configured" in auth_data
    print(f"OAuth authorize configured status: {auth_data['configured']}")

    # Status endpoint
    status_res = client.get("/api/inbox/oauth/status")
    assert status_res.status_code == 200
    status_data = status_res.json()
    assert "connected" in status_data
    print(f"OAuth status connected: {status_data['connected']}")

    # Sync endpoint
    sync_res = client.post("/api/inbox/sync")
    assert sync_res.status_code == 200
    sync_data = sync_res.json()
    assert sync_data["status"] in ["success", "offline_mode", "partial_error", "auth_error"]
    print(f"Sync endpoint status: {sync_data['status']}")

    # Disconnect endpoint
    disc_res = client.post("/api/inbox/oauth/disconnect")
    assert disc_res.status_code == 200
    print("✓ Test 5 Passed Completely!")

def test_audit_logging():
    print("\n--- Test 6: Email Audit Logging ---")
    res = client.get("/api/inbox/audit-logs")
    assert res.status_code == 200
    data = res.json()
    assert "logs" in data
    assert "total" in data
    print(f"Total audit log entries: {data['total']}")
    if data["logs"]:
        print(f"Latest audit entry: event_type={data['logs'][0].get('event_type')}, actor={data['logs'][0].get('actor_type')}")
    print("✓ Test 6 Passed Completely!")

if __name__ == "__main__":
    test_sitemap_inspection()
    test_chat_ai_reasoning_engine()
    test_gmail_engine_and_autonomy_learning()
    test_multi_source_sitemap_endpoints()
    test_oauth_encryption_and_endpoints()
    test_audit_logging()
    print("\n==========================================")
    print("ALL TESTS PASSED WITH 100% SUCCESS RATE!")
    print("==========================================")

