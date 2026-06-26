from services.crm import sync_lead

lead = {
    "name": "Dr. Test Sync",
    "company": "Apollo Hospitals",
    "company_domain": "apollohospitals.com",
    "email": "test@apollohospitals.com",
    "icp_score": 63.0,
    "combined_score": 67.5,
    "buying_signals": [
        {"strength": "high", "signal": "Apollo expands India footprint with 200-bed hospital"},
        {"strength": "medium", "signal": "Apollo launches clinical book series"},
    ],
    "emails": [
        {"tone": "direct", "subject": "Faster screening at Apollo", "body": "Hi, ..."},
        {"tone": "consultative", "subject": "Helping Apollo reach more patients", "body": "Hi, ..."},
    ],
}

print("First sync (should CREATE):")
r1 = sync_lead(lead)
print(" ", r1)

print("\nSecond sync, same lead (should UPDATE, not duplicate):")
lead["combined_score"] = 80.0  # changed value
r2 = sync_lead(lead)
print(" ", r2)