import re
import requests
import feedparser
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import socket
socket.setdefaulttimeout(8)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0 Safari/537.36"
}
TIMEOUT = 6


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def domain_from_url(url: str) -> str:
    if not url.startswith("http"):
        url = "https://" + url
    return urlparse(url).netloc.replace("www.", "").lower()


def scrape_website(url: str) -> dict:
    """
    Scrape a company site: homepage + about/pricing/careers pages.
    Returns raw text + meta + tech hints. Never raises — returns
    {'status': 'failed', ...} on error so the pipeline keeps going.
    """
    if not url.startswith("http"):
        url = "https://" + url

    result = {
        "source": "website",
        "status": "ok",
        "url": url,
        "domain": domain_from_url(url),
        "title": "",
        "meta_description": "",
        "text": "",
        "tech_hints": [],
        "internal_pages_scraped": [],
    }

    try:
        resp = requests.get(url, headers=HEADERS, timeout=(4,5))
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # title + meta description
        if soup.title:
            result["title"] = _clean(soup.title.get_text())
        meta = soup.find("meta", attrs={"name": "description"})
        if meta and meta.get("content"):
            result["meta_description"] = _clean(meta["content"])

        # tech hints from raw HTML (meta generator, common scripts)
        html_lower = resp.text.lower()
        tech_signatures = {
            "react": "react", "next.js": "_next", "vue": "vue",
            "angular": "ng-version", "wordpress": "wp-content",
            "shopify": "cdn.shopify", "hubspot": "hs-scripts",
            "google analytics": "gtag", "segment": "segment.com",
            "intercom": "intercom", "stripe": "js.stripe.com",
        }
        for name, sig in tech_signatures.items():
            if sig in html_lower:
                result["tech_hints"].append(name)

        # collect homepage visible text
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        texts = [_clean(soup.get_text(" "))]

        # find + scrape key internal pages
        wanted = ("about", "pricing", "careers", "jobs", "product", "team")
        links = {}
        for a in soup.find_all("a", href=True):
            href = a["href"].lower()
            for w in wanted:
                if w in href and w not in links:
                    links[w] = urljoin(url, a["href"])

        for w, link in list(links.items())[:2]:  # cap to 4 to stay fast
            try:
                r2 = requests.get(link, headers=HEADERS, timeout=(4,5))
                if r2.ok:
                    s2 = BeautifulSoup(r2.text, "html.parser")
                    for tag in s2(["script", "style", "noscript"]):
                        tag.decompose()
                    texts.append(_clean(s2.get_text(" ")))
                    result["internal_pages_scraped"].append(w)
            except requests.RequestException:
                continue  # one page failing never kills the scrape

        # cap total text so we don't blow the LLM context later
        result["text"] = " ".join(texts)[:6000]

    except requests.RequestException as e:
        result["status"] = "failed"
        result["error"] = str(e)

    return result


def scrape_google_news(company: str, max_items: int = 6) -> dict:
    """
    Pull recent news headlines via Google News RSS (no API key needed).
    Returns {'status', 'items': [{title, link, published, summary}]}.
    """
    result = {"source": "google_news", "status": "ok", "items": []}
    try:
        q = requests.utils.quote(f'"{company}"')
        rss = f"https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"
        feed = feedparser.parse(rss)
        for entry in feed.entries[:max_items]:
            result["items"].append({
                "title": _clean(entry.get("title", "")),
                "link": entry.get("link", ""),
                "published": entry.get("published", ""),
                "summary": _clean(entry.get("summary", ""))[:300],
            })
        if not result["items"]:
            result["status"] = "empty"
    except Exception as e:
        result["status"] = "failed"
        result["error"] = str(e)
    return result


def scrape_linkedin(name: str = "", company: str = "") -> dict:
    """
    Best-effort placeholder. Server-side LinkedIn scraping is blocked on
    free infra (auth wall). We mark it degraded so the pipeline continues;
    real LinkedIn data comes through the Chrome extension DOM later.
    """
    return {
        "source": "linkedin",
        "status": "blocked",
        "confidence": "low",
        "note": "LinkedIn server-side scrape unavailable; use extension DOM.",
        "data": {},
    }