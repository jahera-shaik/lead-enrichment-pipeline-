import os
from dotenv import load_dotenv
from notion_client import Client

load_dotenv()
notion = Client(auth=os.getenv("NOTION_API_KEY"))
db_id = os.getenv("NOTION_DB_ID")

print("DB ID loaded:", db_id)

# Try querying the database (works with data_source IDs)
try:
    resp = notion.databases.query(database_id=db_id, page_size=1)
    print("✅ Query works! Rows currently in DB:", len(resp.get("results", [])))
except Exception as e:
    print("query failed:", e)

# Try creating a test row to confirm write access
try:
    page = notion.pages.create(
        parent={"database_id": db_id},
        properties={
            "Name": {"title": [{"text": {"content": "Connection Test Lead"}}]},
            "Company": {"rich_text": [{"text": {"content": "TestCo"}}]},
            "ICP Score": {"number": 88},
            "Status": {"select": {"name": "synced"}},
        },
    )
    print("✅ Write works! Created test page id:", page["id"])
except Exception as e:
    print("❌ write failed:", e)