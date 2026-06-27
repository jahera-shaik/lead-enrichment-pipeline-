import streamlit as st
import requests
import pandas as pd

API = "http://127.0.0.1:8000"

st.set_page_config(page_title="Lead Enrichment Pipeline", layout="wide")
st.title("🎯 Lead Enrichment & Qualification Pipeline")

tab_upload, tab_dashboard, tab_detail, tab_icp = st.tabs(
    ["📤 Upload / Enrich", "📊 Dashboard", "🔍 Lead Detail", "⚙️ ICP Config"]
)


# ---------- TAB 1: Upload / Enrich a single lead ----------
with tab_upload:
    st.subheader("Enrich a single lead")
    col1, col2 = st.columns(2)
    with col1:
        name = st.text_input("Contact name", "")
        company = st.text_input("Company", "Apollo Hospitals")
    with col2:
        website = st.text_input("Website", "https://www.apollohospitals.com")
        email = st.text_input("Email", "")

    if st.button("🚀 Enrich Lead", type="primary"):
        if not (company or website or email):
            st.error("Enter at least a company, website, or email.")
        else:
            with st.spinner("Running pipeline: scrape → score → signals → emails... (~30s)"):
                try:
                    r = requests.post(f"{API}/enrich", json={
                        "name": name, "company": company,
                        "website": website, "email": email,
                    }, timeout=180)
                    if r.ok:
                        data = r.json()
                        st.success(f"Done! Combined score: {data['combined_score']} | Qualified: {data['qualified']}")
                        c1, c2, c3 = st.columns(3)
                        c1.metric("ICP Score", data["icp_score"])
                        c2.metric("Combined Score", data["combined_score"])
                        c3.metric("Top Signal", "Yes" if data.get("top_signal") else "None")
                        if data.get("top_signal"):
                            st.info(f"**Top buying signal:** {data['top_signal']}")
                        st.write("### Email drafts")
                        for e in data["emails"]:
                            with st.expander(f"✉️ {e['tone'].title()} — {e['subject']}"):
                                st.text(e["body"])
                    else:
                        st.error(f"Error {r.status_code}: {r.text}")
                except Exception as ex:
                    st.error(f"Request failed: {ex}")

    st.divider()
    st.subheader("Or upload a CSV of leads")
    st.caption("CSV columns: name, company, website, email (any subset).")
    csv_file = st.file_uploader("Choose CSV", type="csv")
    if csv_file is not None:
        preview = pd.read_csv(csv_file)
        st.write("Preview (first 5 rows):")
        st.dataframe(preview.head())
        csv_file.seek(0)
        if st.button("📥 Enrich all rows"):
            with st.spinner(f"Enriching {len(preview)} leads... this may take a while"):
                try:
                    r = requests.post(f"{API}/upload-csv",
                                      files={"file": ("leads.csv", csv_file.getvalue())},
                                      timeout=600)
                    if r.ok:
                        res = r.json()
                        st.success(f"Processed {res['processed']} leads. See Dashboard tab.")
                    else:
                        st.error(f"Error: {r.text}")
                except Exception as ex:
                    st.error(f"Failed: {ex}")


# ---------- TAB 2: Dashboard table ----------
with tab_dashboard:
    st.subheader("All leads")
    if st.button("🔄 Refresh"):
        st.rerun()
    try:
        leads = requests.get(f"{API}/leads", timeout=30).json().get("leads", [])
        if not leads:
            st.info("No leads yet. Enrich one in the Upload tab.")
        else:
            rows = []
            for l in leads:
                top_sig = l["buying_signals"][0]["signal"] if l.get("buying_signals") else "—"
                rows.append({
                    "ID": l["id"], "Name": l.get("name", ""),
                    "Company": l.get("company", ""),
                    "ICP Score": l.get("icp_score"),
                    "Top Signal": top_sig[:50],
                    "Enrich": l.get("enrich_status", ""),
                    "Sync": l.get("sync_status", ""),
                })
            df = pd.DataFrame(rows).sort_values("ICP Score", ascending=False, na_position="last")
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.caption(f"{len(leads)} leads. Use the Lead Detail tab to inspect one and sync to Notion.")
    except Exception as ex:
        st.error(f"Couldn't load leads: {ex}")


# ---------- TAB 3: Lead detail + sync ----------
with tab_detail:
    st.subheader("Lead detail")
    lead_id = st.number_input("Lead ID", min_value=1, step=1, value=1)
    if st.button("Load lead"):
        try:
            l = requests.get(f"{API}/lead/{int(lead_id)}", timeout=30).json()
            st.write(f"## {l.get('name','')} @ {l.get('company','')}")
            c1, c2, c3 = st.columns(3)
            c1.metric("ICP Score", l.get("icp_score"))
            c2.metric("Enrich status", l.get("enrich_status"))
            c3.metric("Sync status", l.get("sync_status"))

            st.write("### Buying signals")
            sigs = l.get("buying_signals", [])
            if sigs:
                for s in sigs:
                    st.write(f"- **[{s['strength']}]** {s['signal']}  _(source: {s['source']})_")
            else:
                st.write("None detected.")

            st.write("### Enriched fields")
            fields = l.get("profile", {}).get("fields", {})
            for k, f in fields.items():
                st.write(f"- **{k}**: {f['value']}  `[{f['confidence']} / {f['source']}]`")

            st.write("### Email drafts")
            for e in l.get("emails", []):
                with st.expander(f"✉️ {e['tone'].title()} — {e['subject']}"):
                    st.text(e["body"])

            st.divider()
            if st.button("📤 Sync this lead to Notion", type="primary"):
                with st.spinner("Syncing to Notion..."):
                    r = requests.post(f"{API}/sync/{int(lead_id)}", timeout=60)
                    res = r.json()
                    st.success(f"Sync status: {res.get('status')}")
        except Exception as ex:
            st.error(f"Couldn't load lead: {ex}")


# ---------- TAB 4: ICP config view ----------
with tab_icp:
    st.subheader("ICP configuration")
    st.caption("Edit config/settings.json to change these (no code changes needed).")
    try:
        cfg = requests.get(f"{API}/icp", timeout=30).json()
        st.write("### Target ICP")
        st.json(cfg.get("icp", {}))
        st.write("### Scoring weights & threshold")
        st.json(cfg.get("scoring", {}))
        st.write("### Product / value proposition")
        st.json(cfg.get("product", {}))
    except Exception as ex:
        st.error(f"Couldn't load ICP: {ex}")