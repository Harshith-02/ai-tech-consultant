# AI Tech Consultant — Enterprise Knowledge & Intelligent Email Assistant

An autonomous, multi-agent AI tech consultancy system that unifies company product knowledge, handles customer email support with human-in-the-loop learning, and transforms client meeting transcripts into verified Scopes of Work (SOW), task hour estimates, and proposals.

- **Live Application:** [https://ai-tech-consultant-mu.vercel.app/](https://ai-tech-consultant-mu.vercel.app/)
- **GitHub Repository:** [https://github.com/Harshith-02/ai-tech-consultant](https://github.com/Harshith-02/ai-tech-consultant)

---

## 🌟 Major System Upgrades

### Upgrade A: Advanced Sitemap Discovery, Ingestion & Automatic Refresh
- **Multi-Source Sitemap Support:** Add, inspect, and track multiple independent sitemap origins (`sitemap_sources` table).
- **Recursive Sitemap Traversal:** Automatically navigates nested `<sitemapindex>` hierarchies down to terminal page URLs.
- **SSRF Safeguards & Redirect Defense:** Per-hop IP and hostname re-validation for every HTTP redirect (301/302/307/308), strictly blocking private IP blocks (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), localhost/loopback, link-local metadata (`169.254.169.254`), and cloud internal destinations.
- **Discovery Preview & Explicit Confirmation:** Displays total URLs discovered, first/last URL sample, speed estimates, pipeline stages, and expected completion datetime before any crawling begins.
- **Dynamic Measured ETA:** Calculations based on observed rolling throughput across page fetching, parsing, chunk generation, embedding generation, and indexing, reporting realistic completion estimates (`X hours Y mins (±1 day)`).
- **3-Case Incremental Change Detection:**
  - *Case 1 (New URLs):* Automatically fetched, parsed, chunked, embedded, and added to the Knowledge Brain.
  - *Case 2 (Changed URLs):* Verified via conditional re-validation and SHA-256 content hashes, updating index chunks atomically.
  - *Case 3 (Missing URLs):* Absence is tracked across consecutive runs. Configurable retention thresholds (1, 2, 15, or 30 consecutive checks; default 15) before historical archival.
  - *Cross-Source Protection:* Shared URLs referenced by another active source remain active.
- **Table #2 Archival:** Missing URLs that cross the threshold are retired from active retrieval (Table #1) and safely preserved in Table #2 (`archived_articles`) with version history for audit and one-click restoration.
- **Durable Background Refresh Scheduler:** Configurable schedules (Daily, Weekly, Every 15 Days, or Every 30 Days) with `/api/kb/sitemap/refresh-due` handling concurrency locks, missed runs, and process restarts.

### Upgrade B: Real Gmail Integration & Intelligent Email Assistant
- **Google OAuth 2.0 Integration:** Secure connection flow requesting minimum necessary scopes (`gmail.readonly`, `gmail.compose`, `gmail.modify`, `userinfo.email`) with CSRF state protection.
- **Standard AES-256-GCM Authenticated Encryption:** AES-256-GCM AEAD encryption with cryptographically secure 96-bit nonces, 128-bit authentication tags, and versioned `v1:` ciphertext. Zero hardcoded secrets, fail-safe environment variable enforcement.
- **Real Inbox Synchronization:** Fetches live Gmail messages via Gmail API / History cursor, extracts thread context, and supports Inbox, Starred, Drafts, Sent, Spam, and Trash.
- **9 Configurable Topic Classification Categories:**
  1. `filters` — Filters & Facets, search dropdowns, breadcrumbs, ranking.
  2. `home_page` — Home Page Layout, hero banners, sliders, cover images.
  3. `domain_management` — Domain & DNS Management, SSL, nameservers, MX records.
  4. `header` — Header Layout, logo branding, header top bar.
  5. `main_menu` — Main Menu & Navigation navbar, menu links, dropdowns.
  6. `footer` — Footer Layout, copyright, social media links, bottom bar.
  7. `general_settings` — General Settings, timezone, company info, CSV import.
  8. `design_settings` — Design Settings, CSS overrides, typography, theme colors.
  9. `managers` — Managers & Admin Roles, staff access permissions.
  *(Plus permanently guarded `billing` for subscriptions and payments).*
- **Grounded Draft Generation in Real Gmail:** AI draft replies are generated using Knowledge Brain hybrid retrieval and created in authentic **Gmail Drafts folder** (`users.drafts.create`).
- **Configurable Autonomy Threshold X:**
  - Default: $X = 3$ consecutive unedited sent responses.
  - Configurable per category or globally in Settings.
  - Safe State Machine: approval streaks only commit upon confirmed external send.
- **AI Learning Engine (Draft vs. Sent Diffs):**
  - If a supervisor edits an AI draft before sending, the system captures the difference, persists the rule to SQLite `feedback_rules`, and resets the category streak to 0.
  - Subsequent drafts incorporate the learned supervisor rule directly.
- **Permanent Policy Restrictions:** High-risk categories (`refund_cancellation`, `complaint`, `project_request`, `quote_request`, `billing`) permanently require human review and cannot be bypassed.
- **Durable Persistence & Audit Logs:** Streaks, feedback rules, folder states, sent emails, and audit trails are persisted in SQLite (`knowledge_brain.db`).
- **Application Security & Authorization:** Protected `/api/kb/*` and `/api/inbox/*` endpoints require authentication headers with account-level isolation.

---

## 🚀 Quickstart & Local Setup

### 1. Environment Setup
Create a `.env` file in the project root:
```env
# Optional LLM API Keys (Falls back to deterministic rule & hybrid retrieval engines)
GEMINI_API_KEY=your_gemini_api_key_here

# Google OAuth 2.0 Credentials (for Real Gmail Connection)
GOOGLE_CLIENT_ID=your_google_client_id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your_google_client_secret
GOOGLE_REDIRECT_URI=http://localhost:8000/api/inbox/oauth/callback
GMAIL_ENCRYPTION_KEY=secure-random-encryption-salt-2026
```

### 2. Run the Unified Service (FastAPI + Static Frontend)
```bash
# Using the configured virtual environment:
& ".venv\Scripts\python.exe" -m uvicorn api.index:app --host 0.0.0.0 --port 8000 --reload
```
Open **`http://localhost:8000`** in your browser.

---

## 🔧 Google Cloud Console OAuth Setup Instructions

To connect your real Gmail account:
1. Open the [Google Cloud Console](https://console.cloud.google.com/) and create or select a project.
2. Navigate to **APIs & Services > Library**, search for **Gmail API**, and click **Enable**.
3. Navigate to **APIs & Services > OAuth consent screen**:
   - Choose **External** (or Internal for Google Workspace).
   - Fill in App Name (e.g. *AI Tech Consultant*), Support Email, and Developer Email.
   - Under Scopes, add:
     - `.../auth/gmail.readonly`
     - `.../auth/gmail.compose`
     - `.../auth/gmail.modify`
     - `.../auth/userinfo.email`
   - Under Test Users, add your personal Gmail address.
4. Navigate to **APIs & Services > Credentials**:
   - Click **Create Credentials > OAuth Client ID**.
   - Application type: **Web application**.
   - Name: *AI Tech Consultant Web Client*.
   - Authorized redirect URIs:
     - Local development: `http://localhost:8000/api/inbox/oauth/callback`
     - Production: `https://ai-tech-consultant-mu.vercel.app/api/inbox/oauth/callback`
5. Copy your **Client ID** and **Client Secret** into your `.env` file.
6. In the application dashboard, click the profile avatar in the top-right corner to open **Account & Autonomy Settings**, and click **Connect Gmail**!

---

## 🧪 Real Email Testing Instructions (3–4 Live Emails)

To test end-to-end functionality with 3–4 incoming customer inquiries:

1. **Connect Gmail:** In Account Settings, click **Connect Gmail** and authorize access.
2. **Send Test Email #1 (Search Filters):**
   - From another email address, send an email to your connected Gmail with:
     - **Subject:** *How do I configure custom search filters and category dropdowns?*
     - **Body:** *Hi team, we want to set up multi-tier search filter dropdowns on our homepage search. How do we configure this in the admin panel?*
   - Click **Sync** in the dashboard. The email will appear in your Inbox classified as `Filters & Facets`.
   - The AI generates a grounded draft referencing the official documentation and creates a genuine **Gmail Draft** in your Gmail account.
   - Click **Send (Unedited)**: The email is sent through Gmail, and the `filters` streak increments to $1/X$.
3. **Send Test Email #2 (Supervisor Diff Learning):**
   - Send an inquiry regarding CSS styling:
     - **Subject:** *Custom CSS button hover states*
     - **Body:** *Where do I edit the CSS stylesheets to override button hover colors?*
   - Open the draft in the dashboard.
   - Click **Edit Draft**, add your custom personalized sign-off (e.g., *"P.S. Make sure to back up your custom stylesheet first"*), and click **Send Edited**.
   - The AI Learning Engine records the difference in `FEEDBACK_RULES`, and resets the `design_settings` streak to $0/X$.
4. **Send Test Emails #3 & #4 (Unlocking Autonomy):**
   - Send two additional unedited queries in `filters`.
   - Once the streak reaches the configured threshold $X$ (default: 3), the label unlocks **Autonomous Auto-Sending**!
   - Send a 5th query under `filters`: The system automatically classifies the email, generates the grounded draft, and dispatches it directly to the customer without waiting for human review.

---

## 📊 Automated Evaluation Benchmark Results

All evaluation suites are 100% passing:

```bash
# Task 1 Knowledge Brain Evaluation (22 cases):
& ".venv\Scripts\python.exe" task1-knowledge-brain/evaluation/run_evals.py
# Result: 22/22 PASSED (100.0%)

# Task 2 Inbox Agent Evaluation (50 cases + autonomy engine):
cd task2-inbox-agent && npm test
# Result: 50/50 PASSED (100.0%, 0 safety violations)

# Task 3 Meeting to Scope Evaluation (22 cases):
& ".venv\Scripts\python.exe" task3-meeting-to-scope/evaluation/run_evals.py
# Result: 22/22 PASSED (100.0%)

# Pytest Comprehensive Test Suite (7 tests):
& ".venv\Scripts\python.exe" -m pytest tests/
# Result: 7/7 PASSED (100.0%)
```

---

## 🧠 Knowledge Brain Database & Search Architecture (Interview Submission)

### Hybrid Retrieval Design
The Knowledge Brain implements hybrid search combining lexical matching (BM25 full-text search) and dense semantic vector similarity over a durable, zero-external-dependency SQLite database:
1. **Lexical Retrieval (SQLite FTS5):**
   - Implemented via SQLite's native FTS5 extension (`chunks_fts` virtual table with `'porter unicode61'` tokenization).
   - Indexes chunk titles, section headings, body content, and image descriptions.
   - Computes BM25 ranking for exact keyword matches, error codes, and technical phrases.
2. **Dense Vector Similarity (384-Dimensional Embeddings):**
   - Deterministic 384-dimensional normalized vector embeddings generated by `retrieval.embeddings.EmbeddingEngine`.
   - Uses n-gram hashed feature projections with subword tokenization and IDF scaling.
   - Requires zero external cloud APIs or proprietary embedding services; produces identical vector representations across restarts.
3. **Calibrated Hybrid Fusion:**
   - Evaluates query against the FTS5 index and computes cosine similarity with persisted chunk embeddings.
   - Combines semantic similarity ($0.3$) and substantive token match ratio ($0.7$).
   - Filters candidates against `MIN_RELEVANCE_SCORE` (default $0.40$). If no chunks meet the threshold, the system safely abstains and creates an escalation ticket (`escalations` table).

### Database Storage & Persistence Mapping
All search assets, vectors, and metadata are durably persisted in SQLite (`task1-knowledge-brain/data/knowledge_brain.db`):
- `articles`: Primary article catalog, canonical URLs, titles, categories, content hashes, and source sitemap mapping.
- `chunks`: Granular document chunks, section headings, image metadata, and `embedding_json` (persisted 384-dim vector as JSON).
- `chunks_fts`: Native SQLite FTS5 shadow tables (`chunks_fts_data`, `chunks_fts_idx`, `chunks_fts_content`, `chunks_fts_docsize`, `chunks_fts_config`).
- `sitemap_sources`: Multi-source sitemap registry (e.g., Brilliant Directories, Divi / Elegant Themes).
- `sitemap_urls`: Discovered and indexed URLs per sitemap source with timestamps and crawl health.
- `article_version_history`: Snapshot history of article content across updates for change auditing.
- `archived_articles`: Archival storage (Table #2) for URLs missing across consecutive crawl checks.
- `escalations`: Question abstention tickets routed to human experts.

### Verified Row Counts
| Table / Index | Row Count | Description |
| :--- | :--- | :--- |
| `sitemap_sources` | **7** | Active documentation sitemaps (including Brilliant Directories & Divi) |
| `sitemap_urls` | **80** | Tracked and indexed sitemap URLs |
| `articles` | **75** | Ingested help center articles across sources (48 BD, 24 Divi, 3 samples) |
| `chunks` | **412** | Extracted semantic document chunks |
| `embedding_json` | **412** | Valid, normalized 384-dim dense vector embeddings |
| `chunks_fts` | **412** | SQLite FTS5 virtual table search index entries |
| `article_version_history` | **36** | Historical article revision snapshots |
| `archived_articles` | **33** | Archived URLs missing from sitemaps |
| `escalations` | **208** | Human specialist escalation tickets |

### Verifying Database & Search Functionality
Run the standalone database verification script:
```bash
python scripts/verify_database.py
```

Run the automated pytest verification suite:
```bash
pytest tests/test_hybrid_retrieval_verification.py -v
```

---

## 📁 Repository Structure & Key Changed Files

- `api/index.py` — Unified FastAPI gateway with OAuth 2.0 endpoints, token encryption, real Gmail synchronization, real draft creation, multi-source sitemap management, and audit logging.
- `task1-knowledge-brain/retrieval/vector_store.py` — Database models, schema migrations, and hybrid retrieval engine (SQLite FTS5 + 384-dim cosine similarity).
- `task1-knowledge-brain/retrieval/embeddings.py` — Self-contained 384-dimensional deterministic embedding engine.
- `task1-knowledge-brain/retrieval/qa_engine.py` — Grounded Q&A engine with citation verification and automated human escalation.
- `task1-knowledge-brain/data/knowledge_brain.db` — Populated, durable SQLite database with all tables, chunks, embeddings, and FTS5 indexes.
- `scripts/verify_database.py` — Automated verification script testing storage engine, row counts, embeddings, and BD/Divi retrieval.
- `tests/test_hybrid_retrieval_verification.py` — Pytest suite verifying persistence across process restarts, embedding normalization, and cross-source discrimination.

