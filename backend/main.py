import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
import csv
import io
import time
import threading
import itertools

from services.enrichment import enrich_lead
from services.icp import qualify_lead, load_config, score_icp_fit
from services.outreach import generate_outreach
from services.email_finder import find_emails
from services.sequence import build_sequence, sequence_to_csv
from services.discover import discover_leads
from services.crm import sync_lead
from database.db import init_db, upsert_lead, get_all_leads, get_lead, update_sync_status

app = FastAPI(title="Lead Enrichment Pipeline")

# CORS — needed so the Chrome extension (different origin) can call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")

init_db()


class LeadInput(BaseModel):
    name: str = ""
    company: str = ""
    website: str = ""
    email: str = ""


class FindEmailsInput(BaseModel):
    name: str = ""
    company_domain: str = ""


class PreviewIcpInput(BaseModel):
    name: str = ""
    company: str = ""
    description: str = ""


class DiscoverInput(BaseModel):
    domain: str = ""


# ---- pipeline status registry (for the live "Pipeline" view) ----
_status_lock = threading.Lock()
_job_counter = itertools.count(1)
PIPELINE_JOBS = {}  # job_id -> {id, company, name, stage, status, started, finished}


def _new_job(company, name):
    jid = next(_job_counter)
    with _status_lock:
        PIPELINE_JOBS[jid] = {
            "id": jid, "company": company or "(unknown)", "name": name or "",
            "stage": "queued", "status": "running", "started": time.time(),
            "finished": None,
        }
    return jid


def _set_stage(jid, stage):
    with _status_lock:
        if jid in PIPELINE_JOBS:
            PIPELINE_JOBS[jid]["stage"] = stage


def _finish_job(jid, status):
    with _status_lock:
        if jid in PIPELINE_JOBS:
            PIPELINE_JOBS[jid]["stage"] = status
            PIPELINE_JOBS[jid]["status"] = status
            PIPELINE_JOBS[jid]["finished"] = time.time()


def run_pipeline(name="", company="", website="", email="") -> dict:
    """The full pipeline: enrich -> qualify -> emails -> store. Returns the lead record."""
    jid = _new_job(company or website or email, name)
    try:
        _set_stage(jid, "enriching (website · news · linkedin)")
        t0 = time.time()
        profile = enrich_lead(name=name, company=company, website=website, email=email)
        print(f"[TIMING] enrich: {time.time()-t0:.1f}s")

        _set_stage(jid, "qualifying (ICP + buying signals)")
        t1 = time.time()
        qual = qualify_lead(profile)
        print(f"[TIMING] qualify: {time.time()-t1:.1f}s")

        _set_stage(jid, "drafting outreach")
        t2 = time.time()
        emails = generate_outreach(profile, qual)
        print(f"[TIMING] emails: {time.time()-t2:.1f}s")

        _set_stage(jid, "saving")
        lead_record = _build_record(name, company, email, profile, qual, emails)
        lead_id = upsert_lead(lead_record)
        lead_record["id"] = lead_id
        _finish_job(jid, "done")
        return lead_record
    except Exception:
        _finish_job(jid, "failed")
        raise


def _build_record(name, company, email, profile, qual, emails) -> dict:
    return {
        "name": name,
        "company": company,
        "company_domain": profile.get("company_domain", ""),
        "email": email,
        "profile": profile,
        "icp_score": qual["icp_score"],
        "combined_score": qual["combined_score"],
        "buying_signals": qual["buying_signals"],
        "emails": emails,
        "enrich_status": profile.get("enrich_status", "enriched"),
        "qualified": qual["qualified"],
        "icp_reasoning": qual.get("icp_reasoning", ""),
        "icp_breakdown": qual.get("icp_breakdown", {}),
    }


@app.get("/")
def health():
    return {"status": "ok", "service": "lead-enrichment-pipeline"}


@app.get("/app")
def serve_frontend():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


@app.post("/enrich")
def enrich_endpoint(lead: LeadInput):
    """Enrich a single lead end-to-end. Used by dashboard + Chrome extension."""
    if not (lead.company or lead.website or lead.email):
        raise HTTPException(400, "Provide at least company, website, or email.")
    try:
        record = run_pipeline(lead.name, lead.company, lead.website, lead.email)
        return {
            "id": record["id"],
            "name": record["name"],
            "company": record["company"],
            "icp_score": record["icp_score"],
            "combined_score": record["combined_score"],
            "qualified": record["qualified"],
            "top_signal": record["buying_signals"][0]["signal"] if record["buying_signals"] else None,
            "buying_signals": record["buying_signals"],
            "emails": record["emails"],
            "enrich_status": record["enrich_status"],
        }
    except Exception as e:
        raise HTTPException(500, f"Pipeline error: {e}")


def _process_csv_rows(rows: list[dict]):
    """Background worker: run the full pipeline for each parsed CSV row."""
    for row in rows:
        try:
            run_pipeline(
                name=row.get("name", ""),
                company=row.get("company", ""),
                website=row.get("website", ""),
                email=row.get("email", ""),
            )
        except Exception as e:
            print(f"[CSV] row failed ({row.get('company', '')}): {e}")


@app.post("/upload-csv")
async def upload_csv(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    """
    Upload a CSV of leads (name, company, website, email). Parses + cleans the
    rows, then enriches each in the background so the request returns instantly
    (the full pipeline is slow and would otherwise time out on Railway).
    """
    content = await file.read()
    text = content.decode("utf-8", errors="ignore")
    reader = csv.DictReader(io.StringIO(text))

    rows = []
    for row in reader:
        row = {k.lower().strip(): (v or "").strip() for k, v in row.items()}
        rows.append({
            "name": row.get("name", ""),
            "company": row.get("company", ""),
            "website": row.get("website", "") or row.get("url", ""),
            "email": row.get("email", ""),
        })

    background_tasks.add_task(_process_csv_rows, rows)
    return {
        "status": "processing",
        "estimated_count": len(rows),
        "message": f"Enriching {len(rows)} leads in the background. "
                   "Click ↻ Refresh on the dashboard to watch them appear.",
    }


@app.post("/find-emails")
def find_emails_endpoint(payload: FindEmailsInput):
    """
    Bonus feature: permutation-generate likely work emails for a lead and
    verify the domain via MX records. Self-contained — never touches the
    pipeline. Splits the name into first/last and returns the guesses.
    """
    parts = (payload.name or "").strip().split()
    first = parts[0] if parts else ""
    last = parts[-1] if len(parts) > 1 else ""
    results = find_emails(first, last, payload.company_domain)
    return {
        "domain": payload.company_domain,
        "verified": [r for r in results if r["domain_valid"]],
        "likely": [r for r in results if not r["domain_valid"]],
        "results": results,
    }


@app.get("/pipeline-status")
def pipeline_status():
    """
    Live view of in-flight + recently finished enrichment jobs, with the
    current stage per lead. Drives the Pipeline status screen.
    """
    now = time.time()
    with _status_lock:
        # drop finished jobs older than 90s so the list stays current
        stale = [jid for jid, j in PIPELINE_JOBS.items()
                 if j["finished"] and now - j["finished"] > 90]
        for jid in stale:
            PIPELINE_JOBS.pop(jid, None)
        jobs = sorted(PIPELINE_JOBS.values(), key=lambda j: j["started"], reverse=True)
    active = [j for j in jobs if j["status"] == "running"]
    return {"active": active, "recent": jobs}


@app.post("/preview-icp")
def preview_icp(payload: PreviewIcpInput):
    """
    Score a free-text sample lead against the current ICP — powers the live
    preview on the ICP config screen. Does NOT store anything.
    """
    cfg = load_config()
    profile = {
        "name": payload.name,
        "company": payload.company,
        "company_domain": "",
        "fields": {"description": {"value": payload.description,
                                   "confidence": "high", "source": "manual"}},
    }
    fit = score_icp_fit(profile, cfg["icp"])
    return {
        "icp_score": fit["score"],
        "breakdown": fit["breakdown"],
        "reasoning": fit["reasoning"],
        "disqualified": fit["disqualified"],
    }


@app.post("/sequence/{lead_id}")
def sequence_endpoint(lead_id: int):
    """
    Bonus: build a 3-step outreach sequence (initial / +3d / +7d) for a stored
    lead, returning the steps plus a ready-to-import CSV string.
    """
    lead = get_lead(lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    profile = lead.get("profile", {}) or {}
    profile.setdefault("name", lead.get("name", ""))
    profile.setdefault("company", lead.get("company", ""))
    qual = {"buying_signals": lead.get("buying_signals", [])}
    steps = build_sequence(profile, qual)
    csv_text = sequence_to_csv(lead.get("company", ""), steps)
    return {"lead_id": lead_id, "sequence": steps, "csv": csv_text}


@app.post("/discover-leads")
def discover_leads_endpoint(payload: DiscoverInput):
    """
    Bonus: domain-level discovery. Scrape the company's team/about pages and
    extract individual people (name + title) to seed as leads.
    """
    if not payload.domain:
        raise HTTPException(400, "Provide a company domain.")
    people = discover_leads(payload.domain)
    return {"domain": payload.domain, "count": len(people), "people": people}


@app.get("/leads")
def list_leads():
    """All stored leads — for the dashboard table."""
    return {"leads": get_all_leads()}


@app.get("/lead/{lead_id}")
def lead_detail(lead_id: int):
    """Full detail for one lead."""
    lead = get_lead(lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    return lead


@app.post("/sync/{lead_id}")
def sync_to_crm(lead_id: int):
    """Push a stored lead to Notion (dedup handled in crm.py)."""
    lead = get_lead(lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    result = sync_lead(lead)
    update_sync_status(lead_id, result["status"])
    return result


@app.get("/icp")
def get_icp():
    """Return the current ICP config (for the config screen)."""
    return load_config()