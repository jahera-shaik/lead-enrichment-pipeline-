import re
import os
from services.llm import generate
from services.icp import load_config

CONFIG_PATH = os.getenv("CONFIG_PATH", "config/settings.json")


def _lead_facts(profile: dict, qualification: dict) -> str:
    facts = []
    fields = profile.get("fields", {})
    if "description" in fields:
        facts.append(f"What they do: {fields['description']['value']}")
    if "industry" in fields:
        facts.append(f"Industry: {fields['industry']['value']}")
    if "tech_stack" in fields:
        facts.append(f"Tech they use: {', '.join(fields['tech_stack']['value'])}")
    signals = qualification.get("buying_signals", [])
    if signals:
        facts.append("Recent news / activity:")
        for s in signals[:3]:
            facts.append(f"  - {s['signal']}")
    return "\n".join(facts) if facts else "Limited public information available."


def _pick_hook(profile: dict, qualification: dict, company: str) -> str:
    signals = qualification.get("buying_signals", [])
    if signals:
        return signals[0]["signal"]
    fields = profile.get("fields", {})
    if "description" in fields:
        return f"{company}: {fields['description']['value']}"
    return f"{company}'s work in the healthcare space"


VARIANTS = {
    "direct": "Direct and concise (3-4 short sentences). Gets to the point fast.",
    "consultative": "Consultative and warm (5-6 sentences). Shows you understand their world before asking.",
}


def _generate_variant(tone_key, tone_desc, lead_name, company, facts, product, hook):
    recipient = lead_name if lead_name else f"the {company} team"
    sender = product["name"]

    prompt = (
        "Write a complete, ready-to-send B2B sales email. "
        "Output ONLY the email itself — no notes, no explanations, no commentary, "
        "no labels like 'Greeting:' or 'Note:'. Stop after the sign-off.\n\n"
        f"Sender company: {sender} — {product['description']}\n"
        f"Sender value proposition: {product['value_proposition']}\n"
        f"Recipient: {recipient} at {company}\n\n"
        f"The first sentence MUST reference this specific fact about them:\n\"{hook}\"\n\n"
        f"Useful context:\n{facts}\n\n"
        f"Tone: {tone_desc}\n"
        "Write from the sales rep's point of view ('I noticed...'). "
        f"Always refer to the sender as {sender}. End with a clear call to action "
        "(a short call this week) and a sign-off.\n\n"
        "Format:\n"
        "Subject: <subject line>\n"
        "<greeting, then the email body, then>\n"
        "Best regards,\n[Your Name]\n" + sender + "\n\n"
        "Write the email now:"
    )

    raw = generate(prompt, max_tokens=420, temperature=0.6)
    subject, body = _clean_email(raw, company, recipient, product, sender)
    return {"tone": tone_key, "subject": subject, "body": body}


def _clean_email(raw, company, recipient, product, sender):
    raw = raw.strip()

    # 1. parse subject
    subject = ""
    lines = raw.splitlines()
    body_start = 0
    for i, line in enumerate(lines):
        if line.strip().lower().startswith("subject:"):
            subject = line.split(":", 1)[1].strip()
            body_start = i + 1
            break
    body = "\n".join(lines[body_start:]).strip()

    # 2. HARD STOP: cut everything after the sign-off line (sender name).
    #    This removes the 0.5B's meta-commentary ("Note:", "Greeting:", etc.)
    stop_markers = [sender, "[Your Name]", "Best regards", "Warm regards", "----", "---"]
    cut_at = len(body)
    # find the sign-off (sender name) and keep up to the line after it
    idx = body.find(sender)
    if idx != -1:
        # keep through the sender line, drop the rest
        end = body.find("\n", idx)
        cut_at = len(body) if end == -1 else end
        body = body[:cut_at].strip()
    else:
        # fallback: cut at first meta marker if present
        for m in ["\nNote:", "\nGreeting", "\nThis email", "\n----", "\n---"]:
            j = body.find(m)
            if j != -1:
                body = body[:j].strip()
                break

    # 3. fallbacks
    if not subject or "<" in subject:
        subject = f"A faster way to reach more patients at {company}"
    if not body or len(body) < 40:
        body = (
            f"Hi {recipient},\n\n"
            f"I came across {company} and wanted to reach out. "
            f"At {sender}, {product['value_proposition']}\n\n"
            f"Would you be open to a short call this week to see if it's a fit?\n\n"
            f"Best regards,\n[Your Name]\n{sender}"
        )
    return subject, body


def generate_outreach(profile, qualification):
    config = load_config()
    product = config["product"]
    lead_name = profile.get("name", "")
    company = profile.get("company", "")
    facts = _lead_facts(profile, qualification)
    hook = _pick_hook(profile, qualification, company)

    emails = []
    for tone_key, tone_desc in VARIANTS.items():
        emails.append(_generate_variant(tone_key, tone_desc, lead_name, company, facts, product, hook))
    return emails