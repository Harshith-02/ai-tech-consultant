import os
import re
import math
import hashlib
from typing import List, Optional
import numpy as np
from app.config import settings

class EmbeddingEngine:
    """
    Genuine Pretrained Semantic Vector Embedding Engine.
    Uses SentenceTransformer ('all-MiniLM-L6-v2' by default) to produce
    384-dimensional dense semantic embeddings with L2 normalization.
    Includes batched encoding and a deterministic hash projection fallback
    for environments with strict resource constraints.
    """
    def __init__(
        self,
        model_name: Optional[str] = None,
        dimension: Optional[int] = None
    ):
        self.model_name = model_name or settings.EMBEDDING_MODEL
        self.dimension = dimension or settings.EMBEDDING_DIMENSION
        self._model = None
        self._load_failed = False
    @property
    def is_pretrained(self) -> bool:
        return self._get_model() is not None

    def _get_model(self):
        if self._model is None and not self._load_failed:
            try:
                # Suppress TF oneDNN logs if TF is present
                os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(self.model_name)
            except Exception as e:
                self._load_failed = True
        return self._model

    def get_embedding(self, text: str) -> List[float]:
        """Compute normalized semantic vector embedding for a single text."""
        cleaned = text.strip() if text else ""
        if not cleaned:
            return [0.0] * self.dimension

        model = self._get_model()
        if model is not None:
            try:
                vector = model.encode(cleaned, normalize_embeddings=True, show_progress_bar=False)
                return vector.tolist()
            except Exception:
                pass

        return self._fallback_hash_embedding(cleaned)

    def get_embeddings(self, texts: List[str], batch_size: int = 32) -> List[List[float]]:
        """Compute normalized semantic vector embeddings for a batch of texts."""
        if not texts:
            return []

        model = self._get_model()
        if model is not None:
            try:
                vectors = model.encode(
                    texts,
                    batch_size=batch_size,
                    normalize_embeddings=True,
                    show_progress_bar=False
                )
                return [v.tolist() for v in vectors]
            except Exception:
                pass

        return [self._fallback_hash_embedding(t) for t in texts]

    def _fallback_hash_embedding(self, text: str) -> List[float]:
        cleaned = re.sub(r"[^\w\s-]", " ", text.lower())
        tokens = cleaned.split()
        subwords = []
        for t in tokens:
            subwords.append(t)
            if len(t) >= 4:
                for i in range(len(t) - 2):
                    subwords.append(t[i:i+3])

        if not subwords:
            return [0.0] * self.dimension

        vector = np.zeros(self.dimension, dtype=np.float32)
        for token in subwords:
            h = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)
            idx = h % self.dimension
            sign = 1.0 if ((h >> 16) & 1) == 0 else -1.0
            weight = 1.0 / math.sqrt(len(token)) if len(token) > 0 else 1.0
            vector[idx] += sign * weight

            idx2 = (h >> 8) % self.dimension
            vector[idx2] += sign * 0.5 * weight

        norm = np.linalg.norm(vector)
        if norm > 1e-9:
            vector = vector / norm
        return vector.tolist()

    @staticmethod
    def cosine_similarity(v1: List[float], v2: List[float]) -> float:
        """Compute cosine similarity between two normalized float vectors."""
        if not v1 or not v2:
            return 0.0
        a = np.array(v1, dtype=np.float32)
        b = np.array(v2, dtype=np.float32)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a < 1e-9 or norm_b < 1e-9:
            return 0.0
        sim = float(np.dot(a, b) / (norm_a * norm_b))
        return max(-1.0, min(1.0, sim))

embedding_engine = EmbeddingEngine()
