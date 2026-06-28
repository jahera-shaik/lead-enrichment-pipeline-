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
            n_ctx=2048,
            n_threads=os.cpu_count(),
            n_gpu_layers=0,
            verbose=False,
        )
    return _MODEL