"""로컬 임베딩 (sentence-transformers). Router 병합 후보 탐색·Linker 이웃 탐색·평가 회수율에 사용."""
from __future__ import annotations

import numpy as np

_MODEL = None
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


def _model():
    global _MODEL
    if _MODEL is None:
        from sentence_transformers import SentenceTransformer
        _MODEL = SentenceTransformer(MODEL_NAME)
    return _MODEL


def embed(texts: list[str]) -> np.ndarray:
    if not texts:
        return np.zeros((0, 384), dtype=np.float32)
    return _model().encode(texts, normalize_embeddings=True, batch_size=64, show_progress_bar=False).astype(np.float32)


class Index:
    """작은 인메모리 벡터 인덱스 (id → 벡터). KB 규모(수백~수천 노드)에 충분."""

    def __init__(self):
        self.ids: list[str] = []
        self.vecs: np.ndarray = np.zeros((0, 384), dtype=np.float32)
        self.meta: dict[str, dict] = {}

    def add(self, id: str, text: str, **meta) -> None:
        v = embed([text])
        if id in self.meta:
            i = self.ids.index(id); self.vecs[i] = v[0]
        else:
            self.ids.append(id); self.vecs = np.vstack([self.vecs, v])
        self.meta[id] = {"text": text, **meta}

    def add_many(self, items: list[tuple[str, str, dict]]) -> None:
        if not items:
            return
        vs = embed([t for _, t, _ in items])
        for (id, text, meta), v in zip(items, vs):
            if id in self.meta:
                self.vecs[self.ids.index(id)] = v
            else:
                self.ids.append(id); self.vecs = np.vstack([self.vecs, v[None, :]])
            self.meta[id] = {"text": text, **meta}

    def search(self, text: str, k: int = 5, filt=None) -> list[tuple[str, float]]:
        if not self.ids:
            return []
        q = embed([text])[0]
        sims = self.vecs @ q
        order = np.argsort(-sims)
        out = []
        for i in order:
            id = self.ids[i]
            if filt and not filt(id, self.meta[id]):
                continue
            out.append((id, float(sims[i])))
            if len(out) >= k:
                break
        return out
