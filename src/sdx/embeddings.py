from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable, Protocol

import numpy as np

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def serialize_vector(vector: Iterable[float]) -> bytes:
    return np.asarray(list(vector), dtype="<f4").tobytes()


def deserialize_vector(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype="<f4")


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0.0:
        return 0.0
    return float(np.dot(a, b) / denom)


class Embedder(Protocol):
    model_name: str
    dimension: int

    def embed(self, texts: list[str]) -> list[np.ndarray]: ...


@dataclass
class HashingEmbedder:
    """Deterministic offline lexical embedder for portable tests and no-network use."""

    dimension: int = 384
    model_name: str = "sdx-hashing-384"

    def embed(self, texts: list[str]) -> list[np.ndarray]:
        vectors = []
        for text in texts:
            vector = np.zeros(self.dimension, dtype=np.float32)
            for token in _TOKEN_RE.findall(text.lower()):
                digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
                bucket = int.from_bytes(digest[:4], "little") % self.dimension
                sign = 1.0 if digest[4] % 2 == 0 else -1.0
                # Sublinear token frequency dampening while preserving repeated topical terms.
                vector[bucket] += sign
            norm = np.linalg.norm(vector)
            if norm:
                vector /= norm
            vectors.append(vector.astype(np.float32))
        return vectors


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name
        self._model = SentenceTransformer(model_name)
        dim = self._model.get_sentence_embedding_dimension()
        self.dimension = int(dim or len(self.embed(["dimension probe"])[0]))

    def embed(self, texts: list[str]) -> list[np.ndarray]:
        arr = self._model.encode(texts, normalize_embeddings=True)
        return [np.asarray(v, dtype=np.float32) for v in arr]


@lru_cache(maxsize=4)
def get_embedder(model: str = "hashing") -> Embedder:
    normalized = (model or "hashing").strip()
    if normalized in {"hashing", "sdx-hashing-384"}:
        return HashingEmbedder()
    if normalized.startswith("sentence-transformers/") or normalized in {"all-MiniLM-L6-v2"}:
        model_name = normalized if normalized.startswith("sentence-transformers/") else f"sentence-transformers/{normalized}"
        return SentenceTransformerEmbedder(model_name)
    # Safe MVP default: unknown local names use deterministic hashing but retain requested name.
    embedder = HashingEmbedder()
    embedder.model_name = normalized
    return embedder
