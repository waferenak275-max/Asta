from .memory import search_episodic

def recall_episodic(query: str, top_k: int = 2):
    return search_episodic(query, top_k=top_k)
