import os
from dotenv import load_dotenv
from notion_client import Client

load_dotenv()

_notion = None
DB_ID = os.getenv("NOTION_DB_ID")


def _client():
    global _notion
    if _notion is None:
        _notion = Client(auth=os.getenv("NOTION_API_KEY"))
    return _notion


def _rich(text: str):
    return [{"text": {"content": (text or "")[:2000]}}]


def _find_existing(domain: str, email: str):
    """Find a row by domain OR email (dedup key). Returns page_id or None."""
    notion = _client()
    filters = []
    if domain:
        filters.append({"property": "Domain", "rich_text": {"equals": domain}})
    if email:
        filters.append({"property": "Email", "email": {"equals": email}})
    if not filters:
        return None

    query = {"or": filters} if len(filters) > 1 else filters[0]
    try:
        resp = notion.databases.query(database_id=DB_ID, filter=query, page_size=1)
        results = resp.get("results", [])
        return results[0]["id"] if results else None
    except Exception:
        return None


def _enriched_fields_text(lead: dict) -> str:
    """Flatten every raw enriched field with its confidence + source."""
    fields = (lead.get("profile") or {}).get("fields", {})
    lines = []
    for key, f in fields.items():
        if not isinstance(f, dict):
            continue
        val = f.get("value", "")
        if isinstance(val, list):
            val = ", ".join(str(v) for v in val)
        conf = f.get("confidence", "")
        src = f.get("source", "")
        lines.append(f"{key}: {val}  ({conf} confidence, source: {src})")
    return "\n".join(lines) or "No enriched fields."


def _icp_breakdown_text(lead: dict) -> str:
    """Per-criterion ICP breakdown + reasoning, for the CRM record."""
    bd = lead.get("icp_breakdown") or {}
    lines = [f"{k}: {v}" for k, v in bd.items()]
    reasoning = lead.get("icp_reasoning", "")
    if reasoning:
        lines.append(f"reasoning: {reasoning}")
    return "\n".join(lines) or "No breakdown."


def _build_properties(lead: dict) -> dict:
    """Map a lead dict to Notion properties matching our column names."""
    emails = lead.get("emails", [])
    draft1 = ""
    draft2 = ""
    if len(emails) >= 1:
        draft1 = f"[{emails[0].get('tone','')}] {emails[0].get('subject','')}\n\n{emails[0].get('body','')}"
    if len(emails) >= 2:
        draft2 = f"[{emails[1].get('tone','')}] {emails[1].get('subject','')}\n\n{emails[1].get('body','')}"

    signals = lead.get("buying_signals", [])
    signal_text = "\n".join(
        f"[{s.get('strength','')}/{s.get('type','news')}] {s.get('signal','')} "
        f"(source: {s.get('source','')})" for s in signals
    ) or "None detected"

    props = {
        "Name": {"title": [{"text": {"content": lead.get("name") or lead.get("company") or "Unknown"}}]},
        "Company": {"rich_text": _rich(lead.get("company", ""))},
        "Domain": {"rich_text": _rich(lead.get("company_domain", ""))},
        "Buying Signals": {"rich_text": _rich(signal_text)},
        # spec §4: push ALL raw enriched fields with confidence + the ICP breakdown
        "Enriched Fields": {"rich_text": _rich(_enriched_fields_text(lead))},
        "ICP Breakdown": {"rich_text": _rich(_icp_breakdown_text(lead))},
        "Email Draft 1": {"rich_text": _rich(draft1)},
        "Email Draft 2": {"rich_text": _rich(draft2)},
    }
    # email is a special type — only set if present and valid-ish
    email = lead.get("email", "")
    if email and "@" in email:
        props["Email"] = {"email": email}
    # numbers
    if lead.get("icp_score") is not None:
        props["ICP Score"] = {"number": float(lead["icp_score"])}
    if lead.get("combined_score") is not None:
        props["Combined Score"] = {"number": float(lead["combined_score"])}
    return props


def sync_lead(lead: dict) -> dict:
    """
    Push a lead to Notion. Updates if it already exists (dedup by
    domain/email), else creates. Returns {status, page_id}.
    status: 'synced' (created), 'updated', 'skipped' (dup w/ same data),
            or 'failed'.
    """
    notion = _client()
    domain = (lead.get("company_domain") or "").lower().strip()
    email = (lead.get("email") or "").lower().strip()

    try:
        props = _build_properties(lead)
        existing_id = _find_existing(domain, email)

        if existing_id:
            props["Status"] = {"select": {"name": "updated"}}
            notion.pages.update(page_id=existing_id, properties=props)
            return {"status": "updated", "page_id": existing_id}
        else:
            props["Status"] = {"select": {"name": "synced"}}
            page = notion.pages.create(
                parent={"database_id": DB_ID}, properties=props
            )
            return {"status": "synced", "page_id": page["id"]}

    except Exception as e:
        return {"status": "failed", "error": str(e)}