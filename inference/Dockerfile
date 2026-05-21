# syntax=docker/dockerfile:1.6
FROM --platform=linux/arm64 python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/inference

RUN pip install --no-cache-dir \
        torch==2.11.0 \
        transformers==5.8.0 \
        huggingface_hub==1.14.0 \
        redis==7.4.0

ARG MODEL_NAME=Qwen/Qwen2.5-0.5B-Instruct
ENV MODEL_NAME=${MODEL_NAME}
RUN python -c "from transformers import AutoModelForCausalLM, AutoTokenizer; \
    AutoTokenizer.from_pretrained('${MODEL_NAME}'); \
    AutoModelForCausalLM.from_pretrained('${MODEL_NAME}')"

COPY inference_worker.py /opt/inference/inference_worker.py

CMD ["python", "/opt/inference/inference_worker.py"]
