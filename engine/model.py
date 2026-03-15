import llama_cpp
from llama_cpp.llama_tokenizer import LlamaHFTokenizer
import os
import sys
import contextlib
import io
from utils.spinner import Spinner

BASE_MODEL_PATH = "./model"

MODELS = {
    "1": {
        "name": "Sailor2 3B (lebih bodoh, lebih ringan)",
        "model_path": os.path.join(
            BASE_MODEL_PATH,
            "Sailor2-3B",
            "Sailor2-3B-Chat.Q4_K_M.gguf"
        ),
        "tokenizer_path": os.path.join(
            BASE_MODEL_PATH,
            "Sailor2-3B",
            "tokenizer"
        ),
    },
    "2": {
        "name": "Sailor2 8B (lebih pintar, lebih berat)",
        "model_path": os.path.join(
            BASE_MODEL_PATH,
            "Sailor2-8B",
            "Sailor2-8B-Chat-Q4_K_M.gguf"
        ),
        "tokenizer_path": os.path.join(
            BASE_MODEL_PATH,
            "Sailor2-8B",
            "tokenizer"
        ),
    },
}

"""
adapter_casual_plus.gguf
adapter_love.gguf
adapter_persona.gguf
adapter_persona_casual_plus.gguf
adapter_persona_love.gguf
"""
LORA_ADAPTER_PATH = "model/LoRA-all-adapter/adapter_persona_love_half.gguf"

def choose_lora_adapter():
    while True:
        use_lora = input("\nApakah Anda ingin menggunakan adaptor LoRA? (y/n, default = n): ").strip().lower()
        if use_lora == "y":
            if not os.path.exists(LORA_ADAPTER_PATH):
                print(f"Peringatan: Adaptor LoRA tidak ditemukan di {LORA_ADAPTER_PATH}.")
                return None, 0
            
            while True:
                try:
                    lora_gpu_layers_str = input(
                        f"Berapa banyak layer LoRA yang ingin di-offload ke GPU? (Default = 0, hanya CPU): "
                    ).strip()
                    lora_n_gpu_layers = int(lora_gpu_layers_str) if lora_gpu_layers_str else 0
                    break
                except ValueError:
                    print("Input tidak valid. Harap masukkan angka.")
            
            return LORA_ADAPTER_PATH, lora_n_gpu_layers
        elif use_lora == "n" or use_lora == "":
            return None, 0
        else:
            print("Pilihan tidak valid. Harap masukkan 'y' atau 'n'.")

class ChatManager:
    def __init__(self, llama: llama_cpp.Llama, system_prompt: str):
        self.llama = llama
        self.system_prompt = system_prompt
        self.history = [{"role": "system", "content": self.system_prompt}]
        self.n_ctx = llama.n_ctx()

    def _count_tokens(self, messages: list) -> int:
        templated_string = ""
        for message in messages:
            templated_string += f"<|im_start|>{message['role']}\n{message['content']}<|im_end|>\n"
        templated_string += "<|im_start|>assistant\n" 

        tokens = self.llama.tokenize(templated_string.encode("utf-8"))
        return len(tokens)

    def chat(self, user_input: str):
        self.history.append({"role": "user", "content": user_input})

        # Implementasi pemotongan riwayat (sliding window)
        messages_to_send = []
        # System prompt selalu disertakan
        messages_to_send.append(self.history[0])

        current_token_count = self._count_tokens(messages_to_send)
        # Reservasi token untuk respons model (max_tokens + buffer)
        # max_tokens di create_chat_completion adalah 128
        MAX_RESPONSE_TOKENS = 256
        available_tokens = self.n_ctx - MAX_RESPONSE_TOKENS

        # Tambahkan pesan dari riwayat (paling baru terlebih dahulu) hingga memenuhi batas
        for message in reversed(self.history[1:]): # Lewati system prompt
            temp_messages = [message] + messages_to_send
            if self._count_tokens(temp_messages) <= available_tokens:
                messages_to_send.insert(1, message) # Insert after system prompt
            else:
                break
        
        final_token_count = self._count_tokens(messages_to_send)
        print(f"[Info] Mengirim {final_token_count} token ke model.")
        sys.stdout.flush()
        # sys.stdout.write("\n") # Ensure spinner starts on a new, clean line
        # sys.stdout.flush()

        spinner = Spinner() # Using default joke messages
        spinner.start()

        response_stream = self.llama.create_chat_completion(
            messages=messages_to_send,
            max_tokens=128,
            temperature=0.7,
            top_p=0.85,
            top_k=60,
            stop=["<|im_end|>", "<|endoftext|>"],
            stream=True
        )

        full_response = ""
        first_chunk = True
        for chunk in response_stream:
            if first_chunk:
                spinner.stop() # Stops spinner and clears its line
                sys.stdout.write("Asta: ") # Prints "Asta: " on the cleared line
                sys.stdout.flush()
                first_chunk = False
            delta = chunk['choices'][0]['delta']
            if 'content' in delta:
                text = delta['content']
                sys.stdout.write(text)
                sys.stdout.flush()
                full_response += text
        
        sys.stdout.write("\n") # Prints a newline after the full response
        sys.stdout.flush()
        self.history.append({"role": "assistant", "content": full_response})
        return full_response

def choose_device():
    print("\nPilih mode komputasi:")
    print("1. CPU (stabil, kompatibel semua device)")
    print("2. GPU CUDA (lebih cepat, butuh NVIDIA)")

    device = input("\nPilihan (default = CPU): ").strip()

    if device == "2":
        print("\nMencoba menggunakan GPU CUDA...")
        return "gpu"

    print("\nMenggunakan CPU mode.")
    return "cpu"

def load_model(system_prompt: str):
    print("\nCUDA Support: ",llama_cpp.llama_cpp.llama_supports_gpu_offload())
    print("\nPilih model yang ingin digunakan:")

    for key, model in MODELS.items():
        print(f"{key}. {model['name']}")

    choice = input("\nPilihan (default = 1): ").strip()

    if choice not in MODELS:
        choice = "1"

    config = MODELS[choice]
    device = choose_device()

    lora_path, lora_n_gpu_layers = choose_lora_adapter()
    if lora_path and config["name"] != MODELS["2"]["name"]:
        print(f"\nPeringatan: Adaptor LoRA '{os.path.basename(lora_path)}' dirancang untuk model Sailor2 8B.")
        print(f"Secara otomatis memilih model Sailor2 8B.")
        choice = "2"
        config = MODELS[choice]
        # Re-check model path after changing config
        if not os.path.exists(config["model_path"]):
            raise FileNotFoundError(f"Model Sailor2 8B tidak ditemukan di {config['model_path']}")
        if not os.path.exists(config["tokenizer_path"]):
            raise FileNotFoundError(f"Tokenizer Sailor2 8B tidak ditemukan di {config['tokenizer_path']}")

    print(f"\nMemuat model: {config['name']}...\n")

    if device == "gpu":
        n_gpu_layers = 30
        n_threads = os.cpu_count() // 2
    else:
        n_gpu_layers = 0
        n_threads = os.cpu_count()

    if not os.path.exists(config["model_path"]):
        raise FileNotFoundError(f"Model tidak ditemukan: {config['model_path']}")

    if not os.path.exists(config["tokenizer_path"]):
        raise FileNotFoundError(f"Tokenizer tidak ditemukan: {config['tokenizer_path']}")

    tokenizer = LlamaHFTokenizer.from_pretrained(
        config["tokenizer_path"]
    )

    # Suppress stderr output during llama_cpp.Llama initialization
    with contextlib.redirect_stderr(io.StringIO()):
        llama = llama_cpp.Llama(
            model_path=config["model_path"],
            tokenizer=tokenizer,
            n_gpu_layers=n_gpu_layers,
            n_threads=n_threads,
            n_batch=1024,
            use_mmap=True,
            use_mlock=True,
            n_ctx=8192,
            verbose=False,
            lora_path=lora_path,
            lora_scale=1.5,
            lora_n_gpu_layers=lora_n_gpu_layers,
            log_level=0, # Attempt to suppress verbose logging from llama.cpp
        )
    
    print("Model siap digunakan!\n")
    
    return ChatManager(llama=llama, system_prompt=system_prompt)
