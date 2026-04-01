import asyncio
import json
import sys
import io
import threading
from contextlib import asynccontextmanager
from typing import Optional

# UTF-8 output agar tidak error di Windows
if sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# ─── State Global ─────────────────────────────────────────────────────────────

_chat_manager  = None
_hybrid_memory = None
_init_lock     = threading.Lock()
_initialized   = False
# Satu lock untuk mencegah dua request chat berjalan bersamaan pada ChatManager yang sama
_chat_lock     = asyncio.Lock()


# ─── Inisialisasi ─────────────────────────────────────────────────────────────

def _initialize_sync() -> None:
    """Jalankan di executor agar tidak block event loop."""
    global _chat_manager, _hybrid_memory, _initialized

    if _initialized:
        return

    with _init_lock:
        if _initialized:
            return

        from config import load_config
        from engine.model import load_model
        from engine.memory import get_hybrid_memory, get_identity

        cfg       = load_config()
        user_name = get_identity("nama_user") or "Aditiya"
        cfg["_user_name"] = user_name

        manager    = load_model(cfg)
        hybrid_mem = get_hybrid_memory()
        manager.hybrid_memory = hybrid_mem

        _chat_manager  = manager
        _hybrid_memory = hybrid_mem
        _initialized   = True


def _save_session_sync() -> int:
    """Simpan sesi ke episodic memory. Aman dipanggil dari thread manapun."""
    if not _initialized or not _chat_manager:
        return 0
    from engine.memory import add_episodic
    conv = _chat_manager._clean_conversation()
    if conv:
        _hybrid_memory.extract_and_save_preferences(conv)
        add_episodic(conv)
        session_text = _chat_manager.get_session_text()
        if session_text:
            _hybrid_memory.update_core_async(
                llm_callable=_chat_manager.llama.create_completion,
                current_session_text=session_text,
            )
    return len(conv)


# ─── Lifespan (menggantikan @on_event yang deprecated) ────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: load model di thread pool agar event loop tidak block
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _initialize_sync)
    yield
    # Shutdown: simpan sesi terakhir
    if _initialized:
        await loop.run_in_executor(None, _save_session_sync)


# ─── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(title="Asta AI API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Guard decorator ──────────────────────────────────────────────────────────

def _require_initialized():
    if not _initialized:
        return JSONResponse({"error": "Model belum siap."}, status_code=503)
    return None


# ─── REST Endpoints ───────────────────────────────────────────────────────────

@app.get("/status")
async def status():
    if not _initialized:
        return {"ready": False}
    import numpy as np
    ep_count = len([
        s for s in _hybrid_memory.episodic.data
        if not np.allclose(np.array(s.get("embedding", [0])[:5]), 0.0)
    ])
    is_dual = _chat_manager.llama_thought is not _chat_manager.llama
    return {
        "ready":             True,
        "model":             _chat_manager.cfg.get("model_choice", "?"),
        "device":            _chat_manager.cfg.get("device", "cpu"),
        "user_name":         _chat_manager._user_name,
        "episodic_sessions": ep_count,
        "dual_model":        is_dual,
        "thought_model":     "3B" if is_dual else "shared",
        "response_model":    "8B" if _chat_manager.cfg.get("model_choice", "2") == "2" else "3B",
        "long_thinking":     _chat_manager.cfg.get("long_thinking_enabled", False),
    }


@app.get("/memory")
async def get_memory():
    err = _require_initialized()
    if err:
        return err
    core_text    = _hybrid_memory.core.get_context_text()
    recent_facts = _hybrid_memory.episodic.get_recent_facts_text(n_sessions=3, max_facts=10)
    profile      = _hybrid_memory.core.get_profile()
    previews     = []
    for s in _hybrid_memory.episodic.get_last_n(5):
        conv       = s.get("conversation", [])
        first_user = next((m["content"] for m in conv if m["role"] == "user"), "")
        previews.append({
            "timestamp": s.get("timestamp", ""),
            "preview":   first_user[:80],
            "facts":     len(s.get("key_facts", [])),
        })
    return {
        "core":         core_text,
        "recent_facts": recent_facts,
        "profile":      profile,
        "sessions":     previews,
    }


@app.get("/self")
async def get_self_model():
    err = _require_initialized()
    if err:
        return err
    sm   = _chat_manager.self_model
    comb = _chat_manager.emotion_manager.get_combined()
    refs = sm.data.get("reflection_history", [])
    return {
        "identity":          sm.data.get("identity", {}),
        "emotional_state":   comb["asta"],
        "preferences":       sm.data.get("preferences", {}),
        "learned_behaviors": sm.data.get("learned_behaviors", {}),
        "memories_of_self":  sm.data.get("memories_of_self", [])[-5:],
        "growth_log":        sm.data.get("growth_log", [])[-5:],
        "last_reflection":   refs[-1] if refs else None,
        "reflection_count":  len(refs),
    }


@app.get("/emotion")
async def get_emotion():
    err = _require_initialized()
    if err:
        return err
    return _chat_manager.emotion_manager.get_combined()


@app.get("/config")
async def get_config():
    err = _require_initialized()
    if err:
        return err
    is_dual = _chat_manager.llama_thought is not _chat_manager.llama
    return {
        "internal_thought_enabled": _chat_manager.cfg.get("internal_thought_enabled", True),
        "web_search_enabled":       _chat_manager.cfg.get("web_search_enabled", True),
        "separate_thought_model":   _chat_manager.cfg.get("separate_thought_model", True),
        "long_thinking_enabled":    _chat_manager.cfg.get("long_thinking_enabled", False),
        "device":                   _chat_manager.cfg.get("device", "cpu"),
        "dual_model":               is_dual,
        "thought_model":            "3B" if is_dual else "shared",
        "response_model":           "8B" if _chat_manager.cfg.get("model_choice", "2") == "2" else "3B",
    }


@app.post("/config/thought")
async def toggle_thought():
    err = _require_initialized()
    if err:
        return err
    from config import save_config
    _chat_manager.cfg["internal_thought_enabled"] = \
        not _chat_manager.cfg.get("internal_thought_enabled", True)
    save_config(_chat_manager.cfg)
    return {"internal_thought_enabled": _chat_manager.cfg["internal_thought_enabled"]}


@app.post("/config/long_thinking")
async def toggle_long_thinking():
    """Toggle fitur long thinking on/off."""
    err = _require_initialized()
    if err:
        return err
    from config import save_config
    _chat_manager.cfg["long_thinking_enabled"] = \
        not _chat_manager.cfg.get("long_thinking_enabled", False)
    save_config(_chat_manager.cfg)
    return {"long_thinking_enabled": _chat_manager.cfg["long_thinking_enabled"]}


@app.post("/config/separate_thought")
async def toggle_separate_thought():
    err = _require_initialized()
    if err:
        return err
    from config import save_config
    _chat_manager.cfg["separate_thought_model"] = \
        not _chat_manager.cfg.get("separate_thought_model", True)
    save_config(_chat_manager.cfg)
    return {"separate_thought_model": _chat_manager.cfg["separate_thought_model"]}


@app.post("/config/device")
async def toggle_device():
    err = _require_initialized()
    if err:
        return err
    from config import save_config
    from engine.web_tools import invalidate_cfg_cache
    cur        = _chat_manager.cfg.get("device", "cpu")
    new_device = "gpu" if cur == "cpu" else "cpu"
    print(f"\n[System] Device: {cur.upper()} → {new_device.upper()}. Restart diperlukan.")
    sys.stdout.flush()
    _chat_manager.cfg["device"] = new_device
    save_config(_chat_manager.cfg)
    invalidate_cfg_cache()
    return {"device": new_device}


@app.post("/save")
async def save_session():
    err = _require_initialized()
    if err:
        return err
    loop    = asyncio.get_event_loop()
    saved_n = await loop.run_in_executor(None, _save_session_sync)
    return {"saved": saved_n}


@app.post("/reflect")
async def trigger_reflection():
    err = _require_initialized()
    if err:
        return err
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _chat_manager.run_exit_reflection)
    return {"status": "done"}


# ─── WebSocket: Terminal ──────────────────────────────────────────────────────

@app.websocket("/ws/terminal")
async def terminal_socket(websocket: WebSocket):
    """
    Terminal WebSocket untuk keperluan lokal/development.
    PERINGATAN: Tidak ada autentikasi — jangan expose ke publik.
    """
    await websocket.accept()
    import os
    import subprocess
    import shlex

    cwd = os.getcwd()

    try:
        while True:
            cmd_raw = await websocket.receive_text()
            if not cmd_raw.strip():
                continue

            parts = shlex.split(cmd_raw)
            if not parts:
                continue

            if parts[0] in ("cls", "clear"):
                await websocket.send_text("[CLEAR_SIGNAL]")
                await websocket.send_text(f"> {cwd} $ ")
                continue

            if parts[0] == "cd":
                if len(parts) > 1:
                    new_path = os.path.abspath(os.path.join(cwd, parts[1]))
                    if os.path.isdir(new_path):
                        cwd = new_path
                        await websocket.send_text(f"\n[CWD: {cwd}]\n")
                    else:
                        await websocket.send_text(f"\nDirectory not found: {parts[1]}\n")
                continue

            try:
                process = subprocess.Popen(
                    cmd_raw,
                    shell=True,
                    cwd=cwd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    universal_newlines=True,
                )
                for line in process.stdout:
                    await websocket.send_text(line)
                process.stdout.close()
                process.wait()
                await websocket.send_text(f"\n> {cwd} $ ")
            except Exception as e:
                await websocket.send_text(f"\nError: {e}\n")

    except WebSocketDisconnect:
        pass


# ─── WebSocket: Chat ──────────────────────────────────────────────────────────

@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    await websocket.accept()
    loop = asyncio.get_event_loop()

    try:
        while True:
            # Terima pesan dari client
            try:
                raw        = await websocket.receive_text()
                data       = json.loads(raw)
                user_input = data.get("message", "").strip()
            except json.JSONDecodeError:
                user_input = raw.strip() if raw else ""

            if not user_input:
                continue

            if not _initialized:
                await websocket.send_text(
                    json.dumps({"type": "error", "text": "Model belum siap."})
                )
                continue

            await websocket.send_text(json.dumps({"type": "thinking_start"}))

            # Queue untuk komunikasi antara thread dan async loop
            chunk_queue: asyncio.Queue = asyncio.Queue()

            async def _process_and_stream():
                """
                Satu fungsi yang menangani seluruh pipeline:
                thought → notify → generate → stream chunks.
                Semua exception tertangkap dan dikirim ke queue.
                """
                try:
                    # Gunakan lock agar tidak ada dua request berjalan bersamaan
                    async with _chat_lock:
                        thought_data: dict = {}

                        def thinking_callback(thought: dict) -> None:
                            """Dipanggil oleh chat() setelah thought selesai."""
                            thought_data.update(thought)
                            is_dual = _chat_manager.llama_thought is not _chat_manager.llama
                            payload = {
                                "type": "thought",
                                "data": {
                                    "topic":              thought.get("topic", ""),
                                    "sentiment":          thought.get("sentiment", ""),
                                    "urgency":            thought.get("urgency", ""),
                                    "asta_emotion":       thought.get("asta_emotion", ""),
                                    "asta_trigger":       thought.get("asta_trigger", ""),
                                    "should_express":     thought.get("should_express", False),
                                    "reasoning":          thought.get("reasoning", ""),
                                    "need_search":        thought.get("need_search", False),
                                    "search_query":       thought.get("search_query", ""),
                                    "web_result":         thought.get("web_result", ""),
                                    "recall_topic":       thought.get("recall_topic", ""),
                                    "use_memory":         thought.get("use_memory", False),
                                    "recall_source":      thought.get("recall_source", "none"),
                                    "tone":               thought.get("tone", ""),
                                    "note":               thought.get("note", ""),
                                    "response_style":     thought.get("response_style", ""),
                                    "is_long_thinking":   thought.get("is_long_thinking", False),
                                    "hidden_need":        thought.get("hidden_need", ""),
                                    "response_structure": thought.get("response_structure", ""),
                                    "emotion": _chat_manager.emotion_manager.get_state(),
                                    "asta_state": _chat_manager.emotion_manager.get_asta_dict(),
                                    "model_info": {
                                        "dual_model":     is_dual,
                                        "thought_model":  "3B" if is_dual else "shared",
                                        "response_model": (
                                            "8B"
                                            if _chat_manager.cfg.get("model_choice", "2") == "2"
                                            else "3B"
                                        ),
                                    },
                                },
                            }
                            # Kirim thought ke queue secara thread-safe
                            loop.call_soon_threadsafe(
                                chunk_queue.put_nowait,
                                {"type": "thought_payload", "payload": payload},
                            )

                        def stream_callback(text: str) -> None:
                            """Dipanggil oleh chat() tiap token."""
                            loop.call_soon_threadsafe(
                                chunk_queue.put_nowait,
                                {"type": "chunk", "text": text},
                            )

                        # Jalankan chat() di thread executor (blocking)
                        await loop.run_in_executor(
                            None,
                            lambda: _chat_manager.chat(
                                user_input=user_input,
                                stream_callback=stream_callback,
                                thinking_callback=thinking_callback,
                            ),
                        )

                    # Selesai
                    loop.call_soon_threadsafe(
                        chunk_queue.put_nowait, {"type": "done"}
                    )

                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    loop.call_soon_threadsafe(
                        chunk_queue.put_nowait,
                        {"type": "error", "text": f"Error: {e}"},
                    )

            # Jalankan pipeline sebagai task terpisah
            task = asyncio.create_task(_process_and_stream())

            # Konsumsi queue dan forward ke WebSocket
            stream_started = False
            try:
                while True:
                    try:
                        # Timeout guard: jika tidak ada item dalam 120 detik, anggap hang
                        item = await asyncio.wait_for(chunk_queue.get(), timeout=120.0)
                    except asyncio.TimeoutError:
                        await websocket.send_text(
                            json.dumps({"type": "error", "text": "Timeout: response terlalu lama."})
                        )
                        task.cancel()
                        break

                    if item["type"] == "error":
                        await websocket.send_text(json.dumps({"type": "error", "text": item["text"]}))
                        break

                    elif item["type"] == "thought_payload":
                        await websocket.send_text(json.dumps(item["payload"]))
                        await websocket.send_text(json.dumps({"type": "stream_start"}))
                        stream_started = True

                    elif item["type"] == "chunk":
                        await websocket.send_text(json.dumps({"type": "chunk", "text": item["text"]}))

                    elif item["type"] == "done":
                        await websocket.send_text(json.dumps({"type": "stream_end"}))
                        break

            except WebSocketDisconnect:
                # Simpan sesi jika user disconnect mendadak
                task.cancel()
                await loop.run_in_executor(None, _save_session_sync)
                return

    except WebSocketDisconnect:
        # Simpan sesi jika koneksi terputus di level luar
        await loop.run_in_executor(None, _save_session_sync)
    except Exception as e:
        try:
            await websocket.send_text(json.dumps({"type": "error", "text": str(e)}))
        except Exception:
            pass
