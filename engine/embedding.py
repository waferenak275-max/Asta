import numpy as np

def text_to_embedding(text: str, dim: int = 256) -> np.ndarray:
    vec = np.zeros(dim)

    for i, c in enumerate(text.lower()):
        vec[i % dim] += ord(c)

    norm = np.linalg.norm(vec)
    return vec / norm if norm > 0 else vec
