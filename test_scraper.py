import json
from services.scraper import scrape_website, scrape_google_news, scrape_linkedin

print("=== WEBSITE ===")
site = scrape_website("https://www.zoho.com")
print("status:", site["status"])
print("title:", site["title"])
print("meta:", site["meta_description"][:120])
print("tech hints:", site["tech_hints"])
print("internal pages:", site["internal_pages_scraped"])
print("text length:", len(site["text"]))
print("text preview:", site["text"][:200])

print("\n=== GOOGLE NEWS ===")
news = scrape_google_news("Aravind Eye Hospital")
print("status:", news["status"], "| items:", len(news["items"]))
for it in news["items"][:3]:
    print("  -", it["title"])

print("\n=== LINKEDIN (graceful degradation) ===")
li = scrape_linkedin("Some Person", "Some Company")
print("status:", li["status"], "| confidence:", li["confidence"])