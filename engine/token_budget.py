from dataclasses import dataclass
from typing import List, Dict, Optional

@dataclass
class TokenBudget:
    total_ctx: int = 8192
    response_reserved: int = 512
    system_identity: int = 350
    memory_budget: int = 600

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
        conversation_history: List[Dict],
        dynamic_context: Optional[Dict] = None,
        **kwargs
    ) -> tuple:
        """
        Strategi Ghost Context: 
        [System] + [History] + [Dynamic Context]
        Dynamic context diletakkan di akhir dan TIDAK disimpan di history permanen.
        """
        used_tokens = self.count_fn([system_identity])
        dynamic_cost = self.count_fn([dynamic_context]) if dynamic_context else 0
        conv_budget = self.budget.available_total - used_tokens - dynamic_cost

        clean_history = [
            m for m in conversation_history
            if m.get("role") in ("user", "assistant") and m.get("content")
        ]

        selected_history = []
        for msg in reversed(clean_history):
            cost = self.count_fn([msg])
            if conv_budget - cost >= 0:
                selected_history.insert(0, msg)
                conv_budget -= cost
            else:
                break

        # URUTAN KRUSIAL: Identitas -> Riwayat Bersih -> Konteks Dinamis (di akhir)
        final_messages = [system_identity] + selected_history
        if dynamic_context:
            final_messages.append(dynamic_context)

        total_tokens = self.count_fn(final_messages)
        return final_messages, total_tokens
