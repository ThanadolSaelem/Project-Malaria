"""ทดสอบ pipeline กับรูปจริง แล้วเซฟผลแต่ละขั้นออกมาเทียบกัน"""
import os
import sys
import time

import cv2
import numpy as np

import vflat_scan as vs

src = sys.argv[1] if len(sys.argv) > 1 else "/data/in.jpg"
outdir = sys.argv[2] if len(sys.argv) > 2 else "/data/out"
os.makedirs(outdir, exist_ok=True)

img = cv2.imread(src, cv2.IMREAD_COLOR)
if img is None:
    print(f"!! อ่านรูปไม่ได้: {src}")
    sys.exit(1)
print(f"input           : {img.shape[1]}x{img.shape[0]}")

padded, rect = vs.pad_to_model_aspect(img)
print(f"padded          : {padded.shape[1]}x{padded.shape[0]}  content={rect}")

t = time.time()
inp = cv2.resize(padded, (vs.FF_W, vs.FF_H), interpolation=cv2.INTER_AREA)
raw = vs.freeform(vs._to_rgba_f32(inp)[None]).reshape(-1)
buf = vs.deobfuscate(raw)
print(f"freeform        : {time.time()-t:.2f}s")

g = buf[:1250].reshape(25, 25, 2)
print(f"  aspect(h/w)   : {buf[1250]:.4f}")
print(f"  grid x range  : {g[...,0].min():+.4f} .. {g[...,0].max():+.4f}")
print(f"  grid y range  : {g[...,1].min():+.4f} .. {g[...,1].max():+.4f}")
print(f"  แถวแรก x      : {np.round(g[0,:5,0],4)} ...")
print(f"  คอลัมน์แรก y  : {np.round(g[:5,0,1],4)} ...")
# ตรวจว่า grid เรียงตัวสมเหตุสมผล (x ควรเพิ่มตามคอลัมน์, y ควรเพิ่ม/ลดตามแถว)
dx = np.diff(g[..., 0], axis=1)
dy = np.diff(g[..., 1], axis=0)
print(f"  monotonic x   : {100*np.mean(dx>0):.1f}% เพิ่มขึ้น")
print(f"  monotonic y   : {100*np.mean(dy>0):.1f}% เพิ่มขึ้น")

w, h = vs.calc_output_size(padded.shape[1], buf)
print(f"output size     : {w}x{h}")

t = time.time(); dw = vs.dewarp(img);        print(f"dewarp          : {time.time()-t:.2f}s -> {dw.shape[1]}x{dw.shape[0]}")
t = time.time(); sh = vs.sharpen(dw);        print(f"sharpen         : {time.time()-t:.2f}s")
t = time.time(); en = vs.enhance(sh);        print(f"enhance         : {time.time()-t:.2f}s")

for name, im in [("1_padded", padded), ("2_dewarp", dw), ("3_sharpen", sh), ("4_final", en)]:
    p = os.path.join(outdir, name + ".jpg")
    cv2.imwrite(p, im, [cv2.IMWRITE_JPEG_QUALITY, 95])
    print(f"เซฟ {p}")
