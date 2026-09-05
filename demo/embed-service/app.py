"""A real sentence-embedding model served over HTTP, for Kestrel to schedule.

Nothing in here knows about Kestrel, and Kestrel knows nothing about what runs
in here: it schedules an image and a port. That is the whole point of the demo
— the platform is model-agnostic, so this service is an ordinary container that
happens to hold real weights.

The model is all-MiniLM-L6-v2 (a 6-layer BERT sentence encoder) exported to
ONNX and int8-quantized, which is what makes it small and fast enough to run on
a CPU node: ~23MB of weights, single-digit milliseconds per short sentence.
Embeddings are mean-pooled over tokens and L2-normalized, matching how
sentence-transformers produces them, so a dot product is cosine similarity.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort
from fastapi import FastAPI
from pydantic import BaseModel, Field
from tokenizers import Tokenizer

MODEL_DIR = Path(os.environ.get("MODEL_DIR", "/model"))
MODEL_NAME = "all-MiniLM-L6-v2 (ONNX int8)"
MAX_TOKENS = 256

app = FastAPI(title="Kestrel demo embedding service")

_tokenizer = Tokenizer.from_file(str(MODEL_DIR / "tokenizer.json"))
_tokenizer.enable_truncation(max_length=MAX_TOKENS)
_tokenizer.enable_padding()

# One intra-op thread: the container is scheduled as a single small replica, and
# letting ORT fan out across every core on the node would make one replica's
# latency depend on how many other replicas share the machine.
_options = ort.SessionOptions()
_options.intra_op_num_threads = 1
_session = ort.InferenceSession(
    str(MODEL_DIR / "model.onnx"), _options, providers=["CPUExecutionProvider"]
)
_input_names = {i.name for i in _session.get_inputs()}


class EmbedRequest(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=64)


class SimilarityRequest(BaseModel):
    a: str
    b: str


def _embed(texts: list[str]) -> np.ndarray:
    encodings = _tokenizer.encode_batch(texts)
    input_ids = np.array([e.ids for e in encodings], dtype=np.int64)
    attention_mask = np.array([e.attention_mask for e in encodings], dtype=np.int64)

    # Build the feed from what this export actually declares rather than
    # assuming BERT's full triple — quantized exports sometimes drop
    # token_type_ids, and a missing/extra input is a hard error in ORT.
    feed: dict[str, np.ndarray] = {"input_ids": input_ids, "attention_mask": attention_mask}
    if "token_type_ids" in _input_names:
        feed["token_type_ids"] = np.zeros_like(input_ids)

    token_vectors = _session.run(None, feed)[0]

    # Mean-pool over real tokens only, so padding cannot drag a short sentence's
    # vector toward zero, then L2-normalize so a dot product is cosine similarity.
    mask = attention_mask[..., None].astype(np.float32)
    summed = (token_vectors * mask).sum(axis=1)
    counts = np.clip(mask.sum(axis=1), a_min=1e-9, a_max=None)
    pooled = summed / counts
    norms = np.linalg.norm(pooled, axis=1, keepdims=True)
    return pooled / np.clip(norms, a_min=1e-9, a_max=None)


@app.get("/healthz")
def healthz() -> dict[str, object]:
    return {"ok": True, "model": MODEL_NAME, "dimensions": _session.get_outputs()[0].shape[-1]}


@app.get("/")
def root() -> dict[str, object]:
    return {
        "service": "kestrel-demo-embeddings",
        "model": MODEL_NAME,
        "endpoints": ["POST /embed", "POST /similarity", "GET /healthz"],
    }


@app.post("/embed")
def embed(body: EmbedRequest) -> dict[str, object]:
    started = time.perf_counter()
    vectors = _embed(body.texts)
    return {
        "model": MODEL_NAME,
        "count": len(body.texts),
        "dimensions": int(vectors.shape[1]),
        "inference_ms": round((time.perf_counter() - started) * 1000, 2),
        "embeddings": [[round(float(x), 6) for x in v] for v in vectors],
    }


@app.post("/similarity")
def similarity(body: SimilarityRequest) -> dict[str, object]:
    started = time.perf_counter()
    vectors = _embed([body.a, body.b])
    return {
        "model": MODEL_NAME,
        "a": body.a,
        "b": body.b,
        # Both vectors are unit-length, so the dot product is the cosine.
        "cosine_similarity": round(float(vectors[0] @ vectors[1]), 4),
        "inference_ms": round((time.perf_counter() - started) * 1000, 2),
    }
