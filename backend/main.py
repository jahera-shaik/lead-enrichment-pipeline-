import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
import csv
import io
import time

from services.enrichment import enrich_lead
from services.icp import qualify_lead, load_config
from services.outreach import generate_outreach
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


def run_pipeline(name="", company="", website="", email="") -> dict:
    """The full pipeline: enrich -> qualify -> emails -> store. Returns the lead record."""
    t0 = time.time()
    profile = enrich_lead(name=name, company=company, website=website, email=email)
    print(f"[TIMING] enrich: {time.time()-t0:.1f}s")

    t1 = time.time()
    qual = qualify_lead(profile)
    print(f"[TIMING] qualify: {time.time()-t1:.1f}s")

    t2 = time.time()
    emails = generate_outreach(profile, qual)
    print(f"[TIMING] emails: {time.time()-t2:.1f}s")

    lead_record = {
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
    lead_id = upsert_lead(lead_record)
    lead_record["id"] = lead_id
    return lead_record


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


@app.post("/upload-csv")
async def upload_csv(file: UploadFile = File(...)):
    """Upload a CSV of leads (name, company, website, email). Enriches each."""
    content = await file.read()
    text = content.decode("utf-8", errors="ignore")
    reader = csv.DictReader(io.StringIO(text))

    results = []
    for row in reader:
        row = {k.lower().strip(): (v or "").strip() for k, v in row.items()}
        record = run_pipeline(
            name=row.get("name", ""),
            company=row.get("company", ""),
            website=row.get("website", "") or row.get("url", ""),
            email=row.get("email", ""),
        )
        results.append({
            "id": record["id"], "company": record["company"],
            "combined_score": record["combined_score"], "qualified": record["qualified"],
        })
    return {"processed": len(results), "leads": results}


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