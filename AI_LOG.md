# AI Coding Assistant Interaction Log & Prompt Engineering

**Project:** AI Tech Consultant  
**Tool Used:** Antigravity / Claude Code  
**Document Length:** 1 Page Max  

---

## 1. Five Most Useful Prompts

### Prompt 1: Resumable Checkpointed Crawler Architecture
> *"Design a polite, resumable sitemap crawler for Brilliant Directories Solution Center. It must parse the sitemap XML, compare URLs against a persistent JSON manifest checkpointing each page's status and SHA256 content hash, rate-limit with exponential backoff on 429/500 errors, and isolate failures so a dead link never aborts the crawl."*
- **Why it worked:** Forced the model to design a durable, checkpointed state machine rather than a fragile in-memory script.

### Prompt 2: Multimodal Screenshot Extraction & Association
> *"In Brilliant Directories help articles, screenshots inside the article body often contain the exact setting toggle or button name. Write a BeautifulSoup parser that extracts all content images, isolates their surrounding step paragraphs, and summarizes the interface action path (e.g. 'Members >> Member Categories') so screenshots become searchable text chunks."*
- **Why it worked:** Explicitly tied image attachments to nearby procedural verbs, turning visual artifacts into grounded text.

### Prompt 3: Hybrid Search Calibration & Calibrated Abstention
> *"Implement hybrid search in SQLite using FTS5 for BM25 keyword matching combined with normalized dense vector cosine similarity. Implement a strict lexical topic check: if non-stopword query tokens have zero hits in the document, do NOT let vector projection hallucinate relevance. Calibrate the threshold so out-of-scope questions cleanly trigger abstention."*
- **Why it worked:** Prevented the classic vector similarity hallucination trap where completely unrelated questions receive false 0.8+ scores.

### Prompt 4: 20-Consecutive-Approval Autonomy Engine with Safety Locks
> *"Build an autonomy state machine in TypeScript for customer email drafts. Track consecutive unedited sends per category, calculate string edit distance between generated drafts and sent text, and reset the streak to 0 if an edit occurs. Crucially, enforce permanent safety locks so refunds, complaints, and quotes NEVER become autonomous even after 20 sends."*
- **Why it worked:** Enforced commercial safety boundaries in strict TypeScript types instead of relying on prompt instructions alone.

### Prompt 5: Scope Diff Engine for Follow-Up Transcripts
> *"Create a Python Scope Diff Engine that compares requirements extracted from a follow-up meeting against an approved baseline SOW. Categorize changes into Added, Removed, Modified, and Out-of-Scope requests. Specifically flag out-of-scope requests (like legacy database migrations) for separate quotation to prevent scope creep."*
- **Why it worked:** Structured change detection around the commercial reality of consulting deliverables and timeline compression.

---

## 2. Example Where AI-Generated Output Was Rejected & Why

### The AI's Initial Proposal:
When asked to implement the RAG retrieval scoring in `vector_store.py`, the AI assistant suggested normalizing the Reciprocal Rank Fusion (RRF) score by dividing by the highest candidate score:
```python
# REJECTED AI IMPLEMENTATION:
normalized_relevance = min(1.0, (score / max_score) * 0.95)
```

### Why I Rejected It:
This mathematical shortcut had a catastrophic bug: **the highest-ranking candidate always received a 0.95 relevance score, regardless of how irrelevant the query actually was**.

When tested with an absurd query ("How do I bake a chocolate cake recipe with vanilla frosting?"), the AI assistant retrieved "How To Import Members Via CSV" with 0.95 confidence because it was the "least bad" document in an empty set, completely bypassing the 0.50 abstention threshold and fabricating an answer!

### Correct Implementation Implemented Instead:
I rejected the relative normalization and replaced it with an absolute lexical grounding formula:
```python
# ACCEPTED GROUNDED IMPLEMENTATION:
min_required_hits = 1 if len(substantive_tokens) <= 2 else 2
if keyword_hits < min_required_hits:
    continue  # Reject candidate immediately

hit_ratio = keyword_hits / len(substantive_tokens)
calibrated_relevance = (sim * 0.3) + (hit_ratio * 0.7)
if calibrated_relevance >= settings.MIN_RELEVANCE_SCORE:
    candidate_scores.append((cid, calibrated_relevance, c))
```
This ensured that out-of-scope inquiries received a calibrated score of 0.10, reliably triggering the required abstention, escalation ticket, and human specialist routing.
