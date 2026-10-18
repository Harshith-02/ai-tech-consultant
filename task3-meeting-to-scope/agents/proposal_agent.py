import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from app.models import ScopeOfWork, TaskEstimate, ProposalDocument

class ProposalAgent:
    def __init__(self, default_hourly_rate: float = 120.0):
        self.hourly_rate = default_hourly_rate

    def generate_proposal(
        self,
        scope: ScopeOfWork,
        estimates: List[TaskEstimate],
        hourly_rate: Optional[float] = None
    ) -> ProposalDocument:
        rate = hourly_rate or self.hourly_rate
        now = datetime.now(timezone.utc).strftime("%B %d, %Y")

        low_hours = sum(e.low_hours for e in estimates)
        likely_hours = sum(e.likely_hours for e in estimates)
        high_hours = sum(e.high_hours for e in estimates)

        total_cost = round(likely_hours * rate, 2)

        milestones = [
            {
                "milestone": "Milestone 1: Sprint Kickoff & Platform Config",
                "percentage": "40%",
                "amount_usd": round(total_cost * 0.40, 2),
                "deliverables": "Admin settings configuration, category tiers setup, verified badge search filtering."
            },
            {
                "milestone": "Milestone 2: Custom Components & Mobile UX",
                "percentage": "40%",
                "amount_usd": round(total_cost * 0.40, 2),
                "deliverables": "Mobile swipeable pill cards, Twilio SMS webhooks, radius filtering integration."
            },
            {
                "milestone": "Milestone 3: Acceptance Testing & Production Launch",
                "percentage": "20%",
                "amount_usd": round(total_cost * 0.20, 2),
                "deliverables": "Performance benchmarks (< 1.5s mobile search response), client sign-off, live deployment."
            }
        ]

        exec_summary = (
            f"Proposal prepared for {scope.client_name} covering {scope.project_name}. "
            f"Total estimated effort: {likely_hours:.1f} engineering hours (range: {low_hours:.1f}h - {high_hours:.1f}h) "
            f"at ${rate:.2f}/hr, delivering a fixed milestone cost of ${total_cost:,.2f}. "
            f"Target delivery date: {scope.target_delivery_date}."
        )

        proposal_id = f"PROP-{uuid.uuid4().hex[:6].upper()}"

        return ProposalDocument(
            proposal_id=proposal_id,
            project_id=scope.project_id,
            client_name=scope.client_name,
            created_at=now,
            target_delivery_date=scope.target_delivery_date,
            executive_summary=exec_summary,
            scope_of_work=scope,
            task_estimates=estimates,
            hourly_rate_usd=rate,
            total_hours_low=round(low_hours, 1),
            total_hours_likely=round(likely_hours, 1),
            total_hours_high=round(high_hours, 1),
            total_cost_likely_usd=total_cost,
            payment_milestones=milestones,
            is_client_ready=False,
            human_approved=False,
            approved_by=None
        )

    def approve_proposal(self, proposal: ProposalDocument, reviewer_name: str) -> ProposalDocument:
        proposal.human_approved = True
        proposal.is_client_ready = True
        proposal.approved_by = reviewer_name
        proposal.scope_of_work.is_approved = True
        proposal.scope_of_work.approved_by = reviewer_name
        proposal.scope_of_work.approval_timestamp = datetime.now(timezone.utc).isoformat()
        return proposal

proposal_agent = ProposalAgent()
