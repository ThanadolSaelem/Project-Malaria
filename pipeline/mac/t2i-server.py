#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t2i-server.py — เซิร์ฟเวอร์สร้างภาพ (text-to-image) แบบ generic + เสียบ LoRA ได้

ทำไมต้องมีตัวนี้แยก: llama.cpp/llama-server เสิร์ฟได้แต่ LLM — สร้างภาพไม่ได้
โมเดล T2I (diffusion) ต้องใช้ engine คนละชุด ตัวนี้ใช้ 🤗 diffusers รัน native บน Mac (Metal/MPS)
เป็น server แยกบนพอร์ตของตัวเอง (ดีฟอลต์ :8094) ตั้งค่าใน llama.env (ตัวแปร T2I_*)

จุดเด่น:
  - generic: ใส่โมเดล diffusers format อะไรก็ได้ (SDXL / Flux / Qwen-Image ฯลฯ) ผ่าน T2I_MODEL
  - เสียบ LoRA ได้ (T2I_LORA) ปรับน้ำหนักได้ (T2I_LORA_WEIGHT)
  - ต่อยอด finetune เองได้: LoRA ที่เทรนด้วย diffusers/ai-toolkit/kohya วางไฟล์แล้วชี้ T2I_LORA มาได้เลย
  - พูด OpenAI image API (/v1/images/generations) → เอาไปต่อ LiteLLM/สคริปต์อื่นได้

⚠️ ขอบเขต: นี่คือ "โครงสร้างกลาง (SFW)" — ใส่โมเดลที่ถูกลิขสิทธิ์/เหมาะสมเท่านั้น
   อย่าใช้กับโมเดล/LoRA ที่ถอด safety (uncensored/NSFW-bypass) — ผิดกติกาของโปรเจกต์นี้เอง

ติดตั้ง deps (ใน venv ของ Mac):
  pip install torch diffusers transformers accelerate safetensors peft \
              fastapi "uvicorn[standard]" pillow
  (Apple Silicon: torch รองรับ MPS อยู่แล้ว ไม่ต้องลง CUDA)

RAM คร่าว ๆ: SDXL ~7GB · Flux ~24GB · Qwen-Image ~40GB (ตัวใหญ่กินแรม/ช้าบน Mac)

หมายเหตุ finetune: การ "เทรน" LoRA ทำด้วย diffusers training scripts หรือ ai-toolkit/kohya
   (คนละสคริปต์กับตัวนี้ซึ่งเป็น inference). บน Mac/MPS เทรนได้แต่ช้า และ tooling บางตัว
   (bitsandbytes/xformers) เป็น CUDA-only — งานเทรนจริงจังแนะนำเครื่อง NVIDIA
"""
import os
import io
import base64
import time

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
import uvicorn

# ---- config จาก env (ตั้งใน llama.env) ----
MODEL = os.environ.get("T2I_MODEL", "")                       # HF id หรือ local path (diffusers format)
LORA = os.environ.get("T2I_LORA", "")                         # path ไฟล์/โฟลเดอร์ LoRA (ว่าง = ไม่ใช้)
LORA_W = float(os.environ.get("T2I_LORA_WEIGHT", "0.8"))      # น้ำหนัก LoRA 0..1
PORT = int(os.environ.get("T2I_PORT", "8094"))
ALIAS = os.environ.get("T2I_ALIAS", "image")
DTYPE = os.environ.get("T2I_DTYPE", "bf16").lower()           # bf16|fp16|fp32
OUTDIR = os.environ.get("T2I_OUTDIR", os.path.expanduser("~/t2i-out"))

app = FastAPI(title="t2i-server")
_pipe = None
_device = "cpu"


def _load():
    """โหลดโมเดลครั้งเดียวตอน start (lazy import เพื่อให้ไฟล์นี้ import ได้แม้ยังไม่ลง torch)"""
    global _pipe, _device
    import torch
    from diffusers import AutoPipelineForText2Image

    if not MODEL:
        raise RuntimeError("ยังไม่ได้ตั้ง T2I_MODEL (ใส่ HF id หรือ path ของโมเดล diffusers)")

    dt = {"bf16": torch.bfloat16, "fp16": torch.float16, "fp32": torch.float32}.get(DTYPE, torch.bfloat16)
    _device = "mps" if torch.backends.mps.is_available() else ("cuda" if torch.cuda.is_available() else "cpu")

    # AutoPipeline เดาสถาปัตยกรรมให้ (SD/SDXL ครอบคลุมดี; Flux/Qwen-Image รุ่นใหม่มาก
    # อาจต้องใช้ pipeline class เฉพาะ + deps เพิ่ม — ดู error ตอนโหลดแล้วปรับ)
    pipe = AutoPipelineForText2Image.from_pretrained(MODEL, torch_dtype=dt)
    pipe = pipe.to(_device)

    if LORA:
        pipe.load_lora_weights(LORA)
        # ตั้งน้ำหนัก adapter ถ้า pipeline รองรับ (ไม่ fuse เพื่อให้ปรับ/ถอดภายหลังได้)
        try:
            pipe.set_adapters(["default_0"], adapter_weights=[LORA_W])
        except Exception:
            pass
        print(f"[t2i] loaded LoRA: {LORA} (weight {LORA_W})")

    try:
        pipe.set_progress_bar_config(disable=True)
    except Exception:
        pass
    _pipe = pipe
    print(f"[t2i] ready: model={MODEL} device={_device} dtype={DTYPE} alias={ALIAS} port={PORT}")


class GenReq(BaseModel):
    prompt: str
    negative_prompt: Optional[str] = None
    steps: int = 30
    guidance: float = 5.0
    width: int = 1024
    height: int = 1024
    seed: Optional[int] = None


def _generate(req: GenReq):
    import torch
    if _pipe is None:
        raise HTTPException(503, "model ยังไม่พร้อม")
    gen = None
    if req.seed is not None:
        try:
            gen = torch.Generator(device=_device).manual_seed(req.seed)
        except Exception:
            torch.manual_seed(req.seed)
    kwargs = dict(prompt=req.prompt, num_inference_steps=req.steps,
                  guidance_scale=req.guidance, width=req.width, height=req.height)
    if req.negative_prompt:
        kwargs["negative_prompt"] = req.negative_prompt
    if gen is not None:
        kwargs["generator"] = gen
    image = _pipe(**kwargs).images[0]

    os.makedirs(OUTDIR, exist_ok=True)
    fn = os.path.join(OUTDIR, f"img_{int(time.time())}_{req.seed if req.seed is not None else 'rnd'}.png")
    image.save(fn)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    return fn, b64


@app.get("/health")
def health():
    return {"ok": _pipe is not None, "model": MODEL, "device": _device, "lora": LORA or None}


@app.get("/v1/models")
def models():
    return {"object": "list", "data": [{"id": ALIAS, "object": "model"}]}


@app.post("/generate")
def generate(req: GenReq):
    fn, b64 = _generate(req)
    return {"file": fn, "b64_png": b64}


class OAIImageReq(BaseModel):
    prompt: str
    n: int = 1
    size: str = "1024x1024"
    model: Optional[str] = None


@app.post("/v1/images/generations")
def oai_images(req: OAIImageReq):
    try:
        w, h = (int(x) for x in req.size.lower().split("x"))
    except Exception:
        w, h = 1024, 1024
    data = []
    for _ in range(max(1, req.n)):
        _, b64 = _generate(GenReq(prompt=req.prompt, width=w, height=h))
        data.append({"b64_json": b64})
    return {"created": int(time.time()), "data": data}


@app.on_event("startup")
def _startup():
    _load()


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
