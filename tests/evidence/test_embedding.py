"""Embedding-model loading tests."""

from __future__ import annotations

import logging

import sentence_transformers
from transformers.utils import logging as transformers_logging

from tracecite.evidence import schema
from tracecite.evidence.embedding import EmbeddingModel


class NoisySentenceTransformer:
    """Emits the same kinds of output the real model load prints."""

    def __init__(self, *args, **kwargs):
        logging.getLogger("sentence_transformers.models").warning(
            "The Transformer `cache_dir` argument is deprecated."
        )
        logging.getLogger("huggingface_hub.utils._http").warning(
            "You are sending unauthenticated requests to the HF Hub; set a HF_TOKEN."
        )
        for _ in transformers_logging.tqdm(range(3), desc="Loading weights"):
            pass

    def encode(self, texts, **kwargs):
        return [[0.0] * schema.EMBEDDING_DIMENSIONS for _ in texts]


def test_model_loading_prints_no_library_noise_and_restores_settings(
    tmp_path, capfd, caplog, monkeypatch
):
    monkeypatch.setattr(
        sentence_transformers, "SentenceTransformer", NoisySentenceTransformer
    )
    transformers_level = logging.getLogger("transformers").level
    progress_bars = transformers_logging.is_progress_bar_enabled()
    capfd.readouterr()
    caplog.set_level(logging.WARNING)

    model = EmbeddingModel(
        schema.EMBEDDING_MODEL, schema.EMBEDDING_REVISION, tmp_path / "model-cache"
    )
    assert len(model.embed(["query"])) == 1

    captured = capfd.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert caplog.records == []
    assert logging.getLogger("transformers").level == transformers_level
    assert transformers_logging.is_progress_bar_enabled() == progress_bars
