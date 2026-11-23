# CPU-only image: Claude Code CLI (script writer, uses your Claude subscription) + Ollama (fallback LLM)
# + Kokoro (voice) + ffmpeg + Pillow. Build from the repo root:
#   docker build -f pipeline/Dockerfile -t yt-pipeline .
ARG OLLAMA_VERSION=latest

FROM ollama/ollama:${OLLAMA_VERSION} AS ollama
# drop the GPU backends; this pipeline runs on CPU only
RUN rm -rf /usr/lib/ollama/cuda* /usr/lib/ollama/rocm* /usr/lib/ollama/vulkan* /usr/lib/ollama/mlx* || true

FROM python:3.12-slim-trixie
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    OLLAMA_MODELS=/opt/ollama-models TOPICS_FILE=/app/topics/topics.yaml CHALLENGES_DIR=/app/challenges \
    PATH=/root/.local/bin:$PATH DISABLE_AUTOUPDATER=1
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg fonts-dejavu-core libsndfile1 libgomp1 libstdc++6 ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# Claude Code CLI (native build). Auth at runtime via CLAUDE_CODE_OAUTH_TOKEN from `claude setup-token`.
RUN curl -fsSL https://claude.ai/install.sh | bash && claude --version

COPY --from=ollama /usr/bin/ollama /usr/bin/ollama
COPY --from=ollama /usr/lib/ollama /usr/lib/ollama

# Kokoro-82M (Apache-2.0), int8 ONNX build: ~90 MB, fast on CPU
RUN mkdir -p /opt/models && cd /opt/models \
 && curl -fsSL -o kokoro-v1.0.int8.onnx https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.int8.onnx \
 && curl -fsSL -o voices-v1.0.bin https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin

WORKDIR /app
COPY pipeline/requirements.txt .
RUN pip install -r requirements.txt
COPY pipeline/app ./app
COPY topics ./topics
COPY challenges ./challenges

ENTRYPOINT ["python", "-m", "app.main"]
CMD ["render"]
