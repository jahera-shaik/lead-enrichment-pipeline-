import json
from services.enrichment import enrich_lead
from services.icp import qualify_lead

# enrich a realistic healthcare-ish lead
profile = enrich_lead(
    name="Dr. Test Director",
    company="Apollo Hospitals",
    website="https://www.apollohospitals.com",
)
print("enriched:", profile["enrich_status"], "| sources:", profile["sources_used"])

result = qualify_lead(profile)

print("\n=== QUALIFICATION ===")
print("ICP score:", result["icp_score"])
print("breakdown:", result["icp_breakdown"])
print("reasoning:", result["icp_reasoning"])
print("\nbuying signals:")
for s in result["buying_signals"]:
    print(f"  - [{s['strength']}] {s['signal']}  ({s['source']})")
print("signal score:", result["buying_signal_score"])
print("\ncombined score:", result["combined_score"], "| qualified:", result["qualified"])
print("weights used:", result["weights_used"])