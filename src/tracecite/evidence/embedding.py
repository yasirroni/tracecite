from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol
import os


class Embedder(Protocol):
    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class EmbeddingModel:
    """Lazy wrapper around the configured sentence-transformers model."""

    def __init__(
        self,
        model_name: str,
        revision: str,
        cache_dir: Path,
        *,
        preloaded_model=None,
    ) -> None:
        self.model_name = model_name
        self.revision = revision
        self.cache_dir = Path(cache_dir)
        self._model = preloaded_model
        self.calls: list[list[str]] = []

    def _ensure_loaded(self):
        if self._model is not None:
            return self._model
        from huggingface_hub.errors import LocalEntryNotFoundError
        from sentence_transformers import SentenceTransformer

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", str(self.cache_dir))
        unpacked_model = self.cache_dir / self.model_name
        if (unpacked_model / "modules.json").is_file():
            self._model = SentenceTransformer(
                str(unpacked_model),
                local_files_only=True,
            )
            return self._model
        kwargs = {"revision": self.revision, "cache_folder": str(self.cache_dir)}
        try:
            self._model = SentenceTransformer(self.model_name, local_files_only=True, **kwargs)
        except (LocalEntryNotFoundError, OSError):
            self._model = SentenceTransformer(self.model_name, **kwargs)
        return self._model

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        batch = list(texts)
        self.calls.append(batch)
        if not batch:
            return []
        model = self._ensure_loaded()
        vectors = model.encode(batch, normalize_embeddings=True, show_progress_bar=False)
        return [[float(value) for value in vector] for vector in vectors]
