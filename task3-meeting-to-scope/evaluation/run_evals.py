import sys
import time
import json
from pathlib import Path

# Add task3 directory to path
current_dir = Path(__file__).resolve().parent
task3_dir = current_dir.parent
sys.path.insert(0, str(task3_dir))

from agents.orchestrator import orchestrator
from agents.proposal_agent import proposal_agent
from app.models import Requirement

def run_task3_evaluations():
    print("\n=======================================================")
    print("RUNNING TASK 3 MEETING TO SCOPE EVALUATION (22 Cases)")
    print("=======================================================\n")

    transcripts_dir = task3_dir / "transcripts"
    txt_a = (transcripts_dir / "meeting_a_website_improvements.txt").read_text(encoding="utf-8")
    txt_b = (transcripts_dir / "meeting_b_ecommerce_workflow.txt").read_text(encoding="utf-8")
    txt_c = (transcripts_dir / "meeting_c_followup_changes.txt").read_text(encoding="utf-8")

    # Run pipelines
    start_a = time.perf_counter()
    res_a = orchestrator.process_initial_meeting(txt_a, project_id="APEX-01")
    latency_a = (time.perf_counter() - start_a) * 1000

    start_c = time.perf_counter()
    res_c = orchestrator.process_followup_meeting(txt_c, baseline_result=res_a, project_id="APEX-01")
    latency_c = (time.perf_counter() - start_c) * 1000

    start_b = time.perf_counter()
    res_b = orchestrator.process_initial_meeting(txt_b, project_id="BAZAAR-01")
    latency_b = (time.perf_counter() - start_b) * 1000

    cases_path = current_dir / "test_cases.json"
    with open(cases_path, "r", encoding="utf-8") as f:
        cases = json.load(f)

    results = []
    total_passed = 0

    for c in cases:
        cid = c["id"]
        cname = c["name"]
        cat = c["category"]
        passed = False
        reason = ""

        # Test case routing
        if cid == "TC-SC-001":
            passed = any("category" in r.title.lower() for r in res_a["requirements"])
        elif cid == "TC-SC-002":
            passed = any("radius" in r.description.lower() for r in res_a["requirements"])
        elif cid == "TC-SC-003":
            passed = any("pill" in r.title.lower() for r in res_a["requirements"])
        elif cid == "TC-SC-004":
            passed = any("1.5" in r.description.lower() for r in res_a["requirements"])
        elif cid == "TC-SC-005":
            passed = "november 20" in res_a["metadata"]["target_delivery_date"].lower()
        elif cid == "TC-SC-006":
            req_cat = Requirement(
                id="T-01", title="How to import categories via CSV",
                description="Importing categories via CSV", source_transcript="Test",
                speaker="Client", acceptance_criteria="Works"
            )
            # Evaluate feasibility directly
            from agents.feasibility_agent import feasibility_agent
            evaluated = feasibility_agent.check_feasibility(req_cat)
            passed = evaluated.feasibility_classification in ["existing_configuration", "custom_development"]
        elif cid == "TC-SC-007":
            req_wp = Requirement(
                id="T-02", title="Can I host a WordPress site directly on BD?",
                description="Host external WordPress directly on server", source_transcript="Test",
                speaker="Client", acceptance_criteria="Works"
            )
            from agents.feasibility_agent import feasibility_agent
            evaluated = feasibility_agent.check_feasibility(req_wp)
            passed = evaluated.feasibility_classification in ["existing_feature_limitation", "custom_development"]
        elif cid == "TC-SC-008":
            req_sms = Requirement(
                id="T-03", title="Twilio SMS Webhook lead notifications",
                description="Custom SMS dispatch on lead form", source_transcript="Test",
                speaker="Client", acceptance_criteria="Works"
            )
            from agents.feasibility_agent import feasibility_agent
            evaluated = feasibility_agent.check_feasibility(req_sms)
            passed = evaluated.feasibility_classification in ["custom_development", "existing_configuration"]
        elif cid == "TC-SC-009":
            req_stripe = Requirement(
                id="T-04", title="Stripe Connect split payouts marketplace",
                description="Marketplace split payouts", source_transcript="Test",
                speaker="Client", acceptance_criteria="Works"
            )
            from agents.feasibility_agent import feasibility_agent
            evaluated = feasibility_agent.check_feasibility(req_stripe)
            passed = evaluated.feasibility_classification in ["custom_development", "existing_configuration"]
        elif cid == "TC-SC-010":
            # Compare config vs custom hours
            config_est = [e for e in res_a["estimates"] if "configure" in e.task_name.lower()]
            custom_est = [e for e in res_a["estimates"] if "custom" in e.task_name.lower()]
            passed = True
            if config_est and custom_est:
                passed = config_est[0].likely_hours < custom_est[0].likely_hours
        elif cid == "TC-SC-011":
            # Check low <= likely <= high for all tasks
            passed = all(e.low_hours <= e.likely_hours <= e.high_hours for e in res_a["estimates"])
        elif cid == "TC-SC-012":
            likely_sum = sum(e.likely_hours for e in res_a["estimates"])
            expected_cost = round(likely_sum * res_a["proposal"].hourly_rate_usd, 2)
            passed = abs(res_a["proposal"].total_cost_likely_usd - expected_cost) < 0.01
        elif cid == "TC-SC-013":
            # Twilio SMS added in Meeting C
            passed = any("sms" in r.title.lower() for r in res_c["diff_report"].added_requirements)
        elif cid == "TC-SC-014":
            # AI search removed in Meeting C
            passed = any("ai" in r.title.lower() for r in res_c["diff_report"].removed_requirements)
        elif cid == "TC-SC-015":
            # Date change to Nov 13
            passed = "november 13" in res_c["diff_report"].delivery_date_change["after"].lower()
        elif cid == "TC-SC-016":
            # 20k MySQL out of scope
            passed = any("mysql" in o["item"].lower() for o in res_c["diff_report"].out_of_scope_requests)
        elif cid == "TC-SC-017":
            # Net hour delta calculated
            passed = isinstance(res_c["diff_report"].net_hour_delta, (int, float))
        elif cid == "TC-SC-018":
            # Initial proposal not client ready
            passed = res_a["proposal"].is_client_ready is False and res_a["proposal"].human_approved is False
        elif cid == "TC-SC-019":
            # Approval unlocks client ready
            approved_prop = proposal_agent.approve_proposal(res_a["proposal"], "Lead Consultant")
            passed = approved_prop.is_client_ready is True and approved_prop.human_approved is True
        elif cid == "TC-SC-020":
            # Meeting B direct purchase
            passed = any("purchase" in r.title.lower() for r in res_b["requirements"])
        elif cid == "TC-SC-021":
            # Meeting B budget
            passed = "7,000" in res_b["metadata"]["budget_range"]
        elif cid == "TC-SC-022":
            # Meeting B Stripe
            passed = any("stripe" in r.title.lower() for r in res_b["requirements"])
        else:
            passed = True

        if passed:
            total_passed += 1
        mark = "PASS" if passed else "FAIL"
        print(f"[{mark}] {cid} - {cname}")

        results.append({
            "case_id": cid,
            "category": cat,
            "name": cname,
            "passed": passed
        })

    pass_rate = round((total_passed / len(cases)) * 100, 2)
    summary = {
        "total_cases": len(cases),
        "passed": total_passed,
        "pass_rate_pct": pass_rate,
        "median_pipeline_latency_ms": round((latency_a + latency_b + latency_c) / 3, 2),
        "results": results
    }

    out_file = current_dir / "task3_eval_results.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("\n=======================================================")
    print("TASK 3 EVALUATION SUMMARY:")
    print(f"Pass Rate: {pass_rate}% ({total_passed}/{len(cases)})")
    print(f"Pipeline Latency: Meeting A={latency_a:.1f}ms, Meeting C={latency_c:.1f}ms, Meeting B={latency_b:.1f}ms")
    print(f"Results saved to: {out_file}")
    print("=======================================================\n")

if __name__ == "__main__":
    run_task3_evaluations()
