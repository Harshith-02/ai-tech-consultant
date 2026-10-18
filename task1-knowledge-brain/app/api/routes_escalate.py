from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query
from app.models import EscalationCreateRequest, EscalationResolveRequest, EscalationItem
from retrieval.vector_store import vector_store

router = APIRouter(prefix="/escalations", tags=["Human Escalation & Feedback"])

@router.post("", response_model=dict)
async def create_escalation(request: EscalationCreateRequest):
    esc_id = vector_store.create_escalation(
        question=request.question,
        user_email=request.user_email,
        reason=request.reason
    )
    return {"status": "created", "escalation_id": esc_id}

@router.get("", response_model=List[EscalationItem])
async def list_escalations(status: Optional[str] = Query(None, description="Filter by pending or resolved")):
    items = vector_store.list_escalations(status=status)
    return [EscalationItem(**item) for item in items]

@router.post("/{escalation_id}/resolve", response_model=dict)
async def resolve_escalation(escalation_id: str, request: EscalationResolveRequest):
    success = vector_store.resolve_escalation(
        esc_id=escalation_id,
        expert_answer=request.expert_answer,
        supporting_notes=request.supporting_notes,
        approved_by=request.approved_by
    )
    if not success:
        raise HTTPException(status_code=404, detail="Escalation ID not found")
    return {
        "status": "resolved",
        "escalation_id": escalation_id,
        "indexed_in_knowledge_brain": True
    }
