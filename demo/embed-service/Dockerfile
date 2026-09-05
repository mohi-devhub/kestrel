# The weights are baked in at build time rather than fetched on startup: the
# demo has to come up on a node with no reliable egress, and a replica that
# downloads a model on boot would make scale-up latency a network measurement.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

ENV MODEL_DIR=/model
ARG MODEL_REPO=https://huggingface.co/Xenova/all-MiniLM-L6-v2/resolve/main
RUN mkdir -p "$MODEL_DIR" \
 && apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
 && curl -fsSL "$MODEL_REPO/onnx/model_quantized.onnx" -o "$MODEL_DIR/model.onnx" \
 && curl -fsSL "$MODEL_REPO/tokenizer.json" -o "$MODEL_DIR/tokenizer.json" \
 && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

COPY app.py .

EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
