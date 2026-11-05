from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import Generator, Sequence
from pathlib import Path
from typing import Any, Protocol


class Embedder(Protocol):
    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


@contextlib.contextmanager
def _quiet_model_loading() -> Generator[None, None, None]:
    """Hide the warnings and progress bars the model libraries print on every load.

    Logger levels and progress-bar settings are restored afterwards, so other
    users of these libraries in the same process are unaffected.
    """
    from huggingface_hub import utils as hub_utils
    from transformers.utils import logging as transformers_logging

    loggers = [
        logging.getLogger(name)
        for name in ("huggingface_hub", "sentence_transformers", "transformers")
    ]
    levels = [logger.level for logger in loggers]
    transformers_bars = transformers_logging.is_progress_bar_enabled()
    hub_bars = not hub_utils.are_progress_bars_disabled()
    for logger in loggers:
        logger.setLevel(logging.ERROR)
    transformers_logging.disable_progress_bar()
    try:
        yield
    finally:
        for logger, level in zip(loggers, levels):
            logger.setLevel(level)
        # Each transformers toggle also switches the hub bars, so restore the
        # hub setting last.
        if transformers_bars:
            transformers_logging.enable_progress_bar()
        if hub_bars:
            hub_utils.enable_progress_bars()
        else:
            hub_utils.disable_progress_bars()


class EmbeddingModel:
    """Lazy wrapper around the configured sentence-transformers model."""

    def __init__(
        self,
        model_name: str,
        revision: str,
        cache_dir: Path,
    ) -> None:
        self.model_name = model_name
        self.revision = revision
        self.cache_dir = Path(cache_dir)
        self._model = None

    def _ensure_loaded(self):
        if self._model is not None:
            return self._model
        from huggingface_hub.errors import LocalEntryNotFoundError
        from sentence_transformers import SentenceTransformer

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", str(self.cache_dir))
        unpacked_model = self.cache_dir / self.model_name
        with _quiet_model_loading():
            if (unpacked_model / "modules.json").is_file():
                self._model = SentenceTransformer(
                    str(unpacked_model),
                    local_files_only=True,
                )
                return self._model
            kwargs: dict[str, Any] = {
                "revision": self.revision,
                "cache_folder": str(self.cache_dir),
            }
            try:
                self._model = SentenceTransformer(
                    self.model_name, local_files_only=True, **kwargs
                )
            except (LocalEntryNotFoundError, OSError):
                self._model = SentenceTransformer(self.model_name, **kwargs)
        return self._model

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        batch = list(texts)
        if not batch:
            return []
        model = self._ensure_loaded()
        vectors = model.encode(
            batch, normalize_embeddings=True, show_progress_bar=False
        )
        return [[float(value) for value in vector] for vector in vectors]
