import time
import os
import sys
from pathlib import Path

sys.path.append(str(Path("C:/Users/USER/Documents/Asta")))

from config import load_config

def test_performance():
    cfg = load_config()
    
    print("--- 1. Testing Embedding Speed ---")
    from engine.memory_system import create_embedding
    
    t0 = time.perf_counter()
    emb = create_embedding("Halo Asta, apa kabar hari ini?")
    t1 = time.perf_counter()
    print(f"Time for first embedding: {t1 - t0:.4f}s")
    
    t0 = time.perf_counter()
    for _ in range(5):
        create_embedding("Input tes untuk benchmark")
    t1 = time.perf_counter()
    print(f"Avg time for subsequent embeddings (5 runs): {(t1 - t0)/5:.4f}s")

    print("\n--- 2. Testing Memory Context Speed ---")
    from engine.memory import get_hybrid_memory
    hybrid_mem = get_hybrid_memory()
    
    t0 = time.perf_counter()
    ctx = hybrid_mem.get_context(current_query="Apa kabar?", recall_topic="Aditiya")
    t1 = time.perf_counter()
    print(f"Time to get memory context: {t1 - t0:.4f}s")
    print(f"Context length: {len(ctx)} chars")

    print("\n--- 3. Testing Token Budget Manager Speed ---")
    from engine.model import MODELS, ChatManager
    import llama_cpp
    from llama_cpp.llama_tokenizer import LlamaHFTokenizer
    
    choice = cfg.get("model_choice", "1")
    model_cfg = MODELS[choice]
    tokenizer = LlamaHFTokenizer.from_pretrained(model_cfg["tokenizer_path"])
    
    print("Loading minimal llama for tokenizer...")
    llama = llama_cpp.Llama(
        model_path=model_cfg["model_path"],
        tokenizer=tokenizer,
        vocab_only=True,
        verbose=False
    )
    
    from engine.token_budget import TokenBudget, TokenBudgetManager
    
    def count_fn(msgs):
        text = ""
        for m in msgs:
            text += f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>\n"
        return len(llama.tokenize(text.encode("utf-8")))

    budget = TokenBudget()
    manager = TokenBudgetManager(budget, count_fn)
    
    history = [{"role": "user", "content": "Pesan ke-" + str(i)} for i in range(20)]
    system_msg = {"role": "system", "content": "Identity " * 50}
    memory_msgs = [{"role": "system", "content": "Memory fact " * 20} for _ in range(5)]
    
    t0 = time.perf_counter()
    for _ in range(10):
        manager.build_messages(system_msg, memory_msgs, history)
    t1 = time.perf_counter()
    print(f"Avg time for build_messages (10 runs, 20 history, 5 memory): {(t1 - t0)/10:.4f}s")

if __name__ == "__main__":
    test_performance()
