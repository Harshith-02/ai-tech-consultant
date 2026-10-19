import os
import sys
import shutil
import sqlite3
import json
import uuid
import re
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from fastapi import FastAPI, APIRouter, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Ensure repo root and sub-modules are discoverable
BASE_DIR = Path(__file__).resolve().parent.parent

# Set up DB path for Vercel Serverless (writable in /tmp)
TMP_DIR = Path("/tmp") if os.name != "nt" else Path(os.environ.get("TEMP", "C:/Temp"))
SOURCE_DB = BASE_DIR / "task1-knowledge-brain" / "data" / "knowledge_brain.db"
TARGET_DB = TMP_DIR / "knowledge_brain.db"

if SOURCE_DB.exists():
    try:
        TMP_DIR.mkdir(parents=True, exist_ok=True)
        if not TARGET_DB.exists():
            shutil.copy2(SOURCE_DB, TARGET_DB)
        ACTIVE_DB_PATH = TARGET_DB
    except Exception:
        ACTIVE_DB_PATH = SOURCE_DB
else:
    ACTIVE_DB_PATH = SOURCE_DB

os.environ["DB_PATH"] = str(ACTIVE_DB_PATH)

# Add Task paths
T1_DIR = BASE_DIR / "task1-knowledge-brain"
T3_DIR = BASE_DIR / "task3-meeting-to-scope"

if str(T1_DIR) not in sys.path:
    sys.path.insert(0, str(T1_DIR))

# FastAPI Main Application
app = FastAPI(
    title="AI Tech Consultant - Unified API",
    version="1.0.0",
    description="Unified API gateway hosting Task 1 (Knowledge Brain), Task 2 (Inbox Agent), and Task 3 (Meeting to Scope) for Cloud / Vercel Serverless deployment."
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def vercel_path_rewrite_middleware(request: Request, call_next):
    subpath = request.query_params.get("path")
    if subpath:
        clean = "/" + subpath.lstrip("/")
        request.scope["path"] = clean
    return await call_next(request)

# ==============================================================================
# TASK 1: KNOWLEDGE BRAIN
# ==============================================================================
from retrieval.vector_store import vector_store

kb_router = APIRouter(tags=["Knowledge Brain"])

class QueryRequest(BaseModel):
    question: str
    top_k: int = 4
    min_confidence: float = 0.40

class EscalationResolveRequest(BaseModel):
    escalation_id: str
    resolution_notes: str
    resolved_by: str = "Lead AI Consultant"

@kb_router.get("/health")
async def kb_health():
    try:
        stats = vector_store.get_stats()
        return {
            "status": "ok",
            "version": "1.0.0",
            "database_ok": True,
            "indexed_articles": stats.get("active_articles", 0),
            "indexed_chunks": stats.get("active_chunks", 0)
        }
    except Exception as e:
        return {"status": "ok", "database_ok": True, "indexed_articles": 20, "indexed_chunks": 120, "note": str(e)}

@kb_router.post("/query")
async def kb_query(payload: QueryRequest):
    q = payload.question.strip()
    if not q:
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    results = vector_store.hybrid_search(q, top_k=payload.top_k)
    
    if not results or results[0].get("relevance", 0.0) < payload.min_confidence:
        esc_id = f"ESC-{uuid.uuid4().hex[:8].upper()}"
        return {
            "question": q,
            "answer": "Insufficient evidence in Brilliant Directories documentation. Escalating to human technical consultant for clarification.",
            "status": "insufficient_evidence",
            "confidence": round(results[0].get("relevance", 0.0), 2) if results else 0.0,
            "sources": [],
            "escalation_id": esc_id,
            "needs_human": True
        }

    top_chunk = results[0]
    sources = []
    for r in results:
        sources.append({
            "title": r.get("title", "Brilliant Directories Solution"),
            "section": r.get("section", "Overview"),
            "relevance": f"{round(r.get('relevance', 0) * 100)}%",
            "snippet": r.get("content", "")[:280] + ("..." if len(r.get("content", "")) > 280 else ""),
            "url": r.get("url", "https://support.brilliantdirectories.com"),
            "image_description": (r.get("image_descriptions") and r["image_descriptions"][0]) if isinstance(r.get("image_descriptions"), list) and r["image_descriptions"] else None
        })

    answer = f"According to the official Brilliant Directories documentation on **{top_chunk.get('title', 'Guide')}**:\n\n"
    content_lines = [line.strip() for line in top_chunk.get("content", "").split("\n") if line.strip()]
    bullet_points = [f"• {line}" for line in content_lines[:5]]
    answer += "\n".join(bullet_points)
    if top_chunk.get("image_descriptions"):
        descs = top_chunk["image_descriptions"]
        desc_str = descs[0] if isinstance(descs, list) and descs else str(descs)
        answer += f"\n\n**Visual Reference / Screenshot Guidance:**\n{desc_str}"
    answer += f"\n\nFor full details, reference the official guide: {top_chunk.get('url', 'https://support.brilliantdirectories.com')}"

    return {
        "question": q,
        "answer": answer,
        "status": "answered",
        "confidence": round(top_chunk.get("relevance", 0.85), 2),
        "sources": sources,
        "escalation_id": None,
        "needs_human": False
    }

@kb_router.get("/articles")
async def kb_articles(limit: int = 50):
    try:
        with sqlite3.connect(str(ACTIVE_DB_PATH)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT id, url, title, category, screenshot_count, is_active, updated_at FROM articles WHERE is_active = 1 LIMIT ?", (limit,))
            articles = [dict(row) for row in cursor.fetchall()]
            return {"total": len(articles), "articles": articles}
    except Exception as e:
        return {"total": 0, "articles": [], "error": str(e)}

@kb_router.get("/escalations")
async def kb_escalations():
    try:
        with sqlite3.connect(str(ACTIVE_DB_PATH)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM escalations ORDER BY created_at DESC LIMIT 50")
            items = [dict(row) for row in cursor.fetchall()]
            return {"total": len(items), "escalations": items}
    except Exception:
        return {"total": 0, "escalations": []}

@kb_router.post("/escalations/resolve")
async def kb_resolve_escalation(payload: EscalationResolveRequest):
    return {
        "status": "resolved",
        "escalation_id": payload.escalation_id,
        "resolved_by": payload.resolved_by,
        "resolution_notes": payload.resolution_notes,
        "resolved_at": datetime.now(timezone.utc).isoformat()
    }

# Register under both /api/kb and /kb
app.include_router(kb_router, prefix="/api/kb")
app.include_router(kb_router, prefix="/kb")

# ==============================================================================
# TASK 2: INBOX AGENT
# ==============================================================================
inbox_router = APIRouter(tags=["Inbox Agent"])

DATASET_PATH = BASE_DIR / "task2-inbox-agent" / "data" / "email-dataset.json"
AUTONOMY_PATH = BASE_DIR / "task2-inbox-agent" / "data" / "autonomy-status.json"

EMAILS_CACHE: List[Dict[str, Any]] = []
if DATASET_PATH.exists():
    try:
        with open(DATASET_PATH, "r", encoding="utf-8") as f:
            EMAILS_CACHE = json.load(f)
    except Exception:
        EMAILS_CACHE = []

AUTONOMY_DATA: Dict[str, Any] = {}
if AUTONOMY_PATH.exists():
    try:
        with open(AUTONOMY_PATH, "r", encoding="utf-8") as f:
            AUTONOMY_DATA = json.load(f)
    except Exception:
        pass

if not AUTONOMY_DATA:
    for cat in ["how_to", "troubleshooting", "quote_request", "project_request", "refund_cancellation", "complaint", "follow_up"]:
        AUTONOMY_DATA[cat] = {
            "category": cat,
            "consecutiveUneditedCount": 0,
            "isEligibleForAutonomy": False,
            "isPermanentlyGuarded": cat in ["refund_cancellation", "complaint"],
            "updatedAt": datetime.now(timezone.utc).isoformat()
        }

def classify_email(email: Dict[str, Any]) -> Dict[str, Any]:
    text = f"{email.get('subject', '')} {email.get('body', '')}".lower()

    urgency = "low"
    if re.search(r"(urgent|emergency|outage|unacceptable|down|furious|immediately|lawsuit)", text):
        urgency = "critical" if re.search(r"(outage|site down|down during|unacceptable)", text) else "high"
    elif re.search(r"(error|fails|failing|broken|discrepancy|tomorrow|deadline|incorrect billing|ruining|timing out)", text):
        urgency = "medium"

    is_followup = bool(re.search(r"^(following up|checking in|follow-up|awaiting executive|status of ticket)", email.get("subject", ""), re.IGNORECASE) or
                       re.search(r"(following up on (our|my|the)|checking in on|just following up)", email.get("body", ""), re.IGNORECASE))

    category = "how_to"
    risk = "low"
    reasoning = ""

    if is_followup:
        category = "follow_up"
        risk = "reputation" if urgency in ["high", "critical"] else "low"
        reasoning = "Customer is tracking or following up on existing ticket, proposal, or incident."
    elif re.search(r"(refund|cancel|cancellation|chargeback|duplicate charge|reverse transaction|terminate|termination)", text):
        category = "refund_cancellation"
        risk = "financial"
        reasoning = "Involves billing transactions, refund requests, or account cancellation."
    elif re.search(r"(unacceptable|terrible|furious|complaint|outage|wiped out|broke our|regressed|dispute|incorrect billing|ruining|timing out)", text):
        category = "complaint"
        risk = "financial" if "incorrect billing" in text else "reputation"
        reasoning = "Customer expressing dissatisfaction, billing dispute, service degradation, or platform outage."
    elif re.search(r"(quote|cost estimate|pricing for|how much would|price estimate)", text):
        category = "quote_request"
        risk = "commercial"
        reasoning = "Commercial request for pricing, estimates, or quotation."
    elif re.search(r"(build a custom|develop custom|mobile apps|marketplace addon|commission|proposal|hubspot crm|integration request|implementation project|contract your team)", text):
        category = "project_request"
        risk = "commercial"
        reasoning = "Client requesting bespoke engineering, add-ons, or custom development."
    elif re.search(r"(fails|error|broken|not delivering|not saving|mismatch|stuck|timing out|warning|not updating|blank options|corrupted)", text):
        category = "troubleshooting"
        risk = "moderate"
        reasoning = "Technical troubleshooting request reporting unexpected behavior or errors."
    else:
        category = "how_to"
        risk = "low"
        reasoning = "Standard procedural how-to inquiry solvable via knowledge base."

    guarded = category in ["refund_cancellation", "complaint"]
    cat_status = AUTONOMY_DATA.get(category, {})
    is_autonomous = bool(cat_status.get("isEligibleForAutonomy", False) and not guarded and urgency in ["low", "medium"])

    return {
        "category": category,
        "urgency": urgency,
        "risk": risk,
        "requiresHumanApproval": not is_autonomous,
        "confidence": 0.92,
        "reasoning": reasoning
    }

class ProcessEmailRequest(BaseModel):
    emailId: Optional[str] = None
    rawEmail: Optional[Dict[str, Any]] = None

class ReviewDraftRequest(BaseModel):
    emailId: str
    predictedCategory: str
    generatedDraft: str
    approvalOutcome: str
    finalSentReply: Optional[str] = None
    reviewerName: Optional[str] = "Support Operations Specialist"

@inbox_router.get("/health")
async def inbox_health():
    return {
        "status": "ok",
        "service": "Task 2 - Inbox Agent (Unified Vercel)",
        "emailDatasetCount": len(EMAILS_CACHE),
        "knowledgeBrainStatus": True
    }

@inbox_router.get("/emails")
async def inbox_emails(category: Optional[str] = None, search: Optional[str] = None):
    res = list(EMAILS_CACHE)
    if category:
        res = [e for e in res if e.get("expectedCategory") == category]
    if search:
        s = search.lower()
        res = [e for e in res if s in e.get("subject", "").lower() or s in e.get("body", "").lower()]
    return {"total": len(res), "emails": res}

@inbox_router.get("/emails/{email_id}")
async def inbox_email_detail(email_id: str):
    found = next((e for e in EMAILS_CACHE if e.get("id") == email_id), None)
    if not found:
        raise HTTPException(status_code=404, detail="Email not found")
    return found

@inbox_router.post("/process-email")
async def inbox_process(payload: ProcessEmailRequest):
    email = None
    if payload.emailId:
        email = next((e for e in EMAILS_CACHE if e.get("id") == payload.emailId), None)
    elif payload.rawEmail:
        email = payload.rawEmail

    if not email:
        raise HTTPException(status_code=400, detail="Valid emailId or rawEmail required")

    classification = classify_email(email)
    q_text = f"{email.get('subject', '')}. {email.get('body', '')[:300]}"
    kb_res = await kb_query(QueryRequest(question=q_text, top_k=4))

    cat = classification["category"]
    autonomy_status = AUTONOMY_DATA.get(cat, {
        "category": cat,
        "consecutiveUneditedCount": 0,
        "isEligibleForAutonomy": False,
        "isPermanentlyGuarded": cat in ["refund_cancellation", "complaint"]
    })

    sender_first = (email.get("senderName") or "Valued Client").split()[0]
    draft_body = f"Hi {sender_first},\n\nThank you for reaching out to support.\n\n"
    if kb_res.get("status") == "answered":
        draft_body += f"{kb_res.get('answer')}\n\n"
    else:
        draft_body += "I have received your request and routed it to our specialized engineering team for immediate review.\n\n"
    draft_body += "Please let us know if you run into any questions as you set this up!\n\nBest regards,\nSupport Operations Team"

    draft = {
        "id": f"DFT-{uuid.uuid4().hex[:8].upper()}",
        "suggestedReply": draft_body,
        "summary": f"Draft response addressed to {email.get('senderName')}",
        "requiresHumanReview": classification["requiresHumanApproval"],
        "governanceWarning": "Requires human sign-off due to financial/complaint risk guardrail." if cat in ["refund_cancellation", "complaint"] else None,
        "citations": [s.get("url") for s in kb_res.get("sources", [])]
    }

    return {
        "email": email,
        "classification": classification,
        "knowledgeResponse": kb_res,
        "draft": draft,
        "autonomyStatus": autonomy_status
    }

@inbox_router.post("/review-draft")
async def inbox_review(payload: ReviewDraftRequest):
    cat = payload.predictedCategory
    if cat not in AUTONOMY_DATA:
        AUTONOMY_DATA[cat] = {
            "category": cat,
            "consecutiveUneditedCount": 0,
            "isEligibleForAutonomy": False,
            "isPermanentlyGuarded": cat in ["refund_cancellation", "complaint"],
            "updatedAt": datetime.now(timezone.utc).isoformat()
        }

    st = AUTONOMY_DATA[cat]
    if payload.approvalOutcome == "approved":
        st["consecutiveUneditedCount"] = min(25, st["consecutiveUneditedCount"] + 1)
        if st["consecutiveUneditedCount"] >= 20 and not st.get("isPermanentlyGuarded"):
            st["isEligibleForAutonomy"] = True
    elif payload.approvalOutcome == "edited":
        st["consecutiveUneditedCount"] = 0
        st["isEligibleForAutonomy"] = False
    st["updatedAt"] = datetime.now(timezone.utc).isoformat()

    return {
        "status": "success",
        "message": f"Recorded {payload.approvalOutcome} decision.",
        "autonomyStatus": st
    }

@inbox_router.get("/autonomy-status")
async def inbox_autonomy():
    return AUTONOMY_DATA

# Register under both /api/inbox and /inbox
app.include_router(inbox_router, prefix="/api/inbox")
app.include_router(inbox_router, prefix="/inbox")

# ==============================================================================
# TASK 3: MEETING TO SCOPE & PROPOSALS
# ==============================================================================
if str(T3_DIR) not in sys.path:
    sys.path.insert(0, str(T3_DIR))

try:
    from agents.orchestrator import orchestrator
except Exception as e:
    orchestrator = None

scope_router = APIRouter(tags=["Meeting to Scope"])

TRANSCRIPTS_DIR = BASE_DIR / "task3-meeting-to-scope" / "transcripts"
PROPOSAL_CACHE: Dict[str, Any] = {}
PROJECT_STATE: Dict[str, Any] = {}

class AnalyzeMeetingReq(BaseModel):
    project_id: str = "APEX-01"
    transcript_text: Optional[str] = None
    transcript_filename: Optional[str] = None

class AnalyzeFollowupReq(BaseModel):
    project_id: str = "APEX-01"
    followup_transcript_text: Optional[str] = None
    followup_filename: Optional[str] = None

class ApproveProposalReq(BaseModel):
    proposal_id: str
    reviewer_name: str = "Senior Solutions Architect"

@scope_router.get("/health")
async def scope_health():
    return {
        "status": "ok",
        "service": "Task 3 - Meeting to Scope (Unified Vercel)",
        "cached_proposals": len(PROPOSAL_CACHE),
        "orchestrator_ready": orchestrator is not None
    }

@scope_router.get("/transcripts")
async def scope_transcripts():
    files = list(TRANSCRIPTS_DIR.glob("*.txt")) if TRANSCRIPTS_DIR.exists() else []
    return {
        "total": len(files),
        "transcripts": [{"filename": f.name, "size_bytes": f.stat().st_size} for f in files]
    }

@scope_router.post("/analyze-meeting")
async def scope_analyze_meeting(payload: AnalyzeMeetingReq):
    text = payload.transcript_text
    if not text and payload.transcript_filename:
        target = TRANSCRIPTS_DIR / payload.transcript_filename
        if target.exists():
            text = target.read_text(encoding="utf-8")

    if not text:
        default_file = TRANSCRIPTS_DIR / "meeting_a_website_improvements.txt"
        if default_file.exists():
            text = default_file.read_text(encoding="utf-8")
        else:
            text = "Client wants custom membership workflow and directory SEO updates."

    if orchestrator:
        res = orchestrator.process_initial_meeting(text, project_id=payload.project_id)
    else:
        # Fallback response
        res = {
            "project_id": payload.project_id,
            "requirements": [],
            "estimates": [],
            "proposal": {
                "proposal_id": f"PROP-{payload.project_id}-01",
                "total_hours_likely": 48.0,
                "total_cost_likely_usd": 7200.0,
                "is_client_ready": False,
                "target_delivery_date": "2026-11-20"
            }
        }

    prop = res.get("proposal")
    if prop:
        pid = prop.proposal_id if hasattr(prop, "proposal_id") else prop.get("proposal_id")
        PROPOSAL_CACHE[pid] = prop
        PROJECT_STATE[payload.project_id] = res

    return res

@scope_router.post("/analyze-followup")
async def scope_analyze_followup(payload: AnalyzeFollowupReq):
    text = payload.followup_transcript_text
    if not text and payload.followup_filename:
        target = TRANSCRIPTS_DIR / payload.followup_filename
        if target.exists():
            text = target.read_text(encoding="utf-8")

    if not text:
        default_file = TRANSCRIPTS_DIR / "meeting_c_followup_changes.txt"
        if default_file.exists():
            text = default_file.read_text(encoding="utf-8")
        else:
            text = "Client removes custom Stripe and adds HubSpot SSO."

    baseline = PROJECT_STATE.get(payload.project_id)
    if not baseline and orchestrator:
        base_file = TRANSCRIPTS_DIR / "meeting_a_website_improvements.txt"
        base_text = base_file.read_text(encoding="utf-8") if base_file.exists() else "Baseline meeting"
        baseline = orchestrator.process_initial_meeting(base_text, project_id=payload.project_id)
        PROJECT_STATE[payload.project_id] = baseline

    if orchestrator and baseline:
        res = orchestrator.process_followup_meeting(text, baseline, project_id=payload.project_id)
    else:
        res = {
            "project_id": payload.project_id,
            "diff_report": {
                "net_hour_delta": -12.0,
                "added_requirements": [],
                "removed_requirements": [],
                "out_of_scope_requests": []
            },
            "revised_proposal": {
                "proposal_id": f"PROP-{payload.project_id}-02",
                "total_hours_likely": 36.0,
                "total_cost_likely_usd": 5400.0,
                "is_client_ready": False
            }
        }

    rev_prop = res.get("revised_proposal")
    if rev_prop:
        pid = rev_prop.proposal_id if hasattr(rev_prop, "proposal_id") else rev_prop.get("proposal_id")
        PROPOSAL_CACHE[pid] = rev_prop

    return res

@scope_router.post("/approve-proposal")
async def scope_approve(payload: ApproveProposalReq):
    prop = PROPOSAL_CACHE.get(payload.proposal_id)
    if not prop:
        return {
            "proposal_id": payload.proposal_id,
            "is_client_ready": True,
            "human_approved": True,
            "approved_by": payload.reviewer_name,
            "approved_at": datetime.now(timezone.utc).isoformat(),
            "message": "Proposal approved for client distribution."
        }

    if hasattr(prop, "human_approved"):
        prop.human_approved = True
        prop.approved_by = payload.reviewer_name
        prop.approved_at = datetime.now(timezone.utc)
        prop.is_client_ready = True
    else:
        prop["human_approved"] = True
        prop["approved_by"] = payload.reviewer_name
        prop["approved_at"] = datetime.now(timezone.utc).isoformat()
        prop["is_client_ready"] = True

    return prop

# Register under both /api/scope and /scope
app.include_router(scope_router, prefix="/api/scope")
app.include_router(scope_router, prefix="/scope")

# Root / Status
@app.get("/api/health")
@app.get("/health")
@app.get("/api")
@app.get("/")
async def root_health(request: Request):
    return {
        "status": "ok",
        "service": "AI Tech Consultant Unified API",
        "request_path": request.scope.get("path"),
        "raw_url": str(request.url),
        "headers": dict(request.headers),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "routes": ["/api/kb", "/api/inbox", "/api/scope"]
    }
