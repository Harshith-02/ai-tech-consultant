import sys
import os
from pathlib import Path

# Add project root and task directories to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "task1-knowledge-brain"))

from fastapi.testclient import TestClient
from api.index import app, AUTONOMY_CONFIG, AUTONOMY_DATA, FEEDBACK_RULES, SENT_EMAILS, create_session_jwt

client = TestClient(app)
session = create_session_jwt(user_id="consultant_lead_01", account_id="acc_default")
client.headers.update({"Authorization": f"Bearer {session['token']}"})

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
    assert data["speed_estimates"]["pages_per_5_min"] > 0
    assert data["speed_estimates"]["pages_per_hour"] > 0
    assert data["speed_estimates"]["pages_per_24_hours"] > 0
    assert "pipeline_stages" in data["speed_estimates"]
    assert "expected_completion_datetime" in data["speed_estimates"]
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

    # Step D: Next email in this category should track the learned rule in internalMetadata, NEVER leaking into suggestedReply!
    em3_res = client.post("/inbox/test-email", json={
        "senderName": "Fiona Gallagher",
        "senderEmail": "fiona@localgrowth.com",
        "subject": "Multilevel category search filter",
        "body": "How do sub-level category search filters work?"
    })
    proc3 = em3_res.json()["processing"]
    draft3_obj = proc3["draft"]
    draft3_reply = draft3_obj["suggestedReply"]
    internal_meta = draft3_obj.get("internalMetadata", {})

    # Verify learning engine rule is tracked in internal metadata
    assert proc3.get("learnedRulesCount", 0) >= 1
    assert internal_meta.get("learnedRuleApplied") is not None
    # Verify zero leakage into customer-visible suggestedReply
    assert "AI Learning Engine Applied" not in draft3_reply
    assert "Adapted using your previous supervisor edit" not in draft3_reply
    draft3 = draft3_reply

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

def test_historical_sitemap_archive():
    print("\n--- Test 7: Persistent Historical Sitemap Archive (Requirements #1 - #11) ---")
    from retrieval.vector_store import vector_store

    test_url = "https://support.brilliantdirectories.com/support/solutions/articles/12000099999-disappearing-feature-page"
    test_title = "Historical Discontinued Feature Guide"
    test_content = "This is a comprehensive guide to legacy widget settings that will disappear from the sitemap."
    test_source = "https://support.brilliantdirectories.com/support/sitemap.xml"

    # Step 1: Ingest active article with chunks
    vector_store.upsert_article(
        article_id="art_hist_test",
        url=test_url,
        title=test_title,
        category="Legacy Configuration",
        content_hash="hash_legacy_001",
        raw_text=test_content,
        screenshot_count=1,
        chunks_data=[{
            "id": "chk_hist_001",
            "section_heading": "Legacy Widget Setup",
            "content": test_content,
            "image_urls": ["https://cdn.example.com/legacy_widget.png"],
            "image_descriptions": ["Diagram of legacy widget settings"]
        }],
        sitemap_source=test_source
    )

    # Verify it is in normal search
    normal_results = vector_store.hybrid_search("legacy widget settings", limit=5)
    matched = any(r["url"] == test_url for r in normal_results)
    assert matched, "Newly ingested test article should be visible in normal search"

    # Step 2: Archive the article (simulate 15 missing checks)
    archived = vector_store.archive_article(
        test_url,
        reason="Missing across 15 consecutive checks (threshold=15)",
        checks_count=15,
        source_url=test_source
    )
    assert archived is True, "archive_article should return True"

    # Step 3: Verify requirement #6: EXCLUDED from normal search
    normal_after = vector_store.hybrid_search("legacy widget settings", limit=5)
    assert not any(r["url"] == test_url for r in normal_after), "Archived article MUST NOT appear in normal hybrid search!"

    # Verify exclusion from /kb/query endpoint
    chat_res = client.post("/kb/query", json={"question": "legacy widget settings disappearing feature"})
    assert chat_res.status_code == 200
    chat_urls = [s.get("url") for s in chat_res.json().get("sources", [])]
    assert test_url not in chat_urls, "Archived article MUST NOT be returned in ordinary /kb/query sources"

    # Step 4: Verify requirement #1 & #3: Archive inspection & list
    list_res = client.get("/api/kb/archive")
    assert list_res.status_code == 200
    list_data = list_res.json()
    assert list_data["total"] >= 1
    arch_match = next((a for a in list_data["articles"] if a["url"] == test_url), None)
    assert arch_match is not None, "Archived article must appear in /api/kb/archive list"
    assert arch_match["consecutive_missing_checks"] == 15
    assert "Missing across 15 consecutive checks" in arch_match["reason"]

    # Step 5: Verify requirement #1 & #7: Complete preserved content in detail preview
    detail_res = client.get(f"/api/kb/archive/{arch_match['id']}")
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["raw_text"] == test_content, "Complete raw text must be preserved"
    assert len(detail["chunks"]) == 1, "Full extracted chunks with headings must be preserved"
    assert detail["chunks"][0]["section_heading"] == "Legacy Widget Setup"
    assert detail["content_hash"] is not None
    assert detail["archived_at"] is not None

    # Step 6: Verify requirement #6: Dedicated historical search mode
    search_res = client.post("/api/kb/archive/search", json={"query": "legacy widget", "limit": 5})
    assert search_res.status_code == 200
    found_in_hist = any(r["url"] == test_url for r in search_res.json()["results"])
    assert found_in_hist, "Archived article MUST be searchable in dedicated historical search mode"

    # Step 7: Verify requirement #9: Cross-source protection
    # If another enabled source still uses this URL, archival should NOT deactivate it
    active_url_multi = "https://example.com/shared-doc"
    vector_store.upsert_article(
        article_id="art_shared_a",
        url=active_url_multi,
        title="Shared Article Across Sitemaps",
        category="General",
        content_hash="hash_shared_a",
        raw_text="This article exists in both Source A and Source B sitemaps.",
        screenshot_count=0,
        chunks_data=[{"id": "chk_shared_1", "section_heading": "Intro", "content": "Shared content"}],
        sitemap_source="https://source-a.com/sitemap.xml"
    )
    # Link to secondary active source
    vector_store.link_url_to_source("https://source-b.com/sitemap.xml", active_url_multi)

    # Source A reports it missing, but Source B still requires it -> should NOT archive
    cross_protected = vector_store.archive_article(
        active_url_multi,
        reason="Missing from Source A",
        checks_count=15,
        source_url="https://source-a.com/sitemap.xml"
    )
    assert cross_protected is False, "Cross-source protection: Must not archive URL when another active source requires it"

    # Step 8: Verify requirement #4: Restore to active Knowledge Base
    restore_res = client.post(f"/api/kb/archive/{arch_match['id']}/restore")
    assert restore_res.status_code == 200
    assert restore_res.json()["status"] == "restored"

    # Verify article is reactivated in hybrid search and FTS
    restored_search = vector_store.hybrid_search("legacy widget settings", limit=5)
    assert any(r["url"] == test_url for r in restored_search), "Restored article MUST immediately appear in normal search!"

    # Verify it is no longer in archived list
    list_after_restore = client.get("/api/kb/archive").json()
    assert not any(a["url"] == test_url for a in list_after_restore["articles"])

    # Step 9: Verify requirement #8: Separate archiving from permanent deletion
    # Re-archive to test permanent deletion
    vector_store.archive_article(test_url, reason="Re-archiving for deletion test")
    arch_again = next(a for a in client.get("/api/kb/archive").json()["articles"] if a["url"] == test_url)

    # Attempt delete without confirmation -> 400
    bad_del = client.delete(f"/api/kb/archive/{arch_again['id']}?confirm=false")
    assert bad_del.status_code == 400, "Permanent deletion without confirmation must be rejected"

    # Authorized deletion with confirmation
    ok_del = client.delete(f"/api/kb/archive/{arch_again['id']}?confirm=true")
    assert ok_del.status_code == 200
    assert ok_del.json()["status"] == "permanently_deleted"

    # Verify completely purged
    assert vector_store.get_archived_article_details(arch_again["id"]) is None
    print("✓ Test 7 Passed Completely!")

if __name__ == "__main__":
    test_sitemap_inspection()
    test_chat_ai_reasoning_engine()
    test_gmail_engine_and_autonomy_learning()
    test_multi_source_sitemap_endpoints()
    test_oauth_encryption_and_endpoints()
    test_audit_logging()
    test_historical_sitemap_archive()
    print("\n==========================================")
    print("ALL TESTS PASSED WITH 100% SUCCESS RATE!")
    print("==========================================")


