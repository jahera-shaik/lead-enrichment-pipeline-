from database.db import init_db, upsert_lead, get_all_leads, get_lead

init_db()

# first insert
id1 = upsert_lead({
    "name": "Asha Rao", "company": "BoltHealth",
    "company_domain": "bolthealth.com", "email": "asha@bolthealth.com",
    "icp_score": 72, "enrich_status": "enriched",
})
print("inserted id:", id1)

# SAME domain+email again, new score → should UPDATE, not duplicate
id2 = upsert_lead({
    "name": "Asha Rao", "company": "BoltHealth",
    "company_domain": "bolthealth.com", "email": "asha@bolthealth.com",
    "icp_score": 88, "enrich_status": "enriched",
})
print("second upsert id (should equal first):", id2)

# different lead
id3 = upsert_lead({
    "name": "Vikram S", "company": "NimbusAI",
    "company_domain": "nimbus.ai", "email": "vik@nimbus.ai",
    "icp_score": 55,
})

leads = get_all_leads()
print(f"\ntotal leads in DB: {len(leads)}  (expected 2, not 3)")
for l in leads:
    print(f"  - {l['name']} | {l['company']} | score={l['icp_score']}")

print(f"\nAsha's score is now: {get_lead(id1)['icp_score']}  (expected 88 — updated)")