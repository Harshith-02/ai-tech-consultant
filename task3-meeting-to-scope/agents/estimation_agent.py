from typing import List
from app.models import Requirement, TaskEstimate

class EstimationAgent:
    def __init__(self):
        pass

    def estimate_tasks(self, requirements: List[Requirement]) -> List[TaskEstimate]:
        estimates: List[TaskEstimate] = []

        for req in requirements:
            t_id = f"TASK-{req.id}"
            
            if req.feasibility_classification == "existing_configuration":
                est = TaskEstimate(
                    task_id=t_id,
                    requirement_id=req.id,
                    task_name=f"Configure & Verify: {req.title}",
                    description=f"Admin configuration and testing for {req.title}. Grounded in: {req.feasibility_evidence}",
                    low_hours=1.5,
                    likely_hours=3.0,
                    high_hours=5.0,
                    assumptions="Platform settings operate as documented without custom database schema overrides.",
                    risks="Minor theme CSS conflicts.",
                    confidence=0.90
                )
            elif req.feasibility_classification == "custom_development":
                est = TaskEstimate(
                    task_id=t_id,
                    requirement_id=req.id,
                    task_name=f"Custom Engineering: {req.title}",
                    description=f"Full lifecycle custom implementation: API webhooks, frontend UI component, testing, and error handling for {req.title}.",
                    low_hours=7.0,
                    likely_hours=11.0,
                    high_hours=16.0,
                    assumptions="Third-party API credentials (e.g. Twilio/Stripe) provided on schedule.",
                    risks="Webhook retry delays, external API rate limiting, cross-browser touch quirks.",
                    confidence=0.75
                )
            elif req.feasibility_classification == "existing_feature_limitation":
                est = TaskEstimate(
                    task_id=t_id,
                    requirement_id=req.id,
                    task_name=f"Feature Adaptation & Customization: {req.title}",
                    description=f"Extend existing core setting with custom widget script for {req.title}.",
                    low_hours=4.0,
                    likely_hours=6.5,
                    high_hours=9.0,
                    assumptions="Base feature hook exists in theme template.",
                    risks="Theme update overwrites.",
                    confidence=0.82
                )
            else:
                est = TaskEstimate(
                    task_id=t_id,
                    requirement_id=req.id,
                    task_name=f"Discovery Spike & Technical Prototype: {req.title}",
                    description=f"Architecture investigation and prototype spike for {req.title}.",
                    low_hours=3.0,
                    likely_hours=5.0,
                    high_hours=8.0,
                    assumptions="Client provides detailed schema requirements.",
                    risks="Unresolved requirements scope creep.",
                    confidence=0.65
                )

            req.estimate_status = "estimated"
            estimates.append(est)

        return estimates

estimation_agent = EstimationAgent()
