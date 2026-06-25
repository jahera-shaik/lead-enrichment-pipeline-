from services.scraper import (
    scrape_website, scrape_google_news, scrape_linkedin, domain_from_url
)
from services.llm import generate_json


def _conf_band(score: float) -> str:
    if score >= 0.8:
        return "high"
    if score >= 0.5:
        return "medium"
    return "low"


def _field(value, confidence_score: float, source: str) -> dict:
    """Wrap an enriched field with its confidence + provenance."""
    return {
        "value": value,
        "confidence_score": round(confidence_score, 2),
        "confidence": _conf_band(confidence_score),
        "source": source,
    }


def enrich_lead(name: str = "", company: str = "", website: str = "",
                email: str = "") -> dict:
    """
    Run all sources, build a structured profile. Each field carries a
    confidence band + source. Missing sources degrade gracefully — a
    failed source never aborts the whole enrichment.
    """
    domain = ""
    if website:
        domain = domain_from_url(website)
    elif email and "@" in email:
        domain = email.split("@")[1].lower()

    profile = {
        "name": name,
        "company": company,
        "company_domain": domain,
        "email": email,
        "sources_used": [],
        "sources_failed": [],
        "fields": {},
        "raw_news": [],
    }

    # ---- 1. Website ----
    site_text = ""
    if website or domain:
        url = website or f"https://{domain}"
        site = scrape_website(url)
        if site["status"] == "ok":
            profile["sources_used"].append("website")
            site_text = site["text"]
            if site["title"]:
                profile["fields"]["company_title"] = _field(
                    site["title"], 0.9, "website")
            if site["meta_description"]:
                profile["fields"]["description"] = _field(
                    site["meta_description"], 0.85, "website")
            if site["tech_hints"]:
                profile["fields"]["tech_stack"] = _field(
                    site["tech_hints"], 0.7, "website:html-signatures")
        else:
            profile["sources_failed"].append("website")

    # ---- 2. Google News ----
    if company:
        news = scrape_google_news(company)
        if news["status"] == "ok" and news["items"]:
            profile["sources_used"].append("google_news")
            profile["raw_news"] = news["items"]
            headlines = [it["title"] for it in news["items"]]
            profile["fields"]["recent_news"] = _field(
                headlines, 0.75, "google_news")
        else:
            profile["sources_failed"].append("google_news")

    # ---- 3. LinkedIn (best-effort, expected to degrade) ----
    li = scrape_linkedin(name, company)
    if li["status"] == "blocked":
        profile["sources_failed"].append("linkedin")
    else:
        profile["sources_used"].append("linkedin")

    # ---- 4. LLM inference: extract structured fields from site text ----
    # Only if we actually got meaningful text. Inferred → lower confidence.
    if len(site_text) > 200:
        inferred = _infer_from_text(company, site_text)
        for key, val in inferred.items():
            if val and str(val).lower() not in ("unknown", "n/a", "none", ""):
                profile["fields"][key] = _field(val, 0.55, "llm-inferred:website")

    # ---- status ----
    if not profile["sources_used"]:
        profile["enrich_status"] = "failed"
    elif profile["sources_failed"]:
        profile["enrich_status"] = "partial"
    else:
        profile["enrich_status"] = "enriched"

    return profile


def _infer_from_text(company: str, text: str) -> dict:
    """Use the local LLM to pull structured attributes from website text."""
    prompt = (
        f"Company: {company}\n"
        f"Website text (truncated):\n{text[:3000]}\n\n"
        "From the text above, infer these attributes. If not determinable, "
        'use "unknown". Return JSON with exactly these keys:\n'
        '{"industry": "", "sub_industry": "", "company_size_estimate": "", '
        '"products": "", "target_market": ""}'
    )
    result = generate_json(prompt, max_tokens=300)
    if "_parse_error" in result:
        return {}
    return result