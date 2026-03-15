from pathlib import Path
from .memory_system import SemanticMemory, EpisodicMemory, CoreMemory

MEMORY_DIR = Path("memory")
MEMORY_DIR.mkdir(exist_ok=True)

semantic_memory = SemanticMemory(MEMORY_DIR)
episodic_memory = EpisodicMemory(MEMORY_DIR)
core_memory = CoreMemory(MEMORY_DIR)

def remember_identity(key: str, value: any):
    semantic_memory.add_fact(key, value)

def get_identity(key: str):
    return semantic_memory.get_fact(key)

def get_all_identities():
    return semantic_memory.get_all_facts()

def add_episodic(conversation: list):
    episodic_memory.add(conversation)

def search_episodic(query: str, top_k: int = 3):
    return episodic_memory.search(query, top_k)

def get_last_episodic_sessions(n: int = 4):
    return episodic_memory.get_last_n_sessions(n)

def get_core_memory() -> str:
    return core_memory.get_summary()

def save_core_memory(summary_text: str):
    core_memory.update_summary(summary_text)
