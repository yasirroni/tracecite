"""Deterministic embeddings for the documentation-index tests."""

from __future__ import annotations

import pytest

from tracecite.evidence import schema


class FakeEmbedder:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        vectors: list[list[float]] = []
        for text in texts:
            seed = sum((index + 1) * ord(char) for index, char in enumerate(text))
            vector = [0.0] * schema.EMBEDDING_DIMENSIONS
            vector[seed % schema.EMBEDDING_DIMENSIONS] = 1.0
            vector[(seed // 7) % schema.EMBEDDING_DIMENSIONS] = 0.5
            vectors.append(vector)
        return vectors


@pytest.fixture
def make_embedder():
    """Factory for a fresh, call-counting fake embedder."""
    return FakeEmbedder
