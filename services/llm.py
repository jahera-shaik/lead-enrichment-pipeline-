import os
from llama_cpp import Llama

_MODEL = None
MODEL_PATH = os.getenv("MODEL_PATH", "models/qwen2.5-0.5b-instruct-q4_k_m.gguf")

# Hugging Face repo + filename for auto-download (used if the model file is missing,
# e.g. on a fresh deploy where models/ isn't in the repo).
HF_REPO = os.getenv("HF_REPO", "Qwen/Qwen2.5-0.5B-Instruct-GGUF")
HF_FILENAME = os.getenv("HF_FILENAME", "qwen2.5-0.5b-instruct-q4_k_m.gguf")


def _ensure_model():
    """Download the GGUF model if it isn't on disk yet (first run / fresh deploy)."""
    if os.path.exists(MODEL_PATH):
        return MODEL_PATH
    from huggingface_hub import hf_hub_download
    os.makedirs(os.path.dirname(MODEL_PATH) or ".", exist_ok=True)
    print(f"[llm] Model not found at {MODEL_PATH}; downloading {HF_FILENAME} from {HF_REPO}...")
    path = hf_hub_download(
        repo_id=HF_REPO,
        filename=HF_FILENAME,
        local_dir=os.path.dirname(MODEL_PATH) or ".",
    )
    print(f"[llm] Model downloaded to {path}")
    return path


def get_model():
    global _MODEL
    if _MODEL is None:
        path = _ensure_model()
        _MODEL = Llama(
            model_path=path,
            n_ctx=1024,
            n_threads=2,
            n_batch=128,
            n_gpu_layers=0,
            use_mlock=False,
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
        repeat_penalty=1.3,
    )
    return out["choices"][0]["message"]["content"].strip()


def generate_json(prompt: str, system: str = "", max_tokens: int = 512):
    """
    Generate and parse JSON. NEVER raises - always returns a dict (or list).
    Tries several repair strategies for small-model output quirks.
    """
    import json, re
    sys = (system + "\nRespond ONLY with valid JSON. No markdown, no prose, "
           "no trailing commas.").strip()
    raw = generate(prompt, system=sys, max_tokens=max_tokens, temperature=0.1)

    def _try(s):
        try:
            return json.loads(s)
        except Exception:
            return None

    # 1. strip code fences
    cleaned = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()
    out = _try(cleaned)
    if out is not None:
        return out
    # 2. grab the first {...} or [...] block
    m = re.search(r"(\{.*\}|\[.*\])", cleaned, re.DOTALL)
    if m:
        block = m.group(1)
        out = _try(block)
        if out is not None:
            return out
        # 3. light repairs: remove trailing commas
        repaired = re.sub(r",\s*([}\]])", r"\1", block)
        out = _try(repaired)
        if out is not None:
            return out
    # 4. give up gracefully - caller handles this
    return {"_parse_error": raw[:500]}