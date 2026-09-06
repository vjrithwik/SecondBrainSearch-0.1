# ONNX embedder wrapper with deterministic fallback for testing.
"""ONNX embedder wrapper with deterministic fallback for testing."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Protocol

import numpy as np

from second_brain.config import CHUNK_BATCH_SIZE, EMBEDDING_DIMENSION

logger = logging.getLogger(__name__)

_ASSET_DIR = Path(__file__).parent.parent / "assets" / "models"


class Embedder(Protocol):
    """Protocol for text-to-embedding encoders."""

    def encode(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding per input text."""
        ...


class _DeterministicEmbedder:
    """Hash-based deterministic embedder used when model assets are absent."""

    def encode(self, texts: list[str]) -> list[list[float]]:
        """Return a unit-normalised embedding derived from each text hash."""
        embeddings: list[list[float]] = []
        for text in texts:
            seed = hashlib.sha256(text.encode("utf-8")).digest()
            rng = np.random.default_rng(
                [int(b) for b in seed[: min(16, len(seed))]]
            )
            vec = rng.normal(size=EMBEDDING_DIMENSION).astype(np.float32)
            norm = float(np.linalg.norm(vec))
            if norm == 0:
                norm = 1.0
            embeddings.append([float(v / norm) for v in vec])
        return embeddings


class _OnnxEmbedder:
    """ONNX Runtime wrapper for the all-MiniLM-L6-v2 model."""

    def __init__(
        self,
        model_path: Path,
        tokenizer_path: Path,
        max_length: int = 256,
        intra_op_num_threads: int = 1,
        inter_op_num_threads: int = 1,
    ) -> None:
        import onnxruntime as ort
        from tokenizers import Tokenizer

        self._tokenizer = Tokenizer.from_file(str(tokenizer_path))
        self._tokenizer.enable_truncation(max_length=max_length)
        self._tokenizer.enable_padding(pad_id=0, pad_token="")  # nosec B106 - tokenizer pad token, not a credential
        sess_options = ort.SessionOptions()
        sess_options.intra_op_num_threads = intra_op_num_threads
        sess_options.inter_op_num_threads = inter_op_num_threads
        self._session = ort.InferenceSession(
            str(model_path),
            sess_options,
            providers=["CPUExecutionProvider"],
        )

    def encode(self, texts: list[str]) -> list[list[float]]:
        """Run tokenisation and ONNX inference for *texts*.

        Large inputs are processed in batches to keep peak ONNX memory usage
        bounded and avoid allocation failures such as the 5 GB+ attention-score
        tensors that can occur when thousands of chunks are encoded at once.
        """
        if not texts:
            return []
        embeddings: list[list[float]] = []
        for i in range(0, len(texts), CHUNK_BATCH_SIZE):
            batch = texts[i : i + CHUNK_BATCH_SIZE]
            embeddings.extend(self._encode_batch(batch))
        return embeddings

    def _encode_batch(self, texts: list[str]) -> list[list[float]]:
        """Run tokenisation and ONNX inference for a single batch."""
        encoded = self._tokenizer.encode_batch(texts)
        input_ids = np.array([e.ids for e in encoded], dtype=np.int64)
        attention_mask = np.array(
            [e.attention_mask for e in encoded], dtype=np.int64
        )
        token_type_ids = np.array(
            [e.type_ids for e in encoded], dtype=np.int64
        )
        outputs = self._session.run(
            None,
            {
                "input_ids": input_ids,
                "attention_mask": attention_mask,
                "token_type_ids": token_type_ids,
            },
        )
        # Mean pooling with attention mask.
        token_embeddings = outputs[0]
        mask = attention_mask[..., None].astype(np.float32)
        summed = np.sum(token_embeddings * mask, axis=1)
        counts = np.clip(mask.sum(axis=1), a_min=1e-9, a_max=None)
        mean_pooled = summed / counts
        # L2 normalise.
        norms = np.linalg.norm(mean_pooled, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        embeddings = mean_pooled / norms
        return embeddings.astype(np.float32).tolist()


def create_embedder(
    model_path: Path | None = None,
    tokenizer_path: Path | None = None,
) -> Embedder:
    """Return an ONNX embedder if assets exist, otherwise a deterministic fallback."""
    model_path = model_path or _ASSET_DIR / "all-MiniLM-L6-v2.onnx"
    tokenizer_path = tokenizer_path or _ASSET_DIR / "tokenizer.json"
    if model_path.exists() and tokenizer_path.exists():
        logger.info("Loading ONNX embedder from %s", model_path)
        return _OnnxEmbedder(model_path, tokenizer_path)
    logger.warning(
        "ONNX model assets not found at %s; using deterministic fallback",
        _ASSET_DIR,
    )
    return _DeterministicEmbedder()
