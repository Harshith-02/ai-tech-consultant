import os
from pathlib import Path
from typing import Dict, Any, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.models import ProposalDocument, ScopeDiffReport
from agents.orchestrator import orchestrator
from agents.proposal_agent import proposal_agent

app = FastAPI(
    title="Meeting to Scope & Proposal API",
    version="1.0.0",
    description="Multi-agent orchestration service that converts client meeting transcripts into verified Scopes of Work, task hour estimates, and client proposals."
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PROJECT_STORE: Dict[str, Any] = {}
PROPOSAL_STORE: Dict[str, ProposalDocument] = {}

class AnalyzeMeetingRequest(BaseModel):
    project_id: str = "APEX-01"
    transcript_text: Optional[str] = None
    transcript_filename: Optional[str] = None

class AnalyzeFollowupRequest(BaseModel):
    project_id: str = "APEX-01"
    followup_transcript_text: Optional[str] = None
    followup_filename: Optional[str] = None

class ApproveProposalRequest(BaseModel):
    proposal_id: str
    reviewer_name: str = "Senior Solutions Architect"

@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "service": "Task 3 - Meeting to Scope (Multi-Agent)",
        "active_projects": len(PROJECT_STORE),
        "proposals_count": len(PROPOSAL_STORE)
    }

@app.get("/transcripts")
async def list_transcripts():
    transcripts_dir = Path(__file__).resolve().parent.parent / "transcripts"
    files = list(transcripts_dir.glob("*.txt"))
    return {
        "total": len(files),
        "transcripts": [
            {
                "filename": f.name,
                "size_bytes": f.stat().st_size,
                "preview": f.read_text(encoding="utf-8")[:250] + "..."
            }
            for f in files
        ]
    }

@app.post("/analyze-meeting")
async def analyze_meeting(request: AnalyzeMeetingRequest):
    trans_text = request.transcript_text
    if not trans_text and request.transcript_filename:
        transcripts_dir = Path(__file__).resolve().parent.parent / "transcripts"
        fpath = transcripts_dir / request.transcript_filename
        if fpath.exists():
            trans_text = fpath.read_text(encoding="utf-8")

    if not trans_text:
        fpath = Path(__file__).resolve().parent.parent / "transcripts" / "meeting_a_website_improvements.txt"
        trans_text = fpath.read_text(encoding="utf-8")

    result = orchestrator.process_initial_meeting(trans_text, project_id=request.project_id)
    PROJECT_STORE[request.project_id] = result
    PROPOSAL_STORE[result["proposal"].proposal_id] = result["proposal"]

    return {
        "project_id": request.project_id,
        "metadata": result["metadata"],
        "requirements_count": len(result["requirements"]),
        "requirements": result["requirements"],
        "out_of_scope_items": result["out_of_scope_items"],
        "scope_of_work": result["scope_of_work"],
        "estimates": result["estimates"],
        "proposal": result["proposal"]
    }

@app.post("/analyze-followup")
async def analyze_followup(request: AnalyzeFollowupRequest):
    baseline = PROJECT_STORE.get(request.project_id)
    if not baseline:
        raise HTTPException(
            status_code=400,
            detail=f"Project {request.project_id} has no baseline meeting. Run /analyze-meeting first."
        )

    trans_text = request.followup_transcript_text
    if not trans_text and request.followup_filename:
        transcripts_dir = Path(__file__).resolve().parent.parent / "transcripts"
        fpath = transcripts_dir / request.followup_filename
        if fpath.exists():
            trans_text = fpath.read_text(encoding="utf-8")

    if not trans_text:
        fpath = Path(__file__).resolve().parent.parent / "transcripts" / "meeting_c_followup_changes.txt"
        trans_text = fpath.read_text(encoding="utf-8")

    diff_result = orchestrator.process_followup_meeting(
        followup_transcript=trans_text,
        baseline_result=baseline,
        project_id=request.project_id
    )

    PROPOSAL_STORE[diff_result["revised_proposal"].proposal_id] = diff_result["revised_proposal"]

    return diff_result

@app.post("/approve-proposal")
async def approve_proposal(request: ApproveProposalRequest):
    prop = PROPOSAL_STORE.get(request.proposal_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Proposal ID not found")

    approved = proposal_agent.approve_proposal(prop, request.reviewer_name)
    PROPOSAL_STORE[request.proposal_id] = approved

    return {
        "status": "approved",
        "proposal_id": approved.proposal_id,
        "is_client_ready": approved.is_client_ready,
        "approved_by": approved.approved_by
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8002, reload=True)
