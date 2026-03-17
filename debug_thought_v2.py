
import os
import sys
import json
import re
from pathlib import Path

# Import templates and parsers from the actual project
from engine.thought import (
    STEP1_PERCEPTION_TEMPLATE,
    STEP2_SELFCHECK_TEMPLATE,
    STEP3_MEMORY_TEMPLATE,
    STEP4_DECISION_TEMPLATE,
    _parse_step1, _parse_step2, _parse_step3, _parse_step4,
    _STOP,
    run_thought_pass
)
from engine.model import MODELS, _load_llama

def run_rigorous_debug():
    model_info = MODELS["1"]
    print(f"Loading Model: {model_info['model_path']}")
    llm = _load_llama(model_info["model_path"], model_info["tokenizer_path"], n_ctx=2048, n_batch=512)

    # Simulation setup
    user_name = "Aditiya"
    # Note: "flag point" is in memory_hint, which might be confusing the model
    memory_hint = "[Memori Inti]\nAditiya dan Asta punya 'flag point' rahasia.\nAditiya suka teknologi."
    asta_state = {"mood": "senang", "affection_level": 0.85, "energy_level": 0.9}
    
    # History simulation
    recent_context = "Asta: Halo sayang!\nAditiya: Halo Asta!"

    # Test cases: Alternating Search and Casual
    test_cases = [
        ("Film horor yang lagi tayang di bioskop minggu ini yang bagus apa?", "search"), # Expected: Search
        ("Wahh kayaknya serem ya filmnya...", "casual"),                               # Expected: No Search (Response to feeling)
        ("Inget gak flag point kita apa?", "recall"),                                  # Expected: Recall (No Search)
        ("Gimana cara benerin laptop yang layarnya biru?", "search"),                  # Expected: Search
        ("Hehe makasih ya infonya sayang", "casual")                                   # Expected: No Search
    ]

    # Load actual config
    with open("config.json", "r") as f:
        config = json.load(f)

    for i, (user_input, expected_type) in enumerate(test_cases):
        print(f"\n{'='*80}")
        print(f"TURN {i+1} | INPUT: {user_input} | EXPECTED: {expected_type}")
        print(f"{'='*80}")

        thought = run_thought_pass(
            llm=llm,
            user_input=user_input,
            memory_context=memory_hint,
            recent_context=recent_context,
            web_search_enabled=True,
            user_name=user_name,
            asta_state=asta_state,
            cfg=config # Pass the actual config here
        )

        print(f"\n[S1] Topic: {thought['topic']}")
        print(f"[S3] Reasoning: {thought['reasoning']}")
        print(f"[S3] Need Search: {thought['need_search']}")
        print(f"[S3] Search Query: {thought['search_query']}")
        print(f"[S3] Recall Topic: {thought['recall_topic']}")
        print(f"[S4] Note: {thought['note']}")

        # Update context for next turn
        recent_context += f"\nAditiya: {user_input}\nAsta: (responded)"
        if len(recent_context) > 500: recent_context = recent_context[-500:]

if __name__ == "__main__":
    run_rigorous_debug()
