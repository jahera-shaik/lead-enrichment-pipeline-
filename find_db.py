import os
from dotenv import load_dotenv
from notion_client import Client

load_dotenv()
notion = Client(auth=os.getenv("NOTION_API_KEY"))

print("Objects shared with this integration:\n")
results = notion.search().get("results", [])
if not results:
    print("Nothing found — integration may not be connected to anything.")
for r in results:
    obj = r.get("object")
    rid = r.get("id")
    title = ""
    if r.get("title"):
        title = "".join(t.get("plain_text", "") for t in r["title"])
    print(f"{obj} | id={rid} | title={title}")