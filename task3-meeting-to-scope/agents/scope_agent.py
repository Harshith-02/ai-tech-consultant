from typing import List, Dict, Any
from app.models import Requirement, ScopeOfWork

class ScopeAgent:
    def __init__(self):
        pass

    def build_scope_of_work(
        self,
        project_id: str,
        meta: Dict[str, str],
        requirements: List[Requirement],
        out_of_scope_items: List[Dict[str, str]]
    ) -> ScopeOfWork:
        deliverables = []
        for r in requirements:
            deliverables.append(f"{r.title} — Verified via {r.feasibility_classification}")

        exclusions = [
            "Any custom feature or integration not explicitly enumerated in the approved requirements table.",
            "Third-party external API subscription costs (e.g. Twilio SMS units, Stripe processing fees, Google Maps billing)."
        ]
        for oos in out_of_scope_items:
            exclusions.append(f"EXCLUDED: {oos['item']} ({oos['reason']})")

        client_responsibilities = [
            "Provide administrative access to Brilliant Directories dashboard.",
            "Provision and provide verified third-party API keys (e.g. Twilio Account SID & Auth Token) prior to sprint start.",
            "Designated point of contact available for weekly acceptance reviews.",
            "Formal milestone approval within 3 business days of staging deployment."
        ]

        risks_and_assumptions = [
            "Assumption: Core directory database schema remains unmodified by third-party plugins during development.",
            "Risk: Third-party carrier SMS filtering or geocoding API rate limits.",
            "Risk: Accelerated timeline requires prompt client asset delivery to prevent milestone slippage."
        ]

        exec_summary = (
            f"This Scope of Work defines the technical enhancements for {meta['project_name']} ({meta['client_name']}). "
            f"The engagement prioritizes rapid user discovery, mobile performance optimization, and instant lead conversion, "
            f"targeting production release by {meta['target_delivery_date']}."
        )

        biz_problem = (
            "Current platform search presents unorganized results with excessive clicks, lacking multi-tier filtering "
            "and mobile-optimized category navigation. The proposed scope resolves these friction points using native platform "
            "configurations wherever possible to maximize ROI and minimize development time."
        )

        return ScopeOfWork(
            project_id=project_id,
            project_name=meta["project_name"],
            client_name=meta["client_name"],
            target_delivery_date=meta["target_delivery_date"],
            budget_range=meta["budget_range"],
            executive_summary=exec_summary,
            business_problem=biz_problem,
            requirements=requirements,
            deliverables=deliverables,
            exclusions=exclusions,
            client_responsibilities=client_responsibilities,
            risks_and_assumptions=risks_and_assumptions,
            is_approved=False
        )

scope_agent = ScopeAgent()
