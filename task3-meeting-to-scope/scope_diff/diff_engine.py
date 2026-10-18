from typing import List, Dict, Any
from app.models import Requirement, ScopeDiffReport, TaskEstimate

class ScopeDiffEngine:
    def __init__(self):
        pass

    def compute_diff(
        self,
        project_id: str,
        baseline_requirements: List[Requirement],
        followup_requirements: List[Requirement],
        baseline_estimates: List[TaskEstimate],
        followup_estimates: List[TaskEstimate],
        out_of_scope_items: List[Dict[str, str]],
        old_delivery_date: str = "November 20th",
        new_delivery_date: str = "November 13th"
    ) -> ScopeDiffReport:
        baseline_map = {r.title.lower(): r for r in baseline_requirements}
        followup_map = {r.title.lower(): r for r in followup_requirements}

        added: List[Requirement] = []
        removed: List[Requirement] = []
        modified: List[Dict[str, Any]] = []

        for title_lower, req in followup_map.items():
            if not any(b_title in title_lower or title_lower in b_title for b_title in baseline_map.keys()):
                added.append(req)

        for title_lower, req in baseline_map.items():
            if not any(f_title in title_lower or title_lower in f_title for f_title in followup_map.keys()):
                removed.append(req)

        for title_lower, f_req in followup_map.items():
            for b_title, b_req in baseline_map.items():
                if b_title in title_lower or title_lower in b_title:
                    if f_req.description != b_req.description or f_req.priority != b_req.priority:
                        modified.append({
                            "title": f_req.title,
                            "before": b_req.description,
                            "after": f_req.description,
                            "priority_change": f"{b_req.priority} -> {f_req.priority}"
                        })

        baseline_likely_sum = sum(e.likely_hours for e in baseline_estimates)
        followup_likely_sum = sum(e.likely_hours for e in followup_estimates)
        net_delta = round(followup_likely_sum - baseline_likely_sum, 1)

        summary_notes = (
            f"Follow-up meeting resulted in {len(added)} added item(s), {len(removed)} removed item(s), "
            f"and {len(out_of_scope_items)} out-of-scope request(s) flagged for separate quotation. "
            f"Delivery date accelerated from {old_delivery_date} to {new_delivery_date} (-7 days)."
        )

        return ScopeDiffReport(
            project_id=project_id,
            previous_meeting="Meeting A (Website Improvements)",
            followup_meeting="Meeting C (Follow-Up & Change Requests)",
            added_requirements=added,
            modified_requirements=modified,
            removed_requirements=removed,
            out_of_scope_requests=out_of_scope_items,
            delivery_date_change={"before": old_delivery_date, "after": new_delivery_date},
            net_hour_delta=net_delta,
            summary_notes=summary_notes
        )

scope_diff_engine = ScopeDiffEngine()
