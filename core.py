import sys
import re
import argparse
from pathlib import Path

from config import load_config, save_config, setup_wizard
from engine.model import load_model
from engine.memory import (
    remember_identity,
    get_identity,
    add_episodic,
    get_hybrid_memory,
)

parser = argparse.ArgumentParser(description="Asta AI Companion")
parser.add_argument("--setup", action="store_true")
parser.add_argument("--debug", action="store_true")
args = parser.parse_args()

cfg = load_config()
if args.setup or not Path("config.json").exists():
    cfg = setup_wizard(cfg)

def get_or_set_user_name() -> str:
    current = get_identity("nama_user")
    if current:
        print(f"\nHalo! Aku ingat kamu: {current}")
        change = input("Ganti nama? (y/n, default = n): ").strip().lower()
        if change == "y":
            new_name = input("Nama baru: ").strip().capitalize()
            if new_name:
                remember_identity("nama_user", new_name)
                return new_name
        return current
    else:
        new_name = input("\nNama kamu siapa? (kosong = 'Aditiya'): ").strip().capitalize()
        name = new_name or "Aditiya"
        remember_identity("nama_user", name)
        return name


user_name = get_or_set_user_name()
cfg["_user_name"] = user_name

print("\n[Startup] Memuat model...")
chat_manager = load_model(cfg)

hybrid_mem = get_hybrid_memory()
chat_manager.hybrid_memory = hybrid_mem
chat_manager.debug_thought = args.debug

# Status
print("\n[Memory] Status:")
core_text = hybrid_mem.core.get_summary()
import numpy as np
ep_count = len([
    s for s in hybrid_mem.episodic.data
    if not np.allclose(np.array(s.get("embedding", [0])[:5]), 0.0)
])
print(f"  Core : {core_text[:80] + '...' if len(core_text) > 80 else core_text or '(kosong)'}")
print(f"  Sesi : {ep_count} sesi valid tersimpan")

profile = hybrid_mem.core.get_profile()
if profile.get("preferensi"):
    print(f"  Suka : {', '.join(profile['preferensi'][:3])}")

print("\n[Self-Model] Status:")
asta_e = chat_manager.self_model.get_emotion()
print(f"  Mood      : {asta_e.get('mood','netral')} (score: {asta_e.get('mood_score',0.0):+.2f})")
print(f"  Affection : {asta_e.get('affection_level',0.7):.2f}")
print(f"  Energy    : {asta_e.get('energy_level',0.8):.2f}")
refs = chat_manager.self_model.data.get("reflection_history", [])
if refs:
    print(f"  Refleksi  : {refs[-1].get('summary','–')[:60]}")

long_mode = cfg.get("long_thinking_enabled", False)
print(f"\n[Config] Long Thinking: {'ON' if long_mode else 'OFF'}")
print()

print("=" * 50)
print("  Asta siap! Ketik 'exit' untuk keluar.")
print("  Perintah: !memory | !self | !thought | !web | !long | !reflect")
if args.debug:
    print("  [DEBUG MODE] Internal thought ditampilkan.")
print("=" * 50 + "\n")

while True:
    sys.stdout.write("Kamu: ")
    sys.stdout.flush()
    user_input = sys.stdin.readline().strip()

    if not user_input:
        continue

    if user_input.lower() == "exit":
        print("\n[Exit] Menyimpan sesi...")
        conversation = chat_manager._clean_conversation()
        if conversation:
            hybrid_mem.extract_and_save_preferences(conversation)
        add_episodic(conversation)
        print("[Exit] Sesi disimpan ke episodic memory.")

        chat_manager.run_exit_reflection()

        session_text = chat_manager.get_session_text()
        if session_text:
            print("[Exit] Memperbarui core memory di background...")
            t = hybrid_mem.update_core_async(
                llm_callable=chat_manager.llama.create_completion,
                current_session_text=session_text,
            )
            if t:
                t.join(timeout=8)

        print(f"\nDaa {user_name}! Asta tunggu kamu balik ya~\n")
        break

    if user_input.lower() == "!memory":
        ctx = hybrid_mem.get_context(max_chars=1000)
        print(f"\n[Memory Context]\n{ctx}\n")
        continue

    if user_input.lower() == "!self":
        print(f"\n[Self-Model Asta]\n{chat_manager.self_model.get_full_context()}\n")
        print(f"[Emosi Asta]\n{chat_manager.emotion_manager.get_combined()['asta']}\n")
        continue

    if user_input.lower() == "!thought":
        chat_manager.debug_thought = not chat_manager.debug_thought
        print(f"[Debug] Thought: {'ON' if chat_manager.debug_thought else 'OFF'}\n")
        continue

    if user_input.lower() == "!web":
        cfg["web_search_enabled"] = not cfg.get("web_search_enabled", True)
        save_config(cfg)
        chat_manager.cfg = cfg
        print(f"[Config] Web search: {'ON' if cfg['web_search_enabled'] else 'OFF'}\n")
        continue

    if user_input.lower() == "!long":
        cfg["long_thinking_enabled"] = not cfg.get("long_thinking_enabled", False)
        save_config(cfg)
        chat_manager.cfg = cfg
        print(f"[Config] Long thinking: {'ON' if cfg['long_thinking_enabled'] else 'OFF'}\n")
        continue

    if user_input.lower() == "!reflect":
        print("[Manual] Menjalankan refleksi...")
        chat_manager.run_exit_reflection()
        continue

    try:
        chat_manager.chat(user_input)
    except Exception as e:
        print(f"[Error] {e}\n")
