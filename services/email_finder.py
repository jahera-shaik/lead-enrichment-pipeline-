"""
Bonus feature: Email Finder.

Permutation-generates likely work emails from a name + domain, then verifies
the domain can actually receive mail by checking its MX records (no paid API).

Self-contained — does NOT touch the enrichment, ICP scoring, or outreach logic.
Everything is wrapped in try/except: this module never raises. On any failure
it returns an empty list so callers can keep going.
"""


def _slug(value: str) -> str:
    """Lowercase, keep only a-z and digits (drop spaces, dots, accents-ish)."""
    return "".join(c for c in (value or "").lower().strip() if c.isalnum())


def _clean_domain(domain: str) -> str:
    """Strip scheme/path/www so 'https://www.acme.com/x' -> 'acme.com'."""
    d = (domain or "").strip().lower()
    if "://" in d:
        d = d.split("://", 1)[1]
    d = d.split("/", 1)[0]
    if d.startswith("www."):
        d = d[4:]
    return d


def verify_domain_mx(domain: str) -> bool:
    """
    Return True if the domain has MX records (it can receive mail).

    Prefers dnspython (dns.resolver). If dnspython isn't installed, falls back
    to a stdlib socket-based lookup. Never raises — returns False on any error.
    """
    d = _clean_domain(domain)
    if not d:
        return False

    # 1. preferred: dnspython
    try:
        import dns.resolver  # type: ignore

        try:
            answers = dns.resolver.resolve(d, "MX")
            return len(answers) > 0
        except Exception:
            return False
    except ImportError:
        pass

    # 2. fallback: stdlib socket — can't read MX directly, but if the domain
    #    resolves to an address it at least exists. Best-effort "unverified".
    try:
        import socket

        socket.gethostbyname(d)
        return False  # resolves, but we couldn't confirm MX → treat as unverified
    except Exception:
        return False


PATTERNS = [
    ("first", lambda f, l: f),
    ("first.last", lambda f, l: f"{f}.{l}" if l else ""),
    ("flast", lambda f, l: f"{f[0]}{l}" if (f and l) else ""),
    ("firstl", lambda f, l: f"{f}{l[0]}" if (f and l) else ""),
    ("last", lambda f, l: l),
    ("first_last", lambda f, l: f"{f}_{l}" if l else ""),
]


def find_emails(first_name: str, last_name: str, domain: str) -> list[dict]:
    """
    Generate common work-email permutations and check the domain's MX records.

    Returns a list of {"email", "pattern", "domain_valid"} dicts. Entries are
    ordered "verified" first (domain has MX) then "likely" (domain unverified).
    Never raises — returns [] on any failure.
    """
    try:
        first = _slug(first_name)
        last = _slug(last_name)
        d = _clean_domain(domain)
        if not first and not last:
            return []
        if not d:
            return []

        domain_valid = verify_domain_mx(d)

        seen = set()
        results = []
        for pattern, fn in PATTERNS:
            try:
                local = fn(first, last)
            except Exception:
                local = ""
            if not local or local in seen:
                continue
            seen.add(local)
            results.append({
                "email": f"{local}@{d}",
                "pattern": pattern,
                "domain_valid": domain_valid,
            })

        # verified (domain has MX) first, then likely guesses
        results.sort(key=lambda r: not r["domain_valid"])
        return results
    except Exception:
        return []
