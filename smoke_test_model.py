import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

MODEL_NAME = "Qwen/Qwen2.5-0.5B-Instruct"

print(f"Loading {MODEL_NAME}...")
tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
model = AutoModelForCausalLM.from_pretrained(MODEL_NAME, dtype=torch.float32)

prompt = "Prove that 1 + 1 = 2 in Lean 4:\n"
inputs = tokenizer(prompt, return_tensors="pt")
print("Generating...")
out = model.generate(**inputs, max_new_tokens=30, do_sample=False)
print("---")
print(tokenizer.decode(out[0], skip_special_tokens=True))
print("---")
print("OK")
