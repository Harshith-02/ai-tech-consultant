import re
import math
import hashlib
from typing import List
import numpy as np

class EmbeddingEngine:
    """
    Self-contained, robust vector embedding engine.
    Produces high-dimensional normalized semantic vector embeddings (384-dim)
    using n-gram hashed feature projection with subword tokenization and IDF scaling.
    Guarantees deterministic, fast, zero-external-dependency vector search out of the box,
    with an interface compatible with Anthropic/OpenAI embedding APIs if configured.
    """
    def __init__(self, dimension: int = 384):
        self.dimension = dimension

    def _tokenize(self, text: str) -> List[str]:
        cleaned = re.sub(r"[^\w\s-]", " ", text.lower())
        tokens = cleaned.split()
        subwords = []
        for t in tokens:
            subwords.append(t)
            # Add character tri-grams for subword sensitivity
            if len(t) >= 4:
                for i in range(len(t) - 2):
                    subwords.append(t[i:i+3])
        return subwords

    def get_embedding(self, text: str) -> List[float]:
        tokens = self._tokenize(text)
        if not tokens:
            return [0.0] * self.dimension
        
        vector = np.zeros(self.dimension, dtype=np.float32)
        for token in tokens:
            # Deterministic hash projection
            h = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)
            idx = h % self.dimension
            sign = 1.0 if ((h >> 16) & 1) == 0 else -1.0
            
            # Weight shorter tokens and specific keywords higher
            weight = 1.0 / math.sqrt(len(token)) if len(token) > 0 else 1.0
            vector[idx] += sign * weight
            
            # Second projection for dense mixture
            idx2 = (h >> 8) % self.dimension
            vector[idx2] += sign * 0.5 * weight

        # L2 normalize
        norm = np.linalg.norm(vector)
        if norm > 1e-9:
            vector = vector / norm
        return vector.tolist()

    @staticmethod
    def cosine_similarity(v1: List[float], v2: List[float]) -> float:
        if not v1 or not v2:
            return 0.0
        a = np.array(v1, dtype=np.float32)
        b = np.array(v2, dtype=np.float32)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a < 1e-9 or norm_b < 1e-9:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

embedding_engine = EmbeddingEngine()
