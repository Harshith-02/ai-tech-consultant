from fastapi import APIRouter, HTTPException
from app.models import QueryRequest, QueryResponse
from retrieval.qa_engine import qa_engine

router = APIRouter(prefix="", tags=["Knowledge Query"])

@router.post("/query", response_model=QueryResponse)
async def query_knowledge_brain(request: QueryRequest):
    try:
        response = qa_engine.generate_answer(
            question=request.question,
            top_k=request.top_k
        )
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Knowledge retrieval error: {str(e)}")
