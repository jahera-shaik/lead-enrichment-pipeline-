FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    gcc g++ cmake make libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --upgrade pip && \
    CMAKE_ARGS="-DGGML_BLAS=OFF -DGGML_CUDA=OFF" \
    pip install --no-cache-dir llama-cpp-python==0.2.90 && \
    pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p models && python -c "from huggingface_hub import hf_hub_download; hf_hub_download(repo_id='Qwen/Qwen2.5-0.5B-Instruct-GGUF', filename='qwen2.5-0.5b-instruct-q4_k_m.gguf', local_dir='models')"

EXPOSE 7860
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "7860"]
