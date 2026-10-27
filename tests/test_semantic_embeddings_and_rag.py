import os
import sys
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "task1-knowledge-brain"))

from app.config import settings
from retrieval.embeddings import embedding_engine, EmbeddingEngine
from retrieval.vector_store import vector_store
from retrieval.qa_engine import qa_engine, SYSTEM_PROMPT
import numpy as np

# ==============================================================================
# 1. PRETRAINED EMBEDDING MODEL & DIMENSIONALITY TESTS
# ==============================================================================

def test_pretrained_embedding_engine_active():
    """Verify that the genuine SentenceTransformer model is loaded and producing 384-dim normalized vectors."""
    assert embedding_engine.is_pretrained is True
    assert embedding_engine.model_name == "all-MiniLM-L6-v2"
    assert embedding_engine.dimension == 384

    vec = embedding_engine.get_embedding("Testing semantic embeddings with SentenceTransformer")
    assert isinstance(vec, list)
    assert len(vec) == 384
    norm = np.linalg.norm(np.array(vec, dtype=np.float32))
    assert abs(norm - 1.0) < 1e-4, f"Embedding must be L2 normalized; got norm={norm}"

def test_batched_embeddings_computation():
    """Verify batched embedding encoding produces matching dimensions for all items."""
    texts = [
        "How do I import categories in Brilliant Directories?",
        "Configure custom domain DNS settings and nameservers",
        "Member signup and subscription recurring billing workflow"
    ]
    batch_vecs = embedding_engine.get_embeddings(texts, batch_size=2)
    assert len(batch_vecs) == 3
    for v in batch_vecs:
        assert len(v) == 384
        norm = np.linalg.norm(np.array(v, dtype=np.float32))
        assert abs(norm - 1.0) < 1e-4

def test_semantic_similarity_different_vocabulary():
    """Verify that semantic paraphrases without keyword overlap yield high cosine similarity."""
    q_synonym = "bulk upload member accounts via spreadsheet"
    doc_target = "Guide to importing members from a CSV file into your directory database"
    doc_unrelated = "Bake a chocolate cake with frosting and sprinkles in the oven"

    vec_q = embedding_engine.get_embedding(q_synonym)
    vec_target = embedding_engine.get_embedding(doc_target)
    vec_unrelated = embedding_engine.get_embedding(doc_unrelated)

    sim_target = embedding_engine.cosine_similarity(vec_q, vec_target)
    sim_unrelated = embedding_engine.cosine_similarity(vec_q, vec_unrelated)

    assert sim_target > 0.45, f"Expected strong semantic similarity for paraphrase, got {sim_target}"
    assert sim_unrelated < 0.20, f"Expected low similarity for unrelated topic, got {sim_unrelated}"
    assert sim_target > sim_unrelated + 0.30

# ==============================================================================
# 2. HYBRID RETRIEVAL & SOURCE ATTRIBUTION TESTS
# ==============================================================================

def test_semantic_retrieval_and_source_attribution():
    """Verify retrieval returns relevant chunks with complete source citations and attribution metadata."""
    query = "How do I import categories via CSV file?"
    results = vector_store.hybrid_search(query, top_k=3)
    assert len(results) > 0

    top = results[0]
    assert "categories" in top["title"].lower() or "import" in top["title"].lower()
    assert top["url"].startswith("http")
    assert top["section"] is not None
    assert top["relevance"] >= 0.50
    assert len(top["content"]) > 30

def test_qa_engine_returns_grounded_citations():
    """Verify QAEngine attaches valid SourceCitation objects to answered inquiries."""
    resp = qa_engine.generate_answer("How do email forwarders work in Brilliant Directories?")
    assert resp.status == "answered"
    assert resp.confidence >= 0.50
    assert len(resp.sources) > 0

    citation = resp.sources[0]
    assert citation.title
    assert citation.url.startswith("http")
    assert citation.snippet
    assert citation.relevance >= 0.50

# ==============================================================================
# 3. ABSTENTION & OUT-OF-DOMAIN HANDLING
# ==============================================================================

def test_irrelevant_query_abstention_and_escalation():
    """Verify that out-of-domain queries abstain safely and create human escalation tasks."""
    out_of_domain_queries = [
        "What is the refund policy for custom Martian real estate listings?",
        "Can I run autonomous Kubernetes pods inside the Brilliant Directories shared hosting?",
        "Does Brilliant Directories support quantum entanglement encryption?"
    ]

    for q in out_of_domain_queries:
        resp = qa_engine.generate_answer(q)
        assert resp.status == "insufficient_evidence", f"Query '{q}' should abstain with insufficient_evidence; got {resp.status}"
        assert resp.needs_human is True
        assert resp.confidence <= 0.45
        assert resp.escalation_id is not None
        assert resp.escalation_id.startswith("ESC-")

def test_empty_query_abstains_without_escalation():
    """Whitespace-only query must prompt user for valid inquiry without creating false escalation."""
    resp = qa_engine.generate_answer("    ")
    assert resp.status == "insufficient_evidence"
    assert resp.needs_human is False
    assert resp.confidence == 0.0

# ==============================================================================
# 4. LLM PROMPT COMPOSITION VERIFICATION
# ==============================================================================

def test_query_and_retrieved_chunks_passed_to_llm():
    """Verify that the user query and retrieved chunk evidence blocks are passed to the configured LLM."""
    mock_anthropic = MagicMock()
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="Grounded answer synthesized from evidence.")]
    mock_client.messages.create.return_value = mock_response
    mock_anthropic.Anthropic.return_value = mock_client

    test_api_key = "sk-ant-api03-test-mock-key-for-prompt-verification-9999"
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": test_api_key}):
        with patch.object(qa_engine, "api_key", test_api_key):
            with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
                resp = qa_engine.generate_answer("How do I import categories via CSV file in Brilliant Directories?")

                assert mock_client.messages.create.called
                call_kwargs = mock_client.messages.create.call_args[1]

                # 1. System prompt rules verified
                assert call_kwargs["system"] == SYSTEM_PROMPT
                assert "Grounding: Answer ONLY using facts directly stated" in call_kwargs["system"]

                # 2. User inquiry and evidence verified in message
                messages = call_kwargs["messages"]
                assert len(messages) == 1
                user_msg = messages[0]["content"]

                assert "User Inquiry: How do I import categories via CSV file in Brilliant Directories?" in user_msg
                assert "Evidence Documents:" in user_msg
                assert "--- EVIDENCE 1 ---" in user_msg
                assert "Title:" in user_msg
                assert "URL:" in user_msg
                assert "Content:" in user_msg

# ==============================================================================
# 5. RESUMABLE RE-EMBEDDING VERIFICATION
# ==============================================================================

def test_resumable_reembedding_preserves_article_integrity():
    """Verify that reembed_all_chunks executes cleanly and preserves all database records."""
    stats = vector_store.reembed_all_chunks(batch_size=64)
    assert stats["total_chunks"] == 453
    assert stats["reembedded"] == 453
    assert stats["is_pretrained"] is True
    assert stats["dimension"] == 384

    # Verify article counts and chunk counts remain unchanged
    db_stats = vector_store.get_stats()
    assert db_stats["active_articles"] == 83
    assert db_stats["active_chunks"] == 453
