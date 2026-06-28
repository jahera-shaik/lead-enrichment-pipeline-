"""
Bonus feature: 3-step outreach sequence builder.

Builds an initial email + a 3-day follow-up + a 7-day final bump, each
LLM-generated and grounded in the same enriched facts as the main outreach.
Self-contained: reuses the outreach helpers but does not change them.
Exportable as a CSV importable into any email-sending tool.
"""
import csv
import io

from services.llm import generate
from services.icp import load_config
from services.outreach import _lead_facts, _pick_hook, _clean_email


# (step label, day offset, instruction for the LLM)
STEPS = [
    ("initial", 0, "This is the FIRST touch. Open with the specific fact below, "
                   "introduce the value proposition, and end with a soft call to action."),
    ("follow_up", 3, "This is a FOLLOW-UP sent 3 days after the first email got no "
                     "reply. Be brief and friendly, reference that you reached out "
                     "earlier, add one new angle, and re-ask for a short call."),
    ("final_bump", 7, "This is a FINAL BUMP sent 7 days after the first email. Very "
                      "short (2-3 sentences), polite, low-pressure 'breakup' tone: "
                      "offer to close the loop if the timing isn't right."),
]


def _generate_step(step_key, day, instruction, recipient, company, facts, product, sender, hook):
    prompt = (
        "Write a complete, ready-to-send B2B sales email for an outreach sequence. "
        "Output ONLY the email itself — no notes, no labels, no commentary. "
        "Stop after the sign-off.\n\n"
        f"Sender company: {sender} — {product['description']}\n"
        f"Sender value proposition: {product['value_proposition']}\n"
        f"Recipient: {recipient} at {company}\n\n"
        f"Specific fact about them to reference:\n\"{hook}\"\n\n"
        f"Useful context:\n{facts}\n\n"
        f"This email's role in the sequence: {instruction}\n"
        f"Always refer to the sender as {sender}. End with a sign-off.\n\n"
        "Format:\n"
        "Subject: <subject line>\n"
        "<greeting, then the email body, then>\n"
        "Best regards,\n[Your Name]\n" + sender + "\n\n"
        "Write the email now:"
    )
    raw = generate(prompt, max_tokens=380, temperature=0.6)
    subject, body = _clean_email(raw, company, recipient, product, sender)
    return {"step": step_key, "day": day, "subject": subject, "body": body}


def build_sequence(profile: dict, qualification: dict) -> list[dict]:
    """Generate the 3-step sequence (initial / +3d / +7d)."""
    config = load_config()
    product = config["product"]
    sender = product["name"]
    lead_name = profile.get("name", "")
    company = profile.get("company", "")
    recipient = lead_name if lead_name else f"the {company} team"
    facts = _lead_facts(profile, qualification)
    hook = _pick_hook(profile, qualification, company)

    return [
        _generate_step(key, day, instr, recipient, company, facts, product, sender, hook)
        for key, day, instr in STEPS
    ]


def sequence_to_csv(company: str, sequence: list[dict]) -> str:
    """
    Render the sequence as CSV text (one row per step). Columns chosen to
    import cleanly into common sequencing tools.
    """
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["company", "step", "send_day", "subject", "body"])
    for s in sequence:
        writer.writerow([company, s["step"], s["day"], s["subject"], s["body"]])
    return buf.getvalue()
