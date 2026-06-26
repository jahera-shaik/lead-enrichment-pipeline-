import os
from services.llm import generate
from services.icp import load_config

CONFIG_PATH = os.getenv("CONFIG_PATH", "config/settings.json")


def _lead_facts(profile: dict, qualification: dict) -> str:
    """Pull concrete, specific facts the email can reference."""
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
        facts.append("Recent activity / news:")
        for s in signals[:3]:
            facts.append(f"  - {s['signal']}")

    return "\n".join(facts) if facts else "Limited public information available."


VARIANTS = {
    "direct": (
        "Direct and concise. Short, punchy, gets to the point in 3-4 sentences. "
        "Respects the reader's time. One clear ask."
    ),
    "consultative": (
        "Consultative and detailed. Warmer, shows you understand their world, "
        "references their specific situation, offers insight before asking. "
        "5-7 sentences."
    ),
}


def _generate_variant(tone_key: str, tone_desc: str, lead_name: str,
                      company: str, facts: str, product: dict,
                      hook: str) -> dict:
    greeting = f"Hi {lead_name.split()[-1]}," if lead_name else f"Hi {company} team,"

    # Opener: explicit perspective (WE are the sender writing TO them).
    opener_prompt = (
        f"You are a sales rep at {product['name']} writing to {company}. "
        f"Write ONE opening sentence that shows you noticed this about {company}: "
        f"\"{hook}\". Write it from the rep's point of view (e.g. 'I saw that "
        f"{company}...' or 'I noticed {company} recently...'). "
        f"Max 28 words. Output ONLY that one sentence."
    )
    opener = generate(opener_prompt, max_tokens=70, temperature=0.5).strip().strip('"')
    opener = opener.split("\n")[0].strip()
    # guard against degenerate repetition loops from the small model
    words = opener.split()
    if len(words) != len(set(words)) and len(words) > 12:
        # too many repeated words → collapse consecutive dupes
        deduped = []
        for w in words:
            if not deduped or deduped[-1].lower() != w.lower():
                deduped.append(w)
        opener = " ".join(deduped)
    # final length cap
    opener = " ".join(opener.split()[:30])

    # Pitch: pre-written, lightly varied by tone — do NOT ask the model to
    # paraphrase an instruction (it echoes it). Use the value prop directly.
    vp = product["value_proposition"]
    if tone_key == "direct":
        pitch = (f"At {product['name']}, we help eye-care and hospital teams "
                 f"screen more patients faster with portable, AI-assisted "
                 f"diagnostics — expanding reach while lowering cost per screening.")
        cta = "Would you be open to a 15-minute call this week to see if it fits?"
        body = f"{greeting}\n\n{opener}\n\n{pitch}\n\n{cta}\n\nBest regards,\n[Your Name]\n{product['name']}"
        subject = f"A faster way to screen more patients at {company}"
    else:
        pitch = (f"{vp} For a provider like {company}, that can mean reaching more "
                 f"patients — including in underserved areas — without adding cost "
                 f"or staff load.")
        cta = ("If this is relevant, I'd love to share how similar providers have "
               "expanded screening capacity — could we find 20 minutes next week?")
        body = (f"{greeting}\n\n{opener}\n\n{pitch}\n\nWe work specifically with "
                f"eye-care and hospital teams, so the fit with {company} could be strong. "
                f"{cta}\n\nWarm regards,\n[Your Name]\n{product['name']}")
        subject = f"Helping {company} reach more patients, affordably"

    return {"tone": tone_key, "subject": subject, "body": body}

def _split_email(raw: str, company: str = "") -> tuple[str, str]:
    """Parse subject (first 'Subject:' line) + body. Robust to format drift."""
    raw = raw.strip()
    lines = raw.splitlines()
    subject, body_start = "", 0

    for i, line in enumerate(lines):
        if line.strip().lower().startswith("subject:"):
            subject = line.split(":", 1)[1].strip()
            body_start = i + 1
            break

    body = "\n".join(lines[body_start:]).strip()
    if not body:
        body = raw

    if not subject or "<" in subject or subject.lower() in ("subject", ""):
        subject = f"A quick idea for {company}" if company else "A quick idea for your team"
    return subject, body


def generate_outreach(profile: dict, qualification: dict) -> list[dict]:
    """
    Generate 2 personalized email variants (direct + consultative).
    Each is anchored to the most specific known fact (top buying signal).
    Returns list of {tone, subject, body}.
    """
    config = load_config()
    product = config["product"]

    lead_name = profile.get("name", "")
    company = profile.get("company", "")
    facts = _lead_facts(profile, qualification)

    signals = qualification.get("buying_signals", [])
    if signals:
        hook = signals[0]["signal"]
    elif "description" in profile.get("fields", {}):
        hook = f"{company}'s work: {profile['fields']['description']['value']}"
    else:
        hook = f"{company}'s presence in the healthcare space"

    emails = []
    for tone_key, tone_desc in VARIANTS.items():
        emails.append(
            _generate_variant(tone_key, tone_desc, lead_name, company,
                              facts, product, hook)
        )
    return emails