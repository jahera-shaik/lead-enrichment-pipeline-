"""
Bonus feature: domain-level lead discovery.

Given just a company domain, scrape the team / about / leadership page and
use the local LLM to extract individual people (name + title). Self-contained:
reuses the scraper + llm helpers, never raises, returns [] on failure.

Honest about limits: LinkedIn's company "people" section is auth-walled on free
infra (see scraper.scrape_linkedin), so discovery here is website-team-page based.
"""
from services.scraper import scrape_website, domain_from_url
from services.llm import generate_json


def discover_leads(domain: str, max_people: int = 8) -> list[dict]:
    """Return [{name, title}] discovered from the company's team/about pages."""
    try:
        d = (domain or "").strip()
        if not d:
            return []
        if not d.startswith("http"):
            d = "https://" + d
        clean = domain_from_url(d)

        site = scrape_website(d)
        text = site.get("text", "") if isinstance(site, dict) else ""
        if len(text) < 100:
            return []

        prompt = (
            "From the company website text below, extract individual PEOPLE who "
            "work there (founders, executives, team members) with their job title. "
            "Only include real person names actually present in the text — do NOT "
            "invent anyone. If none are found, return an empty list.\n\n"
            f"Website text (truncated):\n{text[:3000]}\n\n"
            'Return ONLY a JSON list like: '
            '[{"name": "Jane Doe", "title": "CEO"}]'
        )
        result = generate_json(prompt, max_tokens=300)

        people = result if isinstance(result, list) else result.get("people", []) \
            if isinstance(result, dict) and "_parse_error" not in result else []

        out = []
        seen = set()
        for p in people:
            if not isinstance(p, dict):
                continue
            name = str(p.get("name", "")).strip()
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            out.append({
                "name": name,
                "title": str(p.get("title", "")).strip(),
                "company_domain": clean,
            })
            if len(out) >= max_people:
                break
        return out
    except Exception:
        return []
