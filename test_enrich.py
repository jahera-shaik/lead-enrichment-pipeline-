import json
from services.enrichment import enrich_lead

profile = enrich_lead(
    name="Test Contact",
    company="Zoho",
    website="https://www.zoho.com",
)

print("=== ENRICHED PROFILE ===")
print("status:", profile["enrich_status"])
print("sources used:", profile["sources_used"])
print("sources failed:", profile["sources_failed"])
print("\n--- fields (with confidence) ---")
for key, f in profile["fields"].items():
    val = f["value"]
    if isinstance(val, list):
        val = val[:2]  # short preview
    print(f"  {key}: {val}  [{f['confidence']} / {f['source']}]")
print(f"\nnews headlines pulled: {len(profile['raw_news'])}")