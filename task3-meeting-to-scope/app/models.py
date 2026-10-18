from typing import List, Dict, Any, Optional, Literal
from pydantic import BaseModel, Field

class Requirement(BaseModel):
    id: str = Field(..., description="Unique requirement ID, e.g. REQ-001")
    title: str = Field(..., description="Short requirement title")
    description: str = Field(..., description="Detailed specification of the requirement")
    source_transcript: str = Field(..., description="Meeting transcript passage and timestamp")
    speaker: str = Field(..., description="Client or consultant who stated it")
    status: Literal["confirmed", "unclear", "disputed"] = Field("confirmed")
    priority: Literal["must_have", "should_have", "nice_to_have"] = Field("must_have")
    feasibility_classification: Literal[
        "existing_configuration",
        "existing_feature_limitation",
        "custom_development",
        "needs_clarification"
    ] = Field("needs_clarification")
    feasibility_evidence: str = Field("", description="Knowledge Brain evidence supporting classification")
    acceptance_criteria: str = Field(..., description="Verifiable test criterion for completion")
    dependencies: List[str] = Field(default_factory=list)
    estimate_status: Literal["not_estimated", "estimated", "needs_review"] = Field("not_estimated")

class TaskEstimate(BaseModel):
    task_id: str
    requirement_id: str
    task_name: str
    description: str
    low_hours: float
    likely_hours: float
    high_hours: float
    assumptions: str
    risks: str
    confidence: float

class ScopeOfWork(BaseModel):
    project_id: str
    project_name: str
    client_name: str
    target_delivery_date: str
    budget_range: str
    executive_summary: str
    business_problem: str
    requirements: List[Requirement]
    deliverables: List[str]
    exclusions: List[str]
    client_responsibilities: List[str]
    risks_and_assumptions: List[str]
    is_approved: bool = False
    approved_by: Optional[str] = None
    approval_timestamp: Optional[str] = None

class ScopeDiffReport(BaseModel):
    project_id: str
    previous_meeting: str
    followup_meeting: str
    added_requirements: List[Requirement]
    modified_requirements: List[Dict[str, Any]]
    removed_requirements: List[Requirement]
    out_of_scope_requests: List[Dict[str, str]]
    delivery_date_change: Dict[str, str]
    net_hour_delta: float
    summary_notes: str

class ProposalDocument(BaseModel):
    proposal_id: str
    project_id: str
    client_name: str
    created_at: str
    target_delivery_date: str
    executive_summary: str
    scope_of_work: ScopeOfWork
    task_estimates: List[TaskEstimate]
    hourly_rate_usd: float = 120.0
    total_hours_low: float
    total_hours_likely: float
    total_hours_high: float
    total_cost_likely_usd: float
    payment_milestones: List[Dict[str, Any]]
    is_client_ready: bool = False
    human_approved: bool = False
    approved_by: Optional[str] = None
