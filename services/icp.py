import json
import os
from services.llm import generate_json

CONFIG_PATH = os.getenv("CONFIG_PATH", "config/settings.json")


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _profile_summary(profile: dict) -> str:
    """Flatten the enriched profile into readable text for the LLM."""
    lines = [
        f"Name: {profile.get('name','')}",
        f"Company: {profile.get('company','')}",
        f"Domain: {profile.get('company_domain','')}",
    ]
    for key, f in profile.get("fields", {}).items():
        val = f["value"]
        if isinstance(val, list):
            val = "; ".join(str(v) for v in val[:5])
        lines.append(f"{key}: {val}")
    return "\n".join(lines)


def _check_disqualified(profile: dict, icp: dict) -> str:
    """
    Explicit, deterministic disqualifier check — no LLM. Returns a reason
    string if disqualified, else empty string. Keeps the small model from
    confusing 'target' vs 'exclude' industries.
    """
    text = _profile_summary(profile).lower()
    dq = icp.get("disqualifiers", {})
    for bad in dq.get("industries_to_exclude", []):
        if bad.lower() in text:
            return f"matches excluded industry '{bad}'"
    for comp in dq.get("competitor_names", []):
        if comp.lower() in text:
            return f"matches competitor '{comp}'"
    return ""


def score_icp_fit(profile: dict, icp: dict) -> dict:
    """
    Semantic ICP fit scoring via the local LLM. Scores each criterion
    separately to keep prompts simple enough for a small model.
    """
    summary = _profile_summary(profile)

    prompt = (
        "You are a B2B sales analyst. Rate how well this LEAD fits an ideal "
        "customer, criterion by criterion. Higher = better fit. Use reasoning, "
        "not exact word matching (e.g. '40 engineers' fits '20-100 employees'; "
        "'Head of Platform' equals VP-level).\n\n"
        f"LEAD:\n{summary}\n\n"
        "DESIRED CUSTOMER:\n"
        f"- Should be in or related to: {', '.join(icp['target_industries'])}\n"
        f"- Size around: {icp['company_size_range']}\n"
        f"- Uses or needs: {', '.join(icp['target_tech_indicators'])}\n"
        f"- Contact seniority: {icp['min_seniority']}\n"
        f"- Located in: {', '.join(icp['target_geographies'])}\n\n"
        "For each criterion give 0-100 (use 50 if the lead data is missing). "
        "A lead in a DESIRED industry should score HIGH on industry_fit. "
        "Return ONLY this JSON:\n"
        '{"industry_fit": 75, "size_fit": 50, "tech_fit": 60, '
        '"seniority_fit": 50, "geography_fit": 80, "reasoning": "one sentence"}'
    )
    result = generate_json(prompt, max_tokens=300)
    if "_parse_error" in result or "industry_fit" not in result:
        result = generate_json(prompt, max_tokens=300)  # one retry — small models flake

    if "_parse_error" in result or "industry_fit" not in result:
        return {
            "score": 50.0, "breakdown": {},
            "reasoning": "Scoring model output unparseable; neutral default applied.",
            "disqualified": False,
        }

    disqualified = _check_disqualified(profile, icp)
    if disqualified:
        return {
            "score": 0.0, "breakdown": result,
            "reasoning": f"Disqualified: {disqualified}",
            "disqualified": True,
        }

    crit = ["industry_fit", "size_fit", "tech_fit", "seniority_fit", "geography_fit"]
    vals = [float(result.get(k, 50)) for k in crit]
    score = round(sum(vals) / len(vals), 1)
    return {
        "score": score,
        "breakdown": {k: result.get(k, 50) for k in crit},
        "reasoning": result.get("reasoning", ""),
        "disqualified": False,
    }


# keyword hints used to TYPE a confirmed signal (funding/hiring/expansion/etc.)
_SIGNAL_TYPE_HINTS = {
    "funding": ("raise", "raises", "raised", "funding", "series ", "seed", "investment", "valuation"),
    "hiring": ("hiring", "hires", "appoints", "appointed", "joins as", "names new", "new ceo", "new cto", "head of", "vp of"),
    "expansion": ("expand", "expansion", "new office", "opens", "launch", "launches", "enters", "acqui", "partnership", "partners"),
    "product": ("launches", "unveils", "introduces", "rolls out", "new product"),
}


def _signal_type(title: str) -> str:
    t = (title or "").lower()
    for kind, hints in _SIGNAL_TYPE_HINTS.items():
        if any(h in t for h in hints):
            return kind
    return "news"


def _tech_fit_signals(profile: dict, icp: dict) -> list[dict]:
    """
    Deterministic tech-stack-fit signal: if the lead's detected tech overlaps
    the ICP's target tech indicators, that's a configurable buying signal.
    Semantic-light on purpose — substring overlap is reliable for tech tokens.
    """
    fields = profile.get("fields", {})
    tech = fields.get("tech_stack", {}).get("value", []) if "tech_stack" in fields else []
    if isinstance(tech, str):
        tech = [tech]
    targets = [t.lower() for t in icp.get("target_tech_indicators", [])]
    if not tech or not targets:
        return []

    matched = []
    for item in tech:
        il = str(item).lower()
        for tgt in targets:
            if tgt in il or il in tgt:
                matched.append(item)
                break
    if not matched:
        return []
    return [{
        "signal": f"Uses {', '.join(dict.fromkeys(matched))} — matches your target tech stack",
        "strength": "medium",
        "type": "tech_fit",
        "source": "website:tech-signatures",
    }]


def detect_buying_signals(profile: dict, icp: dict) -> list[dict]:
    """
    Detect buying signals across sources:
      - news headlines (LLM-classified, typed by funding/hiring/expansion/...)
      - tech-stack fit vs the configured target tech (deterministic)
    Each signal carries strength, type, and source.
    """
    out = []

    # ---- news-based signals (LLM classification) ----
    news = profile.get("raw_news", [])
    if news:
        items = news[:6]
        numbered = "\n".join(f"{i+1}. {it['title']}" for i, it in enumerate(items))
        prompt = (
            "Classify each news headline as a B2B BUYING SIGNAL or not.\n"
            "BUYING SIGNALS (budget/growth/readiness): funding, partnership, deal, "
            "expansion, new office, senior hire, product launch, digital "
            "transformation, contract win.\n"
            "NOT signals: scandal, corruption, politics, lawsuits, opinions, awards.\n\n"
            "Examples:\n"
            "'Acme partners with Govt for digital transformation' -> high "
            "(partnership + transformation)\n"
            "'Acme raises $20M Series B' -> high (funding)\n"
            "'Acme founder comments on politics' -> none\n"
            "'Acme accused of corruption' -> none\n"
            "'Acme opens new Bangalore office' -> medium (expansion)\n\n"
            f"Headlines:\n{numbered}\n\n"
            'Return ONLY JSON mapping each number to "high"/"medium"/"low"/"none". '
            'Example: {"1": "high", "2": "none"}'
        )
        result = generate_json(prompt, max_tokens=200)
        if isinstance(result, dict) and "_parse_error" not in result:
            for i, it in enumerate(items):
                verdict = str(result.get(str(i + 1), "none")).lower().strip()
                if verdict in ("high", "medium", "low"):
                    out.append({
                        "signal": it["title"],
                        "strength": verdict,
                        "type": _signal_type(it["title"]),
                        "source": "google_news",
                    })

    # ---- tech-stack-fit signal (deterministic, configurable) ----
    out.extend(_tech_fit_signals(profile, icp))

    return out


def _signal_score(signals: list[dict]) -> float:
    """Convert signals into a 0-100 strength score."""
    if not signals:
        return 0.0
    weights = {"high": 30, "medium": 18, "low": 8}
    total = sum(weights.get(s["strength"], 10) for s in signals)
    return float(min(total, 100))


def qualify_lead(profile: dict) -> dict:
    """
    Full qualification: ICP fit + buying signals → combined score using
    configurable weights. Returns everything the UI/CRM needs.
    """
    config = load_config()
    icp = config["icp"]
    sc = config["scoring"]

    fit = score_icp_fit(profile, icp)
    signals = detect_buying_signals(profile, icp)
    sig_score = _signal_score(signals)

    combined = round(
        sc["weight_icp_fit"] * fit["score"]
        + sc["weight_buying_signals"] * sig_score,
        1,
    )
    if fit["disqualified"]:
        combined = 0.0

    return {
        "icp_score": fit["score"],
        "icp_breakdown": fit["breakdown"],
        "icp_reasoning": fit["reasoning"],
        "disqualified": fit["disqualified"],
        "buying_signals": signals,
        "buying_signal_score": sig_score,
        "combined_score": combined,
        "qualified": combined >= sc["qualification_threshold"] and not fit["disqualified"],
        "weights_used": {
            "icp_fit": sc["weight_icp_fit"],
            "buying_signals": sc["weight_buying_signals"],
            "threshold": sc["qualification_threshold"],
        },
    }