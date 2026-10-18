import sys
import time
import json
from pathlib import Path
from typing import List, Dict, Any

# Ensure task1 root is in python path
current_dir = Path(__file__).resolve().parent
task1_dir = current_dir.parent
sys.path.insert(0, str(task1_dir))

from retrieval.qa_engine import qa_engine

def run_evaluations(test_cases_path: Path = current_dir / "test_cases.json") -> Dict[str, Any]:
    with open(test_cases_path, "r", encoding="utf-8") as f:
        cases = json.load(f)

    results = []
    total_passed = 0
    total_citations_valid = 0
    total_abstention_correct = 0
    total_abstention_cases = 0
    latencies = []

    print(f"\n=======================================================")
    print(f"RUNNING TASK 1 KNOWLEDGE BRAIN EVALUATION ({len(cases)} Cases)")
    print(f"=======================================================\n")

    for c in cases:
        cid = c["id"]
        q = c["question"]
        expected_status = c["expected_status"]
        expected_keywords = c.get("expected_keywords", [])
        requires_screenshot = c.get("requires_screenshot", False)

        start_time = time.perf_counter()
        resp = qa_engine.generate_answer(q)
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        latencies.append(duration_ms)

        # Check status match
        status_match = (resp.status == expected_status)
        
        # Check keyword coverage if answered
        keyword_hits = 0
        if expected_status == "answered" and expected_keywords:
            ans_lower = resp.answer.lower()
            keyword_hits = sum(1 for kw in expected_keywords if kw.lower() in ans_lower)
            keywords_passed = keyword_hits >= max(1, len(expected_keywords) // 2)
        else:
            keywords_passed = True

        # Check citations
        citations_present = len(resp.sources) > 0 if expected_status == "answered" else True
        if citations_present and resp.sources:
            total_citations_valid += 1

        # Check screenshot reference
        screenshot_ok = True
        if requires_screenshot and resp.sources:
            screenshot_ok = any(s.image_url is not None for s in resp.sources)

        # Check abstention
        if expected_status == "insufficient_evidence":
            total_abstention_cases += 1
            if resp.status == "insufficient_evidence" and resp.needs_human is True:
                total_abstention_correct += 1

        passed = status_match and keywords_passed and citations_present and screenshot_ok
        if passed:
            total_passed += 1
        
        failure_reason = ""
        if not status_match:
            failure_reason = f"Status mismatch: expected {expected_status}, got {resp.status}"
        elif not keywords_passed:
            failure_reason = f"Low keyword coverage: {keyword_hits}/{len(expected_keywords)}"
        elif not citations_present:
            failure_reason = "Missing source citations"
        elif not screenshot_ok:
            failure_reason = "Expected screenshot not attached"

        # Model cost estimation (~400 input tokens, ~150 output tokens on Haiku/extractive)
        est_cost_usd = 0.00015

        res_record = {
            "case_id": cid,
            "category": c["category"],
            "question": q,
            "expected_status": expected_status,
            "actual_status": resp.status,
            "confidence": resp.confidence,
            "citations_count": len(resp.sources),
            "latency_ms": duration_ms,
            "cost_usd": est_cost_usd,
            "passed": passed,
            "failure_reason": failure_reason
        }
        results.append(res_record)

        mark = "PASS" if passed else "FAIL"
        print(f"[{mark}] {cid} ({duration_ms}ms, conf={resp.confidence}) - {q[:45]}...")
        if not passed:
            print(f"       Reason: {failure_reason}")

    latencies.sort()
    median_latency = latencies[len(latencies) // 2]
    p95_latency = latencies[int(len(latencies) * 0.95)]
    pass_rate = round((total_passed / len(cases)) * 100, 2)
    abstention_rate = round((total_abstention_correct / total_abstention_cases) * 100, 2) if total_abstention_cases else 100.0

    summary = {
        "total_cases": len(cases),
        "passed": total_passed,
        "pass_rate_pct": pass_rate,
        "abstention_correctness_pct": abstention_rate,
        "median_latency_ms": median_latency,
        "p95_latency_ms": p95_latency,
        "avg_cost_per_query_usd": 0.00015,
        "results": results
    }

    out_file = current_dir / "task1_eval_results.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(f"\n=======================================================")
    print(f"TASK 1 EVALUATION SUMMARY:")
    print(f"Pass Rate: {pass_rate}% ({total_passed}/{len(cases)})")
    print(f"Abstention Precision: {abstention_rate}%")
    print(f"Median Latency: {median_latency} ms | P95 Latency: {p95_latency} ms")
    print(f"Results saved to: {out_file}")
    print(f"=======================================================\n")

    return summary

if __name__ == "__main__":
    run_evaluations()
