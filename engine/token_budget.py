from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

@dataclass
class TokenBudget:
    total_ctx:        int = 8192
    response_reserved: int = 512
    system_identity:  int = 350
    memory_budget:    int = 600

    @property
    def available_total(self) -> int:
        return self.total_ctx - self.response_reserved

# Susun messages yang akan dikirim ke model dengan batasan token.
# Urutan prioritas (dari tertinggi):
# 1. system_identity selalu masuk
# 2. dynamic_context selalu masuk (berisi memori, emosi, catatan thought)
# 3. conversation_history dipotong dari yang paling lama jika budget habis
# Returns: (final_messages, total_token_count)
class TokenBudgetManager:
    def __init__(self, budget: TokenBudget, count_fn: Callable[[List[Dict]], int]):
        self.budget   = budget
        self.count_fn = count_fn

    def build_messages(
        self,
        system_identity:      Dict,
        conversation_history: List[Dict],
        dynamic_context:      Optional[Dict] = None,
    ) -> tuple:
        
        # Hitung slot yang sudah terpakai
        used = self.count_fn([system_identity])
        if dynamic_context:
            used += self.count_fn([dynamic_context])

        conv_budget = self.budget.available_total - used

        # Pilih history dari belakang (terbaru)
        clean_history = [
            m for m in conversation_history
            if m.get("role") in ("user", "assistant") and m.get("content")
        ]

        selected: List[Dict] = []
        for msg in reversed(clean_history):
            cost = self.count_fn([msg])
            if conv_budget - cost >= 0:
                selected.insert(0, msg)
                conv_budget -= cost
            else:
                break 

        final = [system_identity]
        if dynamic_context:
            final.append(dynamic_context)
        final.extend(selected)

        total_tokens = self.count_fn(final)
        return final, total_tokens

    def estimate_memory_chars(self) -> int:
        return self.budget.memory_budget * 3
