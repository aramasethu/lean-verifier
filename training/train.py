import json
import os

import boto3
import torch
from datasets import Dataset
from peft import LoraConfig, get_peft_model
from transformers import AutoModelForCausalLM, AutoTokenizer
from trl import SFTConfig, SFTTrainer

MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "http://minio:9000")
MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "minio")
MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "minio12345")
MINIO_BUCKET = os.environ.get("MINIO_BUCKET", "proofs")
ADAPTER_VERSION = os.environ.get("ADAPTER_VERSION", "1")

MODEL_NAME = os.environ.get("MODEL_NAME", "Qwen/Qwen2.5-0.5B-Instruct")
NUM_EPOCHS = int(os.environ.get("NUM_EPOCHS", "1"))
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "1"))
GRAD_ACCUM = int(os.environ.get("GRAD_ACCUM", "8"))
LR = float(os.environ.get("LR", "1e-4"))
LORA_RANK = int(os.environ.get("LORA_RANK", "8"))
MAX_SEQ_LEN = int(os.environ.get("MAX_SEQ_LEN", "256"))


def load_training_data(s3) -> list[dict]:
    examples = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=MINIO_BUCKET, Prefix="successes/"):
        for obj in page.get("Contents", []):
            body = s3.get_object(Bucket=MINIO_BUCKET, Key=obj["Key"])["Body"].read()
            record = json.loads(body)
            examples.append({"text": record["proof_str"]})
    return examples


def upload_adapter(s3, local_dir: str, version: str) -> None:
    for root, _, files in os.walk(local_dir):
        for filename in files:
            local_path = os.path.join(root, filename)
            rel_path = os.path.relpath(local_path, local_dir)
            key = f"adapters/adapter-v{version}/{rel_path}"
            s3.upload_file(local_path, MINIO_BUCKET, key)
            print(f"  uploaded {key}", flush=True)


def main() -> None:
    s3 = boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        region_name="us-east-1",
    )

    print("loading training data from MinIO...", flush=True)
    examples = load_training_data(s3)
    print(f"  {len(examples)} examples loaded", flush=True)
    if not examples:
        raise SystemExit("no training data in successes/ — run inference+verify first")

    dataset = Dataset.from_list(examples)

    print(f"loading {MODEL_NAME}...", flush=True)
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(MODEL_NAME, dtype=torch.float32)

    print("attaching LoRA adapter...", flush=True)
    lora_config = LoraConfig(
        r=LORA_RANK,
        lora_alpha=LORA_RANK * 2,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    config = SFTConfig(
        output_dir="/tmp/training",
        num_train_epochs=NUM_EPOCHS,
        per_device_train_batch_size=BATCH_SIZE,
        gradient_accumulation_steps=GRAD_ACCUM,
        learning_rate=LR,
        logging_steps=5,
        save_strategy="no",
        report_to=[],
        dataset_text_field="text",
        use_cpu=True,
        bf16=False,
        fp16=False,
    )

    trainer = SFTTrainer(
        model=model,
        train_dataset=dataset,
        args=config,
        processing_class=tokenizer,
    )

    print("starting training...", flush=True)
    trainer.train()

    print("saving adapter locally...", flush=True)
    adapter_dir = "/tmp/adapter"
    model.save_pretrained(adapter_dir)
    tokenizer.save_pretrained(adapter_dir)

    print(f"uploading to MinIO adapters/adapter-v{ADAPTER_VERSION}/...", flush=True)
    upload_adapter(s3, adapter_dir, ADAPTER_VERSION)

    print("DONE", flush=True)


if __name__ == "__main__":
    main()
