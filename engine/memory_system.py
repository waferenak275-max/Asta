import json
from pathlib import Path
import numpy as np
import datetime
import torch
from transformers import AutoTokenizer, AutoModel

HF_MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
LOCAL_MODEL_PATH = Path("model") / "embedding_model" / HF_MODEL_NAME.split('/')[-1]

if LOCAL_MODEL_PATH.exists():
    tokenizer = AutoTokenizer.from_pretrained(LOCAL_MODEL_PATH)
    model = AutoModel.from_pretrained(LOCAL_MODEL_PATH)
else:
    tokenizer = AutoTokenizer.from_pretrained(HF_MODEL_NAME)
    model = AutoModel.from_pretrained(HF_MODEL_NAME)
    LOCAL_MODEL_PATH.mkdir(parents=True, exist_ok=True)
    tokenizer.save_pretrained(LOCAL_MODEL_PATH)
    model.save_pretrained(LOCAL_MODEL_PATH)

def mean_pooling(model_output, attention_mask):
    token_embeddings = model_output[0] 
    input_mask_expanded = attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
    return torch.sum(token_embeddings * input_mask_expanded, 1) / torch.clamp(input_mask_expanded.sum(1), min=1e-9)

def create_embedding(text: str) -> np.ndarray:
    if not text:
        return np.zeros(model.config.hidden_size) 

    encoded_input = tokenizer(
        text,
        padding=True,
        truncation=True,
        return_tensors='pt'
    )

    with torch.no_grad():
        model_output = model(**encoded_input)

    sentence_embeddings = mean_pooling(model_output, encoded_input['attention_mask'])
    sentence_embeddings = torch.nn.functional.normalize(sentence_embeddings, p=2, dim=1)
    
    return sentence_embeddings[0].cpu().numpy()

class BaseMemory:
    def __init__(self, file_path: Path, default_content):
        self.file_path = file_path
        self._default_content = default_content
        self.data = self._load()

    def _load(self):
        if not self.file_path.exists() or self.file_path.stat().st_size == 0:
            self._save(self._default_content)
            return self._default_content
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError):
            print(f"[Memory Warning] File {self.file_path} rusak atau kosong, reset otomatis.")
            self._save(self._default_content)
            return self._default_content

    def _save(self, data):
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def save(self):
        self._save(self.data)

class SemanticMemory(BaseMemory):
    def __init__(self, directory: Path):
        super().__init__(directory / "semantic.json", default_content={})

    def add_fact(self, key: str, value: any):
        if self.data.get(key) != value:
            print(f"[Semantic Memory] Menambahkan/memperbarui fakta: {key} = {value}")
            self.data[key] = value
            self.save()

    def get_fact(self, key: str):
        return self.data.get(key)

    def get_all_facts(self):
        return self.data.copy()

class EpisodicMemory(BaseMemory):
    def __init__(self, directory: Path):
        super().__init__(directory / "episodic.json", default_content=[])

    def add(self, conversation: list):
        text_conversation = " ".join(f"{m['role']}: {m['content']}" for m in conversation)
        embedding = create_embedding(text_conversation).tolist()
        timestamp = datetime.datetime.now().isoformat()

        self.data.append({
            "timestamp": timestamp,
            "conversation": conversation,
            "embedding": embedding
        })
        print("[Episodic Memory] Menambahkan percakapan baru.")
        self.save()

    def search(self, query: str, top_k: int = 3, threshold: float = 0.1):
        if not self.data:
            return []

        query_embedding = create_embedding(query)
        
        sims = []
        for mem in self.data:
            mem_embedding = np.array(mem["embedding"])
            sim = np.dot(query_embedding, mem_embedding)
            sims.append(sim)

        top_indices = np.argsort(sims)[::-1][:top_k]

        results = [
            self.data[i] for i in top_indices if sims[i] > threshold
        ]
        
        if results:
            print(f"[Episodic Memory] Menemukan {len(results)} memori relevan.")
        
        return results

    def get_last_n_sessions(self, n: int = 4):
        return self.data[-n:]

class CoreMemory(BaseMemory):
    def __init__(self, directory: Path):
        super().__init__(directory / "core_memory.json", default_content={"summary": ""})

    def get_summary(self) -> str:
        return self.data.get("summary", "")

    def update_summary(self, summary_text: str):
        if self.data.get("summary") != summary_text:
            print(f"[Core Memory] Memperbarui ringkasan inti memori.")
            self.data["summary"] = summary_text
            self.save()

