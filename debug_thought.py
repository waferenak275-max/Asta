import os
import json
import re
from llama_cpp import Llama
from engine.thought import run_thought_pass, format_thought_debug, extract_recent_context

CONFIG_PATH = "config.json"
MODEL_PATH = "./model/Qwen3-4B-2507/Qwen3-4B-2507.gguf"

with open(CONFIG_PATH, "r") as f:
    cfg = json.load(f)

cfg["use_model_thought_logic"] = True

print(f"Loading Model: {MODEL_PATH}")
llm = Llama(
    model_path=MODEL_PATH,
    n_ctx=2048,
    n_batch=1024,
    n_threads=12,
    verbose=True
)
print("[Model] Siap!\n")

# Percakapan
test_cases = [
    {
        "input": "Asta, aku agak takut... tanganku tiba-tiba muncul lebam biru-biru gitu tanpa sebab. Berbahaya gak ya?",
        "emotion_state": "emosi=cemas; intensitas=tinggi",
        "expected": "COMBINED: Emotion: Cemas + Search: True (Gejala medis)"
    },
    {
        "input": "Hai Asta",
        "emotion_state": "emosi=netral; intensitas=rendah",
        "expected": "Emotion: Netral, Search: False, Recall: False, Use Memory: False"
    },
    {
        "input": "Asta, aku rindu banget sama kamu malam ini...",
        "emotion_state": "emosi=romantis; intensitas=tinggi",
        "expected": "Emotion: Romantis, Search: False"
    },
    {
        "input": "Inget gak apa hobi kesukaanku yang pernah aku ceritain?",
        "emotion_state": "emosi=senang; intensitas=sedang",
        "expected": "Recall: True, Use Memory: True"
    },
    {
        "input": "Eh, coba cariin info dong, kenapa ya langit itu warnanya biru?",
        "emotion_state": "emosi=netral; intensitas=rendah",
        "expected": "Search: True, Query: Langit biru"
    },
    {
        "input": "Ugh, jawaban kamu tadi kurang memuaskan deh. Aku kecewa.",
        "emotion_state": "emosi=kecewa; intensitas=sedang",
        "expected": "Emotion: Kecewa/Marah, Tone: Emphatic/Lembut"
    }
]

asta_state = {
    "mood": "senang",
    "affection_level": 0.85,
    "energy_level": 0.9
}

memory_context = "Aditiya suka teknologi dan hobi merakit PC. Kita punya flag point rahasia tentang masa depan."

conversation_history = []

print("="*80)
print("TEST SUITE: ASTA 4-STEP THOUGHT (EMOTION & AUTONOMY)")
print("Rule-based fallback: DISABLED")
print("="*80 + "\n")

def validate_thought(thought):
    issues = []
    # Cek Key-Value Wajib
    required_keys = ["topic", "asta_emotion", "need_search", "search_query", "use_memory", "tone", "note"]
    for k in required_keys:
        if k not in thought:
            issues.append(f"MISSING_KEY: {k}")
    
    # Cek Konsistensi Search
    if thought.get("need_search") and not thought.get("search_query"):
        issues.append("INCONSISTENT: Search is True but Query is empty.")
    
    # Cek Konsistensi Memory
    if thought.get("use_memory") and not thought.get("recall_topic") and not thought.get("reasoning"):
        issues.append("INCONSISTENT: Use Memory is True but no recall/reasoning provided.")

    return issues

for i, tc in enumerate(test_cases, 1):
    user_input = tc["input"]
    emotion_state = tc["emotion_state"]
    
    # Ambil konteks terbaru (2 turn terakhir)
    recent_context = extract_recent_context(conversation_history, n=2)
    
    print(f"TURN {i} | INPUT: {user_input}")
    print(f"EMOTION IN: {emotion_state} | EXPECTED: {tc['expected']}")
    
    thought = run_thought_pass(
        llm=llm,
        user_input=user_input,
        memory_context=memory_context,
        recent_context=recent_context,
        web_search_enabled=True,
        user_name="Aditiya",
        emotion_state=emotion_state,
        asta_state=asta_state,
        cfg=cfg
    )
    
    # Validasi Hasil
    issues = validate_thought(thought)
    
    print(format_thought_debug(thought))
    
    if issues:
        print(f"!!! ISSUES FOUND: {', '.join(issues)}")
    else:
        print("✓ Validation Passed (All keys & basic logic OK)")
    
    # Update Context for next turn (Simulasi append history)
    conversation_history.append({"role": "user", "content": user_input})
    
    # Gunakan 'note' sebagai proxy respons Asta
    response_proxy = thought.get('note', '[Respon Asta]')
    conversation_history.append({"role": "assistant", "content": response_proxy})
    
    print("-" * 40 + "\n")

print("Pengujian Selesai.")
