from dataclasses import dataclass
from typing import List, Dict, Optional


@dataclass
class TokenBudget:
    total_ctx: int = 8192
    response_reserved: int = 512
    system_identity: int = 350
    memory_budget: int = 600

    @property
    def conversation_budget(self) -> int:
        return (
            self.total_ctx
            - self.response_reserved
            - self.system_identity
            - self.memory_budget
        )

    @property
    def available_total(self) -> int:
        return self.total_ctx - self.response_reserved


class TokenBudgetManager:
    def __init__(self, budget: TokenBudget, count_fn):
        self.budget   = budget
        self.count_fn = count_fn

    def build_messages(
        self,
        system_identity: Dict,
        memory_messages: List[Dict],      # tidak dipakai, dipertahankan compat
        conversation_history: List[Dict],
        dynamic_context: Optional[Dict] = None,
    ) -> tuple:
        """
        Susun messages dengan urutan yang BENAR untuk memaksimalkan KV cache.

        llama.cpp melakukan prefix-match secara LINEAR dari token pertama.
        Begitu ada satu token berbeda, semua token setelahnya harus re-eval.

        URUTAN OPTIMAL:
          [0]   system_identity    ← konstan setiap turn → selalu cache hit
          [1]   user_turn_1        ← konstan sejak turn 1 → cache hit ab turn 2
          [2]   assistant_turn_1   ← konstan → cache hit
          ...
          [N-1] user_turn_N        ← turn ini (baru)
          [N]   dynamic_context    ← TERAKHIR, tepat sebelum asisten menjawab
                                     Berubah tiap turn tapi di akhir — tidak
                                     memutus cache conversation di atasnya

        Dengan urutan ini:
          Turn 1: 0 cache hit (semua baru)
          Turn 2: hit untuk [0]+[1]+[2] = system + turn1_user + turn1_assistant
          Turn 3: hit untuk [0]+[1]+[2]+[3]+[4] = system + turn1 + turn2
          ...dan seterusnya bertambah ~2 pesan per turn

        CATATAN: conversation_history HARUS hanya berisi role:user dan role:assistant.
        Jangan pernah menyimpan role:system di conversation_history.
        """
        # Filter: hanya user & assistant, bersih dari system
        clean_history = [
            m for m in conversation_history
            if m.get("role") in ("user", "assistant") and m.get("content")
        ]

        # Ambil dari belakang sesuai budget DENGAN hitung token penuh (akurasi lebih baik).
        # NOTE: count_fn menambahkan suffix assistant setiap kali dipanggil,
        # jadi hitung per-pesan bisa over-estimate. Gunakan evaluasi incremental
        # pada keseluruhan prompt agar keputusan trimming lebih presisi.
        max_prompt_tokens = self.budget.available_total
        selected = []

        def _build_prompt(msgs: List[Dict]) -> List[Dict]:
            result = [system_identity] + msgs
            if dynamic_context:
                result.append(dynamic_context)
            return result

        for msg in reversed(clean_history):
            trial_selected = [msg] + selected
            trial_prompt = _build_prompt(trial_selected)
            if self.count_fn(trial_prompt) <= max_prompt_tokens:
                selected = trial_selected
            else:
                break

        # Susun: [system] + [conversation...] + [dynamic_context]
        # dynamic_context DI AKHIR agar tidak memutus cache conversation
        result = _build_prompt(selected)

        total = self.count_fn(result)
        return result, total
