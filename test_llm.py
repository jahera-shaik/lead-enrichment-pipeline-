import time
from services.llm import generate, generate_json

t = time.time()
print("=== plain ===")
print(generate("Say 'local inference works' and nothing else.", max_tokens=20))
print(f"\nload+gen took {time.time()-t:.1f}s")

print("\n=== json ===")
print(generate_json(
    'Score this company size match. Target "20-100 employees". '
    'Company: "boutique consultancy with 40 engineers". '
    'Return {"match": true/false, "reason": "..."}'
))