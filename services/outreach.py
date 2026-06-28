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


# Per-tone templated scaffolding. The LLM only writes the opener + value
# paragraph; everything here is fixed so it is always clean and correctly ordered.
VARIANTS = {
    "direct": {
        "subject": "A faster way to reach more patients at {company}",
        "bridge": "",
        "cta": "Would you be open to a 15-minute call this week to see if it fits?",
    },
    "consultative": {
        "subject": "Helping {company} expand patient screening",
        "bridge": ("We work specifically with eye-care and hospital teams, so the "
                   "fit with {company} could be strong."),
        "cta": ("If this is relevant, I'd love to share how similar providers have "
                "expanded screening capacity — could we find 20 minutes next week?"),
    },
}


def _collapse_repeats(text: str) -> str:
    """Repetition guard: collapse consecutive duplicate words (the 0.5B loops)."""
    out = []
    for w in text.split():
        if not out or out[-1].lower() != w.lower():
            out.append(w)
    return " ".join(out)


def _sanitize(text: str) -> str:
    """
    Clean a raw LLM fragment into a single tidy line: drop markdown (#, *, _,
    `, >, ---), quotes, and newlines; collapse repeats and whitespace.
    """
    if not text:
        return ""
    text = text.replace("\r", " ").replace("\n", " ")
    text = re.sub(r"-{2,}", " ", text)          # --- separators
    text = re.sub(r"[#*_`>]+", " ", text)        # markdown emphasis/headers/quotes
    text = text.replace('"', "").replace("“", "").replace("”", "")
    text = re.sub(r"^(?:subject|greeting|opener|body|note)\s*:\s*", "", text,
                  flags=re.IGNORECASE)           # stray labels
    text = _collapse_repeats(text)
    text = re.sub(r"\s+", " ", text).strip().strip("'").strip()
    return text


def _limit_sentences(text: str, n: int) -> str:
    """
    Keep at most n sentences. Drops a trailing incomplete sentence (the 0.5B
    often runs into the token cap mid-sentence) when at least one complete
    sentence remains, then guarantees terminal punctuation.
    """
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text) if p.strip()]
    parts = parts[:n]
    if len(parts) > 1 and parts[-1][-1] not in ".!?":
        parts = parts[:-1]            # drop a dangling fragment
    result = " ".join(parts).strip()
    if result and result[-1] not in ".!?":
        result += "."                 # close an only-sentence that got clipped
    return result


def _scrub_placeholders(text: str, recipient: str) -> str:
    """
    Replace any recipient placeholder the model leaked (e.g. [Name],
    [Recipient's name], [Recipient]) with the actual recipient. Applied at the
    source of every LLM fragment so it covers all callers (outreach + sequence).
    """
    return _PLACEHOLDER_RE.sub(recipient, text)


def _gen_opener(company: str, hook: str, recipient: str) -> str:
    """LLM call #1 — one grounded opening sentence (small bounded task)."""
    prompt = (
        f"You are a sales rep emailing {company}. Write ONE short opening sentence "
        f"(max 30 words) from your point of view that references this specific fact:\n"
        f"\"{hook}\"\n"
        "Start with \"I noticed\" or \"I saw\". Output ONLY the sentence — no quotes, "
        "no label, no greeting, no sign-off, no markdown."
    )
    raw = generate(prompt, max_tokens=40, temperature=0.5)
    sentence = _limit_sentences(_sanitize(raw), 1)
    if len(sentence) < 15:                        # empty/garbage fallback
        sentence = f"I noticed {hook}."
    return _scrub_placeholders(sentence, recipient)


def _gen_value(company: str, product: dict, recipient: str) -> str:
    """LLM call #2 — a 2-3 sentence value paragraph (small bounded task)."""
    prompt = (
        f"Write 2 to 3 short sentences explaining how {product['name']} helps a "
        f"company like {company}. Base them strictly on this value proposition:\n"
        f"\"{product['value_proposition']}\"\n"
        "Write plainly from the sales rep's point of view (\"we help...\"). Do NOT "
        "invent statistics, dates, prices, or prior conversations. No greeting, no "
        "subject, no sign-off, no markdown, no lists. Output only the sentences."
    )
    raw = generate(prompt, max_tokens=90, temperature=0.5)
    paragraph = _limit_sentences(_sanitize(raw), 3)
    if len(paragraph) < 15:                       # empty/garbage fallback
        paragraph = f"At {product['name']}, {product['value_proposition']}"
    return _scrub_placeholders(paragraph, recipient)


def _generate_variant(tone_key, spec, recipient, company, product, hook):
    """
    Hybrid assembly: the LLM writes only the opener + value paragraph; Python
    templates the subject, greeting, optional bridge, CTA, and sign-off and
    assembles them in a fixed, always-clean order.
    """
    sender = product["name"]
    opener = _gen_opener(company, hook, recipient)
    value = _gen_value(company, product, recipient)

    subject = spec["subject"].format(company=company)
    parts = [f"Hi {recipient},", "", opener, "", value]

    bridge = spec["bridge"].format(company=company) if spec["bridge"] else ""
    if bridge:
        parts += ["", bridge]
    parts += ["", spec["cta"], "", f"Best regards,\n[Your Name]\n{sender}"]

    body = "\n".join(parts)
    return {"tone": tone_key, "subject": subject, "body": body}


# a line that is ONLY a markdown/separator rule, e.g. ---  ***  ===  ___
_SEP_RE = re.compile(r"^\s*([-*=_])\1{2,}\s*$")
# leading markdown header markers, e.g. "### " or "#"
_MD_HEADER_RE = re.compile(r"^\s*#{1,6}\s*")
# the small model's trailing meta-commentary (NOT real email content)
_META_PREFIXES = (
    "note:", "greeting:", "this email", "p.s. the", "p.s. this",
    "explanation", "here is the", "here's the", "the email above",
    "in this email", "i have written", "i've written",
)
# literal placeholders the model sometimes leaves for the RECIPIENT
# (deliberately excludes "[Your Name]", which is the intended sign-off token)
_PLACEHOLDER_RE = re.compile(
    r"\[\s*(?:recipient['’]?s\s+name|recipient|name)\s*\]", re.IGNORECASE
)


def _strip_markdown(text: str) -> str:
    """Drop leading #/##/### header markers from a single line."""
    return _MD_HEADER_RE.sub("", text)


def _has_signoff(body: str, sender: str) -> bool:
    """
    True if the last few lines already contain a sign-off. Note: the sender
    name legitimately appears mid-body ("At {sender}, we..."), so it only
    counts as a sign-off when it stands on its own line near the end.
    """
    tail = [ln.strip() for ln in body.splitlines() if ln.strip()][-3:]
    tail_text = " ".join(tail).lower()
    keywords = ("regards", "sincerely", "cheers", "best,", "best wishes",
                "warm wishes", "thanks,", "thank you,", "[your name]")
    if any(k in tail_text for k in keywords):
        return True
    return bool(sender) and any(ln.lower() == sender.lower() for ln in tail)


def _clean_email(raw, company, recipient, product, sender):
    raw = raw.strip()
    lines = raw.splitlines()

    # 1. parse subject — tolerate "### Subject:" and strip markdown from it
    subject = ""
    body_start = 0
    for i, line in enumerate(lines):
        probe = _strip_markdown(line).strip()
        if probe.lower().startswith("subject:"):
            subject = probe.split(":", 1)[1].strip()
            body_start = i + 1
            break
    # strip stray markdown emphasis/header chars around the subject text
    subject = re.sub(r"^[#*\s]+|[#*\s]+$", "", subject)

    # 2. clean the body line by line:
    #    - drop standalone separator lines (---, ***, ===)
    #    - strip leading markdown headers (### ...) from any line
    #    - STOP at the first trailing meta-commentary line (Bug 2: only cut
    #      meta, never real content)
    cleaned = []
    for line in lines[body_start:]:
        if _SEP_RE.match(line):
            continue
        if _META_PREFIXES and line.strip().lower().startswith(_META_PREFIXES):
            break
        cleaned.append(_strip_markdown(line))
    body = "\n".join(cleaned).strip()

    # 3. replace leftover recipient placeholders with the real recipient
    body = _PLACEHOLDER_RE.sub(recipient, body)

    # 4. fallbacks for empty/malformed output
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

    # 5. guarantee a sign-off — if trimming left the email cut off, add one
    if not _has_signoff(body, sender):
        body = f"{body.rstrip()}\n\nBest regards,\n[Your Name]\n{sender}"

    return subject, body


def generate_outreach(profile, qualification):
    config = load_config()
    product = config["product"]
    lead_name = profile.get("name", "")
    company = profile.get("company", "")
    recipient = lead_name if lead_name else f"the {company} team"
    hook = _pick_hook(profile, qualification, company)

    emails = []
    for tone_key, spec in VARIANTS.items():
        emails.append(_generate_variant(tone_key, spec, recipient, company, product, hook))
    return emails