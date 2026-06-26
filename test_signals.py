from services.enrichment import enrich_lead
from services.icp import detect_buying_signals, load_config

profile = enrich_lead(company="Zoho", website="https://www.zoho.com")
print("news pulled:", len(profile["raw_news"]))
for it in profile["raw_news"][:6]:
    print("  -", it["title"])

icp = load_config()["icp"]
signals = detect_buying_signals(profile, icp)
print("\nsignals detected:", len(signals))
for s in signals:
    print(f"  - [{s['strength']}] {s['signal']}")