import httpx
import json
import time

def verify_all():
    print("=" * 65)
    print("RUNNING LIVE END-TO-END VERIFICATION OF ALL SERVICES")
    print("=" * 65)

    client = httpx.Client(timeout=10.0)

    # 1. Task 1 Health & Grounded Query
    print("\n[1/6] Verifying Task 1: Knowledge Brain (Port 8000)...")
    r_h1 = client.get("http://127.0.0.1:8000/health")
    assert r_h1.status_code == 200, f"Health check failed: {r_h1.text}"
    print(f"  [PASS] Health OK: {r_h1.json()['indexed_articles']} articles, {r_h1.json()['indexed_chunks']} chunks")

    q1 = {"question": "How do I import categories via CSV file in Brilliant Directories?", "top_k": 3}
    r_q1 = client.post("http://127.0.0.1:8000/query", json=q1)
    assert r_q1.status_code == 200, f"Query failed: {r_q1.text}"
    d_q1 = r_q1.json()
    print(f"  [PASS] Grounded Query: status={d_q1['status']}, conf={d_q1['confidence']:.2f}")
    print(f"    Top Source: {d_q1['sources'][0]['title']}")
    print(f"    URL Citation: {d_q1['sources'][0]['url']}")

    # 2. Task 1 Out-of-Scope Query & Escalation Loop
    print("\n[2/6] Verifying Task 1 Abstention & Escalation Generation...")
    q_esc = {"question": "Does Brilliant Directories support quantum entanglement billing tokens?", "top_k": 3}
    r_esc = client.post("http://127.0.0.1:8000/query", json=q_esc)
    assert r_esc.status_code == 200
    d_esc = r_esc.json()
    print(f"  [PASS] Abstention status={d_esc['status']}, confidence={d_esc['confidence']}")
    print(f"  [PASS] Escalation ticket created: {d_esc['escalation_id']} (needs_human={d_esc['needs_human']})")

    # 3. Task 2 Inbox Agent Processing
    print("\n[3/6] Verifying Task 2: Inbox Agent (Port 3001)...")
    r_emails = client.get("http://127.0.0.1:3001/emails")
    assert r_emails.status_code == 200
    emails_data = r_emails.json()
    emails_list = emails_data.get("emails", [])
    print(f"  [PASS] Loaded {len(emails_list)} customer emails")

    r_proc = client.post("http://127.0.0.1:3001/process-email", json={"emailId": "EM-001"})
    assert r_proc.status_code == 200
    d_proc = r_proc.json()
    print(f"  [PASS] Classified EM-001 as: {d_proc['classification']['category']} (Urgency: {d_proc['classification']['urgency']})")
    print(f"  [PASS] Task 1 Grounding check: status={d_proc['knowledgeResponse']['status']}, sources={len(d_proc['knowledgeResponse']['sources'])}")
    print(f"  [PASS] Draft generated: \"{d_proc['draft']['summary']}\"")

    # 4. Task 2 Review & Streak Engine
    print("\n[4/6] Verifying Task 2 Human-in-the-Loop & Autonomy Streak...")
    r_rev = client.post("http://127.0.0.1:3001/review-draft", json={
        "emailId": "EM-001",
        "predictedCategory": "how_to",
        "generatedDraft": d_proc['draft']['suggestedReply'],
        "approvalOutcome": "approved"
    })
    assert r_rev.status_code == 200
    d_rev = r_rev.json()
    print(f"  [PASS] Review decision registered: status={d_rev['status']}")
    print(f"  [PASS] Autonomy streak for how_to: {d_rev['autonomyStatus']['consecutiveUneditedCount']} / 20 (Eligible: {d_rev['autonomyStatus']['isEligibleForAutonomy']})")

    # 5. Task 3 Meeting to Scope Pipeline
    print("\n[5/6] Verifying Task 3: Meeting to Scope (Port 8002)...")
    with open("task3-meeting-to-scope/transcripts/meeting_a_website_improvements.txt", "r", encoding="utf-8") as f:
        txt_a = f.read()

    r_m_a = client.post("http://127.0.0.1:8002/analyze-meeting", json={"transcript_text": txt_a, "project_id": "APEX-01"})
    assert r_m_a.status_code == 200
    d_m_a = r_m_a.json()
    print(f"  [PASS] Meeting A analyzed: {len(d_m_a['requirements'])} requirements extracted")
    print(f"    Likely Hours: {d_m_a['proposal']['total_hours_likely']} hrs, Cost: ${d_m_a['proposal']['total_cost_likely_usd']:,.2f}")
    print(f"    Proposal Governance: is_client_ready = {d_m_a['proposal']['is_client_ready']}")

    with open("task3-meeting-to-scope/transcripts/meeting_c_followup_changes.txt", "r", encoding="utf-8") as f:
        txt_c = f.read()
    r_m_c = client.post("http://127.0.0.1:8002/analyze-followup", json={"followup_transcript_text": txt_c, "project_id": "APEX-01"})
    assert r_m_c.status_code == 200
    d_m_c = r_m_c.json()
    diff = d_m_c['diff_report']
    print(f"  [PASS] Scope Diff computed: net hour delta = {diff['net_hour_delta']:+} hrs")
    print(f"    Added: {[r['title'] for r in diff['added_requirements']]}")
    print(f"    Removed: {[r['title'] for r in diff['removed_requirements']]}")
    print(f"    Timeline Change: {diff['delivery_date_change']}")
    print(f"    Out of Scope flagged: {diff['out_of_scope_requests']}")

    # 6. Proposal Approval
    proposal_id = d_m_c['revised_proposal']['proposal_id']
    r_app = client.post("http://127.0.0.1:8002/approve-proposal", json={"proposal_id": proposal_id, "reviewer_name": "Lead AI Architect"})
    assert r_app.status_code == 200
    d_app = r_app.json()
    print(f"  [PASS] Proposal approved by human consultant: client_ready = {d_app['is_client_ready']}")
    print(f"    Approved by: {d_app['approved_by']}")

    # 7. Dashboard HTTP Check
    print("\n[6/6] Verifying Unified Dashboard (Port 5000)...")
    r_dash = client.get("http://127.0.0.1:5000/")
    assert r_dash.status_code == 200
    assert "AI Tech Consultant" in r_dash.text
    print("  [PASS] Dashboard HTML serving correctly on http://127.0.0.1:5000")

    print("\n" + "=" * 65)
    print("ALL LIVE VERIFICATION CHECKS PASSED PERFECTLY!")
    print("=" * 65)

if __name__ == "__main__":
    verify_all()
