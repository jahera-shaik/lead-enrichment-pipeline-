from services.enrichment import enrich_lead
from services.icp import qualify_lead
from services.outreach import generate_outreach

profile = enrich_lead(
    name="Dr. Sangita Reddy",
    company="Apollo Hospitals",
    website="https://www.apollohospitals.com",
)
qual = qualify_lead(profile)
print("qualified:", qual["qualified"], "| score:", qual["combined_score"])
print("signals used:", [s["signal"][:50] for s in qual["buying_signals"]])

emails = generate_outreach(profile, qual)

for e in emails:
    print("\n" + "=" * 60)
    print(f"TONE: {e['tone']}")
    print(f"SUBJECT: {e['subject']}")
    print("-" * 60)
    print(e["body"])