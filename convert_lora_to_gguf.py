import argparse
import os
import json
import torch
from safetensors.torch import load_file
import gguf
import numpy as np

def get_gguf_name(name):
    parts = name.split('.')
    if "layers" not in parts:
        return None
    
    layer_idx = parts[parts.index("layers") + 1]
    
    mapping = {
        "q_proj": "attn_q",
        "k_proj": "attn_k",
        "v_proj": "attn_v",
        "o_proj": "attn_output",
        "gate_proj": "ffn_gate",
        "up_proj": "ffn_up",
        "down_proj": "ffn_down",
    }
    
    target_part = None
    for k, v in mapping.items():
        if k in parts:
            target_part = v
            break
            
    if not target_part:
        return None
        
    lora_type = "lora_a" if "lora_A" in name else "lora_b"
    return f"blk.{layer_idx}.{target_part}.weight.{lora_type}"

def convert_lora(input_path, output_path, alpha=None):
    print(f"[*] Loading adapter from {input_path}")
    tensors = load_file(input_path)
    
    if alpha is None:
        config_path = os.path.join(os.path.dirname(input_path), "adapter_config.json")
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                cfg = json.load(f)
                alpha = cfg.get("lora_alpha", 32)
                print(f"[*] Found alpha in config: {alpha}")
        else:
            alpha = 32
            print(f"[!] No adapter_config.json found, using default alpha: {alpha}")

    # GGUFWriter with architecture "qwen3" (to match your base model)
    writer = gguf.GGUFWriter(output_path, "qwen3")
    
    # Critical Metadata for llama.cpp compatibility
    writer.add_string("general.type", "adapter")
    writer.add_string("adapter.type", "lora")
    writer.add_string("general.architecture", "qwen3")
    writer.add_string("general.name", "Asta Qwen3 LoRA")
    
    # Gunakan float32 untuk alpha (seringkali menyebabkan GGML_ASSERT jika salah tipe)
    writer.add_float32("adapter.lora.alpha", float(alpha))
    
    count = 0
    for name, tensor in tensors.items():
        new_name = get_gguf_name(name)
        if new_name:
            data = tensor.to(torch.float32).numpy()
            writer.add_tensor(new_name, data)
            count += 1
            
    print(f"[*] Writing GGUF file to {output_path}...")
    writer.write_header_to_file()
    writer.write_kv_data_to_file()
    writer.write_tensors_to_file()
    writer.close()
    print(f"[V] Success! Converted {count} tensors.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="Path to adapter_model.safetensors")
    parser.add_argument("output", help="Path to output .gguf")
    parser.add_argument("--alpha", type=float, help="LoRA alpha")
    
    args = parser.parse_args()
    convert_lora(args.input, args.output, args.alpha)
