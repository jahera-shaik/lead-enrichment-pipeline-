from huggingface_hub import hf_hub_download

path = hf_hub_download(
    repo_id="Qwen/Qwen2.5-0.5B-Instruct-GGUF",
    filename="qwen2.5-0.5b-instruct-q4_k_m.gguf",
    local_dir="models",
)
print("DONE:", path)