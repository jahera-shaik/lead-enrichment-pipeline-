import os
from llama_cpp import Llama

_MODEL = None
MODEL_PATH = os.getenv("MODEL_PATH", "models/qwen2.5-0.5b-instruct-q4_k_m.gguf")

def get_model():
    global _MODEL
    if _MODEL is None:
        _MODEL = Llama(
            model_path=MODEL_PATH,
            n_ctx=4096,
            n_threads=os.cpu_count(),
            n_gpu_layers=0,
            verbose=False,
        )
    return _MODEL

def generate(prompt: str, system: str = "", max_tokens: int = 512,
             temperature: float = 0.4) -> str:
    llm = get_model()
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    out = llm.create_chat_completion(
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return out["choices"][0]["message"]["content"].strip()

def generate_json(prompt: str, system: str = "", max_tokens: int = 512) -> dict:
    import json, re
    sys = (system + "\nRespond ONLY with valid JSON. No markdown, no prose.").strip()
    raw = generate(prompt, system=sys, max_tokens=max_tokens, temperature=0.1)
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip()).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        return json.loads(m.group()) if m else {"_parse_error": raw}