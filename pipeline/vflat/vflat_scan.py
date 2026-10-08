"""vFlat scan pipeline — port จาก Android (TFLite + GLSL) มาเป็น numpy/OpenCV ล้วน
ไม่ต้องใช้ OpenGL / ไม่ต้องใช้ libnative-scan.so

ที่มาของแต่ละสูตร:
  - ลำดับ pipeline              : p468Xa/C5598e.java  (m7781a)
  - deobfuscate (Scan.dof)      : freeform::model::deobfuscate  -> permutation table
  - calcOutputSize              : freeform::model::calcOutputSize (disasm)
  - texcoord = g*(1,0.75)+0.5   : rm_freeform_vs_2.glsl
  - enhance                     : enhance_cs.glsl
  - sharpen                     : sharpen_fs.glsl
"""
from __future__ import annotations

import json
import os

import cv2
import numpy as np

try:
    from ai_edge_litert.interpreter import Interpreter
except ImportError:
    from tflite_runtime.interpreter import Interpreter

MODEL_DIR = os.environ.get("VFLAT_MODELS", "/models")
PERM_PATH = os.environ.get("VFLAT_PERM", "/models/freeform_perm.json")

# freeform input = 1x192x144x4  (NHWC -> H=192, W=144)
FF_H, FF_W = 192, 144
GRID = 25          # rm_freeform_vs_2.glsl : TEXTURE_SIZE = 25
ENH = 320          # enhance / mask models
BP = 20            # blackpoint output 20x20

# enhance_cs.glsl
EQUALITY_THRESHOLD = 0.05
WHITEN_RATIO = 255.0 / 230.0
WHITENESS_THRESHOLD = 205.0 / 255.0

_PRE = [
    0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x01,0x01,0x01,0x01,0x01,0x01,0x02,
    0x02,0x02,0x02,0x02,0x03,0x03,0x03,0x04,0x04,0x04,0x05,0x05,0x06,0x06,0x07,0x07,
    0x08,0x08,0x09,0x0A,0x0A,0x0B,0x0C,0x0D,0x0D,0x0E,0x0F,0x10,0x11,0x12,0x13,0x14,
    0x15,0x16,0x17,0x18,0x19,0x1A,0x1B,0x1C,0x1E,0x1F,0x20,0x21,0x22,0x23,0x24,0x25,
    0x26,0x28,0x29,0x2A,0x2B,0x2C,0x2D,0x2E,0x30,0x31,0x32,0x33,0x34,0x35,0x37,0x38,
    0x39,0x3A,0x3B,0x3D,0x3E,0x3F,0x40,0x41,0x43,0x44,0x45,0x46,0x48,0x49,0x4A,0x4B,
    0x4C,0x4E,0x4F,0x50,0x51,0x53,0x54,0x55,0x56,0x58,0x59,0x5A,0x5B,0x5D,0x5E,0x5F,
    0x61,0x62,0x63,0x64,0x66,0x67,0x68,0x69,0x6B,0x6C,0x6D,0x6F,0x70,0x71,0x72,0x74,
    0x75,0x76,0x78,0x79,0x7A,0x7B,0x7D,0x7E,0x7F,0x80,0x82,0x83,0x84,0x86,0x87,0x88,
    0x89,0x8B,0x8C,0x8D,0x8F,0x90,0x91,0x92,0x94,0x95,0x96,0x97,0x99,0x9A,0x9B,0x9C,
    0x9E,0x9F,0xA0,0xA1,0xA3,0xA4,0xA5,0xA6,0xA8,0xA9,0xAA,0xAB,0xAD,0xAE,0xAF,0xB0,
    0xB2,0xB3,0xB4,0xB5,0xB6,0xB8,0xB9,0xBA,0xBB,0xBC,0xBE,0xBF,0xC0,0xC1,0xC2,0xC4,
    0xC5,0xC6,0xC7,0xC8,0xC9,0xCB,0xCC,0xCD,0xCE,0xCF,0xD0,0xD2,0xD3,0xD4,0xD5,0xD6,
    0xD7,0xD8,0xD9,0xDA,0xDB,0xDC,0xDD,0xDE,0xDF,0xE0,0xE1,0xE2,0xE3,0xE4,0xE5,0xE5,
    0xE6,0xE7,0xE8,0xE9,0xEA,0xEB,0xEB,0xEC,0xED,0xEE,0xEF,0xEF,0xF0,0xF1,0xF2,0xF3,
    0xF3,0xF4,0xF5,0xF6,0xF6,0xF7,0xF8,0xF9,0xF9,0xFA,0xFB,0xFB,0xFC,0xFD,0xFE,0xFF,
]
_POST = [
    0x00,0x00,0x01,0x02,0x03,0x04,0x05,0x06,0x07,0x08,0x09,0x0a,0x0b,0x0c,0x0d,0x0e,
    0x0f,0x10,0x10,0x11,0x12,0x13,0x14,0x15,0x16,0x16,0x17,0x18,0x19,0x1a,0x1b,0x1b,
    0x1c,0x1d,0x1e,0x1e,0x1f,0x20,0x21,0x21,0x22,0x23,0x24,0x24,0x25,0x26,0x27,0x27,
    0x28,0x29,0x29,0x2a,0x2b,0x2b,0x2c,0x2d,0x2d,0x2e,0x2f,0x2f,0x30,0x31,0x31,0x32,
    0x33,0x33,0x34,0x35,0x35,0x36,0x37,0x37,0x38,0x39,0x39,0x3a,0x3a,0x3b,0x3c,0x3c,
    0x3d,0x3e,0x3e,0x3f,0x40,0x40,0x41,0x42,0x42,0x43,0x44,0x45,0x45,0x46,0x47,0x47,
    0x48,0x49,0x4a,0x4a,0x4b,0x4c,0x4d,0x4d,0x4e,0x4f,0x50,0x50,0x51,0x52,0x53,0x54,
    0x54,0x55,0x56,0x57,0x58,0x59,0x5a,0x5b,0x5b,0x5c,0x5d,0x5e,0x5f,0x60,0x61,0x62,
    0x63,0x64,0x65,0x66,0x67,0x68,0x69,0x6a,0x6b,0x6c,0x6e,0x6f,0x70,0x71,0x72,0x73,
    0x74,0x76,0x77,0x78,0x79,0x7a,0x7c,0x7d,0x7e,0x80,0x81,0x82,0x83,0x85,0x86,0x87,
    0x89,0x8a,0x8b,0x8d,0x8e,0x90,0x91,0x92,0x94,0x95,0x97,0x98,0x9a,0x9b,0x9d,0x9e,
    0xa0,0xa1,0xa3,0xa4,0xa6,0xa7,0xa9,0xaa,0xac,0xad,0xaf,0xb1,0xb2,0xb4,0xb5,0xb7,
    0xb8,0xba,0xbb,0xbd,0xbf,0xc0,0xc2,0xc3,0xc5,0xc6,0xc8,0xca,0xcb,0xcd,0xce,0xd0,
    0xd1,0xd3,0xd4,0xd6,0xd7,0xd9,0xda,0xdc,0xdd,0xde,0xe0,0xe1,0xe2,0xe4,0xe5,0xe6,
    0xe8,0xe9,0xea,0xeb,0xed,0xee,0xef,0xf0,0xf1,0xf2,0xf3,0xf4,0xf5,0xf6,0xf7,0xf8,
    0xf9,0xf9,0xfa,0xfb,0xfc,0xfc,0xfd,0xfd,0xfe,0xfe,0xfe,0xff,0xff,0xff,0xff,0xff,
]
PRE_LUT = np.array(_PRE, dtype=np.float32) / 255.0
POST_LUT = np.array(_POST, dtype=np.float32) / 255.0


class _Model:
    """โหลด tflite แบบ lazy + รันครั้งละภาพ"""

    def __init__(self, name: str):
        self.path = os.path.join(MODEL_DIR, name + ".tflite")
        self._it = None

    def __call__(self, x: np.ndarray) -> np.ndarray:
        if self._it is None:
            self._it = Interpreter(model_path=self.path, num_threads=int(os.environ.get("VFLAT_THREADS", "4")))
            self._it.allocate_tensors()
            self._in = self._it.get_input_details()[0]
            self._out = self._it.get_output_details()[0]
        self._it.set_tensor(self._in["index"], x.astype(self._in["dtype"]))
        self._it.invoke()
        return self._it.get_tensor(self._out["index"]).copy()


freeform = _Model("freeform_v3_2")
enhance_model = _Model("enhance_v10")
blackpoint_cls = _Model("blackpoint_classification_v1_0_1")
blackpoint = _Model("blackpoint_v1_0_1")

_PERM = None


def _perm() -> np.ndarray:
    global _PERM
    if _PERM is None:
        _PERM = np.array(json.load(open(PERM_PATH)), dtype=np.int32)
    return _PERM


# ---------------------------------------------------------------- helpers
def _to_rgba_f32(img_bgr: np.ndarray) -> np.ndarray:
    rgba = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGBA)
    return rgba.astype(np.float32) / 255.0


def pad_to_model_aspect(img: np.ndarray) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    """pad_fs.glsl — ขยาย canvas ให้ได้อัตราส่วน 144:192 โดยเติมขอบแบบ replicate
    (shader ใช้ CLAMP_TO_EDGE จึงเป็นการยืดขอบ ไม่ใช่แถบดำ)

    คืน (ภาพที่ pad แล้ว, กรอบของเนื้อหาจริง (x, y, w, h) ในพิกัดของภาพนั้น)
    """
    h, w = img.shape[:2]
    f11 = (h * FF_W) / (w * FF_H)
    if f11 < 1.0:
        f5, f11 = 1.0 / f11, 1.0
    else:
        f5 = 1.0
    new_w, new_h = int(w * f11), int(h * f5)
    dx, dy = (new_w - w) // 2, (new_h - h) // 2
    padded = cv2.copyMakeBorder(img, dy, new_h - h - dy, dx, new_w - w - dx, cv2.BORDER_REPLICATE)
    return padded, (dx, dy, w, h)


def _trim_padding(img: np.ndarray, valid: np.ndarray, thresh: float = 0.5) -> np.ndarray:
    """ตัดขอบที่ไปดูดพื้นที่ pad (ขอบยืด) ออก — ตัดเฉพาะแถว/คอลัมน์ริมที่ valid ต่ำกว่าเกณฑ์"""
    rows, cols = valid.mean(axis=1), valid.mean(axis=0)
    h, w = valid.shape

    y0 = 0
    while y0 < h and rows[y0] < thresh:
        y0 += 1
    y1 = h
    while y1 > y0 + 1 and rows[y1 - 1] < thresh:
        y1 -= 1
    x0 = 0
    while x0 < w and cols[x0] < thresh:
        x0 += 1
    x1 = w
    while x1 > x0 + 1 and cols[x1 - 1] < thresh:
        x1 -= 1

    if y1 - y0 < h * 0.2 or x1 - x0 < w * 0.2:   # กันตัดเกินจนภาพหาย
        return img
    return img[y0:y1, x0:x1]


def deobfuscate(raw: np.ndarray) -> np.ndarray:
    """freeform::model::deobfuscate — out[perm[i]] = in[i]; out[905] = in[1250]"""
    out = np.empty(1251, dtype=np.float32)
    out[_perm()] = raw[:1250]
    out[905] = raw[1250]
    return out


def calc_output_size(padded_w: int, buf: np.ndarray) -> tuple[int, int]:
    """freeform::model::calcOutputSize (disasm ที่ 0x1c57c)"""
    aspect = float(buf[1250])
    if aspect <= 0.0:
        return 0, 0
    aspect = max(aspect, 0.1)
    g = buf[:1250].reshape(GRID, GRID, 2)
    seg = np.linalg.norm(np.diff(g, axis=1), axis=2)   # ระยะระหว่างจุดในแถว
    avg_len = float(seg.sum(axis=1).mean())
    if avg_len >= 2.0:
        return 0, 0
    return int(avg_len * padded_w), int(min(aspect, 10.0) * avg_len * padded_w)


def dewarp(img_bgr: np.ndarray, trim: bool = True) -> np.ndarray:
    padded, (cx, cy, cw, ch) = pad_to_model_aspect(img_bgr)
    ph, pw = padded.shape[:2]

    inp = cv2.resize(padded, (FF_W, FF_H), interpolation=cv2.INTER_AREA)
    raw = freeform(_to_rgba_f32(inp)[None]).reshape(-1)
    buf = deobfuscate(raw)

    out_w, out_h = calc_output_size(pw, buf)
    if out_w <= 0 or out_h <= 0:
        raise ValueError(f"freeform ให้ขนาดไม่ถูกต้อง (w={out_w}, h={out_h})")

    # rm_freeform_vs_2.glsl : textureCoord = freeformOutput * vec2(1.0, 0.75) + 0.5
    g = buf[:1250].reshape(GRID, GRID, 2)
    tc = g * np.array([1.0, FF_W / FF_H], dtype=np.float32) + 0.5

    # ขยาย grid 25x25 -> ขนาด output เต็ม แล้ว remap ทีเดียว (แทน mesh 64x64 บน GPU)
    mapx = cv2.resize(tc[..., 0], (out_w, out_h), interpolation=cv2.INTER_CUBIC) * (pw - 1)
    mapy = cv2.resize(tc[..., 1], (out_w, out_h), interpolation=cv2.INTER_CUBIC) * (ph - 1)
    out = cv2.remap(padded, mapx, mapy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)

    if trim:
        valid = (
            (mapx >= cx) & (mapx <= cx + cw - 1) & (mapy >= cy) & (mapy <= cy + ch - 1)
        )
        out = _trim_padding(out, valid)
    return out


def sharpen(img: np.ndarray) -> np.ndarray:
    """sharpen_fs.glsl — unsharp mask, gauss [1,2,1;2,4,2;1,2,1]/16, amount = 1.0"""
    k = np.array([[1, 2, 1], [2, 4, 2], [1, 2, 1]], dtype=np.float32) / 16.0
    f = img.astype(np.float32)
    blur = cv2.filter2D(f, -1, k, borderType=cv2.BORDER_REPLICATE)
    return np.clip(f + (f - blur), 0, 255).astype(np.uint8)


def _lut(x: np.ndarray, lut: np.ndarray) -> np.ndarray:
    idx = np.clip((x * 255.0).astype(np.int32), 0, 255)
    return lut[idx]


def enhance(img_bgr: np.ndarray) -> np.ndarray:
    """enhance_cs.glsl — flat-field correction ด้วย distillation + blackpoint"""
    h, w = img_bgr.shape[:2]
    small = cv2.resize(img_bgr, (ENH, ENH), interpolation=cv2.INTER_AREA)
    small_rgba = _to_rgba_f32(small)[None]

    distill = enhance_model(small_rgba)[0]                      # 320x320x4
    apply_bp = float(blackpoint_cls(small_rgba)[0][0]) < 0.0    # C5598e.java:398
    bp_map = blackpoint(small_rgba)[0] if apply_bp else None    # 20x20x4

    inp = _to_rgba_f32(img_bgr)
    dis = cv2.resize(distill, (w, h), interpolation=cv2.INTER_LINEAR)

    # ถ้าเกือบเท่ากันให้ใช้ input (กันหารเพี้ยนในพื้นที่เรียบ)
    eq = np.all(np.abs(inp - dis) < EQUALITY_THRESHOLD, axis=2, keepdims=True)
    dis = np.where(eq, inp, dis)

    a = _lut(np.clip(inp, 0, 1), PRE_LUT)
    b = _lut(np.clip(dis, 0, 1), PRE_LUT)
    out = np.clip(a / np.clip(b, 1e-7, 1.0), 0.0, 1.0)

    if bp_map is not None:
        bp = cv2.resize(bp_map, (w, h), interpolation=cv2.INTER_LINEAR)
        out = np.clip((out - bp) / np.clip(1.0 - bp, 1e-7, 1.0), 0.0, 1.0)

    out = _lut(out, POST_LUT)
    y = out[..., :3] @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    m = y > WHITENESS_THRESHOLD
    out[..., :3] = np.where(m[..., None], np.clip(out[..., :3] * WHITEN_RATIO, 0, 1), out[..., :3])

    rgba8 = (out * 255.0 + 0.5).astype(np.uint8)
    return cv2.cvtColor(rgba8, cv2.COLOR_RGBA2BGR)


def scan(img_bgr: np.ndarray, do_dewarp=True, do_sharpen=True, do_enhance=True, trim=True) -> np.ndarray:
    out = img_bgr
    if do_dewarp:
        out = dewarp(out, trim=trim)
    if do_sharpen:
        out = sharpen(out)
    if do_enhance:
        out = enhance(out)
    return out
