from typing import List, Optional, Literal, Dict, Any
from pydantic import BaseModel, Field

class SourceCitation(BaseModel):
    title: str = Field(..., description="Title of the source article")
    url: str = Field(..., description="Canonical URL of the source article")
    section: str = Field(..., description="Heading or section where the fact was found")
    relevance: float = Field(..., description="Relevance score (0.0 to 1.0)")
    image_url: Optional[str] = Field(None, description="Screenshot image URL if applicable")
    image_description: Optional[str] = Field(None, description="Extracted screenshot description or label")
    snippet: str = Field(..., description="Relevant text excerpt from article")

class QueryRequest(BaseModel):
    question: str = Field(..., description="Customer question or inquiry")
    top_k: int = Field(4, ge=1, le=10, description="Number of evidence chunks to retrieve")
    category: Optional[str] = Field(None, description="Optional category filter")
    image_data: Optional[str] = Field(None, description="Optional user screenshot (base64 data URL or URL)")
    min_confidence: Optional[float] = Field(0.40, description="Minimum confidence threshold")

class QueryResponse(BaseModel):
    answer: str = Field(..., description="Grounded answer synthesized from evidence")
    status: Literal["answered", "insufficient_evidence", "escalated"] = Field(
        ..., description="Retrieval outcome status"
    )
    sources: List[SourceCitation] = Field(
        default_factory=list, description="Articles and screenshots supporting the answer"
    )
    confidence: float = Field(..., description="Confidence estimate between 0.0 and 1.0")
    needs_human: bool = Field(False, description="Whether human expert escalation is recommended")
    escalation_id: Optional[str] = Field(None, description="Escalation ticket ID if created")
    analyzed_visual: Optional[Dict[str, Any]] = Field(None, description="Visual elements extracted from user screenshot")

class IngestionRunRequest(BaseModel):
    limit: Optional[int] = Field(None, description="Max number of articles to crawl (None for all)")
    force_reindex: bool = Field(False, description="Re-parse and re-index already crawled articles")
    delay_seconds: Optional[float] = Field(None, description="Delay between HTTP requests in seconds")

class IngestionStatusResponse(BaseModel):
    status: str = Field(..., description="Current status: idle, running, completed, error")
    total_sitemap_urls: int = Field(0, description="Total URLs found in sitemap")
    crawled_count: int = Field(0, description="Number of articles successfully crawled")
    failed_count: int = Field(0, description="Number of failed URL fetches")
    chunk_count: int = Field(0, description="Total active searchable chunks in index")
    active_articles: int = Field(0, description="Number of active indexed articles")
    last_run: Optional[str] = Field(None, description="Timestamp of the last crawl/ingestion")
    is_running: bool = Field(False, description="Whether crawler is currently executing")

class EscalationCreateRequest(BaseModel):
    question: str = Field(..., description="Unanswered question")
    user_email: Optional[str] = Field(None, description="User or customer email")
    reason: str = Field("Insufficient evidence in knowledge base", description="Reason for escalation")

class EscalationResolveRequest(BaseModel):
    expert_answer: str = Field(..., description="Verified answer from product specialist")
    supporting_notes: Optional[str] = Field(None, description="Additional context or links")
    approved_by: str = Field("Support Lead", description="Name/email of approving human expert")

class EscalationItem(BaseModel):
    id: str = Field(..., description="Unique escalation identifier")
    question: str = Field(..., description="Unanswered question")
    status: Literal["pending", "resolved"] = Field(..., description="Current state")
    user_email: Optional[str] = None
    reason: str
    expert_answer: Optional[str] = None
    supporting_notes: Optional[str] = None
    approved_by: Optional[str] = None
    created_at: str
    resolved_at: Optional[str] = None

class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "1.0.0"
    database_ok: bool = True
    indexed_articles: int = 0
    indexed_chunks: int = 0
