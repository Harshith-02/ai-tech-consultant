from typing import Dict, Any, Optional
from app.models import ScopeOfWork, ProposalDocument, ScopeDiffReport
from agents.transcript_analyst import transcript_analyst
from agents.feasibility_agent import feasibility_agent
from agents.scope_agent import scope_agent
from agents.estimation_agent import estimation_agent
from agents.proposal_agent import proposal_agent
from scope_diff.diff_engine import scope_diff_engine

class MultiAgentOrchestrator:
    def __init__(self):
        pass

    def process_initial_meeting(
        self,
        transcript_text: str,
        project_id: str = "APEX-01"
    ) -> Dict[str, Any]:
        meta, raw_requirements, out_of_scope = transcript_analyst.analyze_transcript(
            transcript_text, project_code=project_id.split("-")[0]
        )
        evaluated_requirements = feasibility_agent.evaluate_all(raw_requirements)
        sow = scope_agent.build_scope_of_work(
            project_id=project_id,
            meta=meta,
            requirements=evaluated_requirements,
            out_of_scope_items=out_of_scope
        )
        estimates = estimation_agent.estimate_tasks(evaluated_requirements)
        proposal = proposal_agent.generate_proposal(sow, estimates)

        return {
            "project_id": project_id,
            "metadata": meta,
            "requirements": evaluated_requirements,
            "out_of_scope_items": out_of_scope,
            "scope_of_work": sow,
            "estimates": estimates,
            "proposal": proposal
        }

    def process_followup_meeting(
        self,
        followup_transcript: str,
        baseline_result: Dict[str, Any],
        project_id: str = "APEX-01"
    ) -> Dict[str, Any]:
        meta_followup, followup_raw_reqs, out_of_scope_new = transcript_analyst.analyze_transcript(
            followup_transcript, project_code=project_id.split("-")[0]
        )
        all_out_of_scope = baseline_result.get("out_of_scope_items", []) + out_of_scope_new
        followup_eval_reqs = feasibility_agent.evaluate_all(followup_raw_reqs)
        followup_estimates = estimation_agent.estimate_tasks(followup_eval_reqs)

        diff_report = scope_diff_engine.compute_diff(
            project_id=project_id,
            baseline_requirements=baseline_result["requirements"],
            followup_requirements=followup_eval_reqs,
            baseline_estimates=baseline_result["estimates"],
            followup_estimates=followup_estimates,
            out_of_scope_items=all_out_of_scope,
            old_delivery_date=baseline_result["metadata"]["target_delivery_date"],
            new_delivery_date=meta_followup["target_delivery_date"]
        )

        revised_sow = scope_agent.build_scope_of_work(
            project_id=project_id,
            meta=meta_followup,
            requirements=followup_eval_reqs,
            out_of_scope_items=all_out_of_scope
        )
        revised_proposal = proposal_agent.generate_proposal(revised_sow, followup_estimates)

        return {
            "project_id": project_id,
            "metadata": meta_followup,
            "requirements": followup_eval_reqs,
            "diff_report": diff_report,
            "revised_scope_of_work": revised_sow,
            "revised_estimates": followup_estimates,
            "revised_proposal": revised_proposal
        }

orchestrator = MultiAgentOrchestrator()
