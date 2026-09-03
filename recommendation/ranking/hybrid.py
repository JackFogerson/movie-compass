from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class HybridWeights:
    collaborative: float = 0.55
    content: float = 0.35
    popularity: float = 0.10

    def normalized(self) -> np.ndarray:
        values = np.array([self.collaborative, self.content, self.popularity], dtype=np.float64)
        if np.any(values < 0) or values.sum() <= 0:
            raise ValueError("Hybrid weights must be non-negative with a positive sum")
        return values / values.sum()


def hybrid_predictions(
    collaborative: np.ndarray,
    content: np.ndarray,
    popularity: np.ndarray,
    weights: HybridWeights | None = None,
) -> np.ndarray:
    arrays = [np.asarray(value, dtype=np.float64) for value in (collaborative, content, popularity)]
    if len({array.shape for array in arrays}) != 1:
        raise ValueError("All hybrid prediction arrays must have the same shape")
    effective_weights = weights or HybridWeights()
    combined = np.average(np.vstack(arrays), axis=0, weights=effective_weights.normalized())
    return np.clip(combined, 0.5, 5.0)
