# AI Tech Consultant

An autonomous, multi-agent AI tech consultancy system that unifies company product knowledge, handles customer email support with human-in-the-loop learning, and transforms messy client meeting transcripts into verified Scopes of Work (SOW), task hour estimates, and proposals.

---

## Architecture at a Glance

The solution connects **three independently testable components** through a single shared knowledge service:

1. **Task 1 — Knowledge Brain (Python / FastAPI):**
   - Scrapes and indexes Brilliant Directories Solution Center documentation.
   - Extracts screenshots and associates UI visual steps with procedural instructions.
   - Grounded RAG with exact source citations, honest abstention, and an expert escalation queue.
   - Exposes REST API on `http://127.0.0.1:8000`.

2. **Task 2 — Inbox Agent (TypeScript / Node.js):**
   - Ingests customer inquiries across 7 intent and risk categories.
   - Consumes Task 1 API over HTTP for verified product facts.
   - Generates structured response drafts with safety guardrails (refund & legal locks).
   - Enforces a 20-consecutive-approval rule for autonomous sending with instant revocation on human edits.
   - Exposes REST API on `http://127.0.0.1:3001`.

3. **Task 3 — Meeting to Scope (Python / Multi-Agent):**
   - Team of 5 specialized agents: *Transcript Analyst*, *Feasibility Agent* (calls Task 1 API), *Scope Agent*, *Estimation Agent*, and *Proposal Agent*.
   - Evaluates existing configuration vs custom development to save client costs.
   - Compares follow-up meetings against the approved baseline (Scope Diff Engine).
   - Exposes REST API on `http://127.0.0.1:8002`.

4. **Unified Operations Dashboard:**
   - Single glassmorphic interface at `http://127.0.0.1:5000` supporting Knowledge Chat, Inbox Review, and Scope Builder.

---

## Prerequisites

- **Python:** 3.12+ (managed with `uv` or `pip`)
- **Node.js:** v20+ / v24+
- **Operating System:** Windows, macOS, or Linux

---

## Quickstart (One-Command Run)

### Windows:
Double-click `run_all.bat` or execute in PowerShell:
```powershell
.\run_all.ps1
```

### Linux / macOS:
```bash
python3 scripts/start_services.py
```

Once launched, open your browser to **`http://127.0.0.1:5000`**.

---

## Running Individual Services

### Task 1: Knowledge Brain
```bash
cd task1-knowledge-brain
uv run uvicorn app.main:app --port 8000
```

### Task 2: Inbox Agent
```bash
cd task2-inbox-agent
npm install
npm run build
npm start
```

### Task 3: Meeting to Scope
```bash
cd task3-meeting-to-scope
uv run uvicorn app.main:app --port 8002
```

---

## Running Evaluations

All tasks include comprehensive, reproducible test suites:

```bash
# Task 1 Evals (22 cases):
uv run python task1-knowledge-brain/evaluation/run_evals.py

# Task 2 Evals (50 emails + autonomy rules):
cd task2-inbox-agent && npm run eval

# Task 3 Evals (22 cases):
uv run python task3-meeting-to-scope/evaluation/run_evals.py
```

**Overall Test Results:** 94/94 Test Cases Passed (100% Pass Rate across all 3 tasks).
