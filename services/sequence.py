"""
Bonus feature: 3-step outreach sequence builder.

Builds an initial email + a 3-day follow-up + a 7-day final bump. Uses the same
HYBRID approach as services/outreach.py: the local 0.5B model writes only small
bounded pieces (a grounded opener + a short value/follow-up paragraph) and Python
templates the subject, greeting, CTA, and sign-off — reliable on a tiny CPU model.

Self-contained: imports the outreach helpers rather than duplicating them.
Exportable as a CSV importable into any email-sending tool.
"""
import csv
import io

from services.icp import load_config
from services.outreach import _pick_hook, _gen_opener, _gen_value, _limit_sentences


# Per-step templated scaffolding. Only `opener` + `value` come from the LLM;
# everything below is fixed so the structure is always clean and ordered.
STEPS = [
    {
        "key": "initial", "day": 0,
        "subject": "A faster way to reach more patients at {company}",
        "lead_in": "",
        "use_opener": True,
        "value_sentences": 3,
        "cta": "Would you be open to a 15-minute call this week to see if it fits?",
    },
    {
        "key": "follow_up", "day": 3,
        "subject": "Following up on my note, {company}",
        "lead_in": "I wanted to follow up on my note from earlier this week.",
        "use_opener": True,
        "value_sentences": 2,
        "cta": ("Even a quick 10-minute call would help me see if there's a fit — "
                "open to it?"),
    },
    {
        "key": "final_bump", "day": 7,
        "subject": "One last note for {company}",
        "lead_in": "I know things get busy, so I'll keep this brief.",
        "use_opener": False,
        "value_sentences": 1,
        "cta": ("If now isn't the right time, no problem at all — just let me know "
                "and I'll close the loop."),
    },
]


def _generate_step(step, recipient, company, product, sender, hook):
    """Hybrid assembly for one sequence step (mirrors outreach._generate_variant)."""
    # _gen_opener/_gen_value scrub recipient placeholders at the source
    opener = _gen_opener(company, hook, recipient) if step["use_opener"] else ""
    value = _gen_value(company, product, recipient)
    if step["value_sentences"] < 3:
        value = _limit_sentences(value, step["value_sentences"])

    subject = step["subject"].format(company=company)
    parts = [f"Hi {recipient},", ""]
    if step["lead_in"]:
        parts += [step["lead_in"], ""]
    if opener:
        parts += [opener, ""]
    parts += [value, "", step["cta"], "", f"Best regards,\n[Your Name]\n{sender}"]

    return {
        "step": step["key"],
        "day": step["day"],
        "subject": subject,
        "body": "\n".join(parts),
    }


def build_sequence(profile: dict, qualification: dict) -> list[dict]:
    """Generate the 3-step sequence (initial / +3d / +7d)."""
    config = load_config()
    product = config["product"]
    sender = product["name"]
    lead_name = profile.get("name", "")
    company = profile.get("company", "")
    recipient = lead_name if lead_name else f"the {company} team"
    hook = _pick_hook(profile, qualification, company)

    return [
        _generate_step(step, recipient, company, product, sender, hook)
        for step in STEPS
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
