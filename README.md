---
title: Lead Enrichment Pipeline
emoji: 🎯
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---
# Alfaleus Lead Intelligence
### Lead Enrichment & Qualification Pipeline

A sales-intelligence tool that takes a raw lead (name / company / website), autonomously enriches it from public sources, scores it against a configurable Ideal Customer Profile using **semantic reasoning from a local LLM**, detects buying signals across sources, generates two personalized outreach drafts (full subject + body + CTA, written by the LLM), and syncs everything to a Notion CRM. Ships with a web dashboard, a Chrome extension, and four bonus modules (email finder, sequence builder, score history, domain-level discovery).

> **Key constraint honored:** all ML inference runs **locally and CPU-bound** via `llama-cpp-python` â€” no external inference APIs (no Groq / OpenAI / Gemini).

---

## Table of Contents
- [Architecture](#architecture)
- [Features](#features)
- [Bonus Features](#bonus-features)
- [Model Choice & Memory Footprint](#model-choice--memory-footprint)
- [ICP Scoring Formula](#icp-scoring-formula)
- [Scraping Approach & Known Failure Modes](#scraping-approach--known-failure-modes)
- [Deduplication](#deduplication)
- [Tech Stack](#tech-stack)
- [Setup & Installation](#setup--installation)
- [Running the App](#running-the-app)
- [Chrome Extension](#chrome-extension)
- [API Endpoints](#api-endpoints)
- [Project Structure](#project-structure)
- [Implementation Notes](#implementation-notes)

---

## Architecture

```
   CSV Upload        Web Dashboard        Chrome Extension
        \                  |                    /
         \                 |                   /
          -----------------+------------------
                           |
                    FastAPI Backend
        (hosts ONE local GGUF model instance, CPU-bound)
                           |
        +---------+--------+--------+-----------+
        |         |        |        |           |
     scraper  enrichment  icp    outreach     crm
    (website  (profile +  (sem.  (2 email   (Notion +
    + news +  confidence) fit +   variants)  dedup +
    LinkedIn)             signals)           status)
                           |
                           v
              SQLite (local state, dedup, status)
                           |
                           v
                Notion CRM (dedup, per-lead status)
```

The backend hosts a single local model instance shared by the dashboard and the Chrome extension, so the model is loaded into memory only once.

---

## Features

| Section | Status |
|---|---|
| Multi-source enrichment (website + Google News + LinkedIn best-effort) | Implemented |
| Per-field confidence levels (high / medium / low) | Implemented |
| Graceful degradation on source failure | Implemented |
| Semantic ICP scoring (LLM reasoning, not keyword match) | Implemented |
| Buying-signal detection across sources (news + tech-stack fit), typed + sourced | Implemented |
| Configurable scoring weights & threshold (no code change) | Implemented |
| 2 personalized outreach drafts â€” full email written by the LLM (direct + consultative) | Implemented |
| Notion CRM sync with deduplication + per-lead status + all raw fields & ICP breakdown | Implemented |
| Web dashboard (6 screens) â€” sortable/filterable table, ICP breakdown, score history | Implemented |
| Live pipeline-status view (per-lead stage, auto-refresh) | Implemented |
| ICP config screen with live "score a sample lead" preview | Implemented |
| Chrome extension (DOM extraction â†’ backend, Railway-configurable) | Implemented |
| CSV upload â€” client-side validation + background (non-blocking) processing | Implemented |

---

## Bonus Features

| Bonus | Status | Where |
|---|---|---|
| **Email finder** â€” permutation patterns + MX-record domain verification (no paid API); separates *verified* (domain has MX) from *likely* | Implemented | `services/email_finder.py`, detail view "Possible Emails" |
| **Sequence builder** â€” 3-step outreach (initial / +3 days / +7 days), each LLM-generated, exportable as CSV for any sending tool | Implemented | `services/sequence.py`, detail view "Outreach sequence" |
| **Lead scoring history** â€” every re-enrich appends to a timeline; detail view shows ICP/combined over time with â–²/â–¼ deltas | Implemented | `score_history` column in `database/db.py`, detail view "Score history" |
| **Domain-level discovery** â€” input a domain, scrape its team/about pages, LLM-extract individual people (name + title) to seed as leads | Implemented | `services/discover.py`, "Add Lead" â†’ "Discover leads from a domain" |

> MX verification uses `dnspython`; if it is unavailable the finder degrades gracefully to a socket lookup and marks results *unverified* rather than failing.

---

## Model Choice & Memory Footprint

- **Model:** Qwen2.5-0.5B-Instruct, quantized **Q4_K_M** (GGUF).
- **Runtime:** `llama-cpp-python` on CPU (`n_gpu_layers=0`), `n_ctx=2048`.
- **Disk:** ~470 MB. **Context window:** 2048 tokens (kept small to limit RAM).

**Why 0.5B:** It fits comfortably within free-tier memory limits and satisfies the CPU-bound requirement while keeping inference fast (~1-3s per call locally).

**Trade-offs & how they're mitigated.** A 0.5B model is weak at complex structured generation, so the pipeline is engineered around that:

- **Simplest-possible output, structured in Python.** For buying signals the model only returns a flat map like `{"1":"high","2":"none"}`; Python attaches the headline text. This avoids nested JSON that small models break on (headlines contain quotes/colons).
- **Never-fail JSON parser.** `generate_json()` strips code fences, extracts the first JSON block, repairs trailing commas, and falls back to `{"_parse_error": ...}` â€” it never raises, protecting every downstream call.
- **Retry on flaky scoring.** ICP scoring retries once if the first parse fails (squares the success rate).
- **Few-shot signal classification.** Examples in the prompt flip the model from misclassifying scandal/politics as buying signals to correctly favoring partnerships/funding/expansion.
- **Repetition guard.** `repeat_penalty=1.3` prevents degenerate "word word wordâ€¦" loops.
- **Full email, then hard-cleaned in Python.** The model writes the *complete* email (subject + body + CTA) grounded in the top buying signal or company description. A `_clean_email()` step then parses the `Subject:` line and **hard-trims everything after the sign-off**, stripping the small model's trailing meta-commentary ("Note:", "Greeting:", "This email followsâ€¦"). If output is empty/malformed, a Python fallback email is used. Two tone variants (direct + consultative) are produced.

A larger model (e.g. Qwen2.5-1.5B) improves quality and is a one-line swap (`MODEL_PATH`), at higher memory cost.

---

## ICP Scoring Formula

Configured entirely in `config/settings.json` â€” **no code changes required.**

```
combined_score = (weight_icp_fit       * icp_fit_score)
               + (weight_buying_signals * buying_signal_score)
```

- **`icp_fit_score`** (0-100): the average of five criteria â€” industry, company size, tech indicators, contact seniority, geography â€” each scored by the LLM using **genuine semantic reasoning**. Examples it handles: "boutique consultancy with 40 engineers" satisfies "20-100 employees"; "Head of Platform Engineering" maps to VP-equivalent seniority. Missing data scores a neutral 50 rather than guessing.
- **`buying_signal_score`** (0-100): weighted sum of detected signals (high = 30, medium = 18, low = 8), capped at 100. Signals come from **two sources**: (1) Google News headlines, LLM-classified and typed as *funding / hiring / expansion / product*, and (2) a deterministic **tech-stack-fit** signal when the lead's detected tech overlaps the ICP's `target_tech_indicators`. Each signal records its strength, type, and source.
- **Disqualifiers** (excluded industries, competitor names) are checked **deterministically in Python**, not by the LLM. This is a hard business rule and keeps the small model from confusing "target" vs "exclude" industries.

**Defaults:** weights `0.7 / 0.3`, qualification threshold `50`. All editable in config.

---

## Scraping Approach & Known Failure Modes

- **Company website** â€” static fetch + BeautifulSoup. Extracts page title, meta description, visible text (capped at 4000 chars to stay within the model's 2048-token context), tech-stack signatures (React, WordPress, Shopify, HubSpot, etc.), and up to 2 internal pages (about / pricing / careers).
  - *Failure mode:* JavaScript-rendered sites return little text. Handled by graceful degradation â€” title/meta are still captured and the pipeline continues.
- **Google News** â€” RSS feed (no API key) for recent company mentions, used as the buying-signal source.
- **LinkedIn** â€” **best-effort, via the Chrome extension only.** Server-side LinkedIn scraping is **not attempted** (auth wall, anti-scraping); it is marked `blocked / low confidence` and never aborts the pipeline.
  - *Failure mode:* LinkedIn's obfuscated, lazy-loaded DOM means name/company auto-fill in the extension may miss or grab the wrong company link. **All popup fields are editable**, so the user corrects before enriching â€” graceful degradation by design.
- Every enriched field carries a **confidence level** (high / medium / low) based on whether it was directly stated or inferred.
- All network calls have **hard timeouts** so a slow or dead source fails fast instead of hanging the pipeline.

---

## Deduplication

Enforced in **two independent layers**, both verified on repeated runs:

- **SQLite:** upsert keyed on `(company_domain, email)` â€” existing rows are updated, never duplicated. When a lead has **neither** a domain nor an email, it falls back to matching on `(name, company)` so name-only leads don't duplicate either.
- **Notion CRM:** queries for an existing record by domain/email before writing; updates in place and reports per-lead status: `synced` / `updated` / `pending` / `failed`.

Re-enriching an existing lead also appends a point to its `score_history` timeline (see Bonus Features) rather than overwriting history.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend / API | FastAPI + Uvicorn |
| Local LLM | Qwen2.5-0.5B-Instruct (GGUF) via llama-cpp-python |
| Scraping | requests, BeautifulSoup4, feedparser |
| Email verification | dnspython (MX lookup) â€” bonus email finder |
| Storage | SQLite (stdlib `sqlite3`) |
| CRM | Notion API (`notion-client==2.2.1`) |
| Frontend | Vanilla HTML / CSS / JS (single file) |
| Extension | Chrome Manifest V3 |

---

## Setup & Installation

```bash
# 1. Create and activate a virtual environment (Python 3.11)
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS / Linux

# 2. Install dependencies
pip install -r requirements.txt
```

> **llama-cpp-python note:** if the pinned version fails to build, install the prebuilt CPU wheel:
> ```bash
> pip install llama-cpp-python==0.2.90 --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
> ```
> For older CPUs without AVX support, use the basic wheel index or the direct release wheel.

```bash
# 3. Download the model (~470 MB) into models/
python dl.py

# 4. Create a .env file in the project root:
#    NOTION_API_KEY=your_notion_integration_token
#    NOTION_DB_ID=your_notion_database_id
```

**Notion setup:** create an internal integration, build a database with these columns, then connect the integration to the database (`â€¢â€¢â€¢` â†’ Connections):

```
Name (title), Company (text), Domain (text), Email (email),
ICP Score (number), Combined Score (number),
Buying Signals (text), Enriched Fields (text), ICP Breakdown (text),
Status (select), Email Draft 1 (text), Email Draft 2 (text)
```

> **Note:** `Enriched Fields` and `ICP Breakdown` are required for the full-record sync (all raw enriched fields with confidence levels + the per-criterion ICP breakdown). If a column is missing, the Notion write for that lead fails silently and the lead's sync status shows `failed`.

---

## Running the App

```bash
uvicorn backend.main:app --reload
```

Then open **http://127.0.0.1:8000/app** for the dashboard.
Interactive API docs are at **http://127.0.0.1:8000/docs**.

---

## Chrome Extension

1. Go to `chrome://extensions` and enable **Developer mode**.
2. Click **Load unpacked** and select the `extension/` folder.
3. With the backend running, open any company website or LinkedIn profile, click the
   extension icon, review the auto-filled fields (name, title, company, location, URL),
   and click **Enrich Lead**.
4. Results (ICP score, buying signal, qualification) appear in the popup and the lead is
   saved to the dashboard.

**Pointing the extension at a deployed backend.** The backend base URL defaults to
`http://127.0.0.1:8000` for local dev. For the live Railway deployment, either:
- edit `DEFAULT_API` at the top of `extension/popup.js`, **or**
- set an override at runtime without editing code, from the extension's service-worker /
  popup console: `chrome.storage.local.set({ apiBase: "https://your-app.up.railway.app" })`

The manifest already grants host permissions for `*.railway.app` / `*.up.railway.app`.

---

## API Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/` | Health check |
| GET | `/app` | Serves the dashboard |
| POST | `/enrich` | Run the full pipeline on one lead |
| POST | `/upload-csv` | Parse + clean a CSV, then enrich the batch **in the background** (returns immediately) |
| GET | `/leads` | List all stored leads |
| GET | `/lead/{id}` | Full detail for one lead |
| POST | `/sync/{id}` | Push a lead to Notion (deduped) |
| GET | `/icp` | Return the current ICP config |
| GET | `/pipeline-status` | Live in-flight + recent enrichment jobs with per-lead stage |
| POST | `/preview-icp` | Score a free-text sample lead against the current ICP (no storage) |
| POST | `/find-emails` | **Bonus:** permutation emails + MX verification for a name + domain |
| POST | `/sequence/{id}` | **Bonus:** build a 3-step outreach sequence + CSV for a stored lead |
| POST | `/discover-leads` | **Bonus:** discover people from a company domain's team/about pages |

---

## Project Structure

```
lead-pipeline/
â”œâ”€â”€ backend/
â”‚   â””â”€â”€ main.py            FastAPI app + endpoints + pipeline orchestration
â”œâ”€â”€ services/
â”‚   â”œâ”€â”€ llm.py             GGUF model singleton + never-fail JSON helpers
â”‚   â”œâ”€â”€ scraper.py         website + Google News + LinkedIn (best-effort)
â”‚   â”œâ”€â”€ enrichment.py      builds profile + confidence levels
â”‚   â”œâ”€â”€ icp.py             semantic ICP scoring + multi-source buying signals
â”‚   â”œâ”€â”€ outreach.py        2 grounded full-email variants (LLM-written)
â”‚   â”œâ”€â”€ email_finder.py    bonus: permutation emails + MX verification
â”‚   â”œâ”€â”€ sequence.py        bonus: 3-step outreach sequence + CSV export
â”‚   â”œâ”€â”€ discover.py        bonus: domain-level people discovery
â”‚   â””â”€â”€ crm.py             Notion sync + dedup + status (full-record)
â”œâ”€â”€ database/
â”‚   â””â”€â”€ db.py              SQLite schema + upsert/dedup + score history + queries
â”œâ”€â”€ frontend/
â”‚   â””â”€â”€ index.html         dashboard (6 screens), served by FastAPI
â”œâ”€â”€ extension/             Chrome extension (Manifest V3)
â”‚   â”œâ”€â”€ manifest.json
â”‚   â”œâ”€â”€ popup.html
â”‚   â””â”€â”€ popup.js           DOM extraction via chrome.scripting (no content script)
â”œâ”€â”€ config/
â”‚   â””â”€â”€ settings.json      ICP, scoring weights, product (editable, no code)
â”œâ”€â”€ models/                GGUF model (gitignored)
â”œâ”€â”€ dl.py                  model downloader
â”œâ”€â”€ requirements.txt
â””â”€â”€ README.md
```

---

## Implementation Notes

- **Local inference only.** No external LLM APIs are used anywhere â€” the constraint is honored end-to-end.
- **`notion-client` pinned to 2.2.1.** Version 3.x migrated to a data-source API incompatible with the classic database calls used here; 2.2.1 resolves database IDs correctly.
- **Python 3.11** is required â€” `llama-cpp-python` prebuilt wheels are most reliable there.
- **Secrets** live in `.env` (gitignored); the model and database files are gitignored as well.
