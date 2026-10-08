"""vFlat Scan API — สแกนภาพเอกสารให้เป็นภาพสวย (dewarp + sharpen + enhance)

POST /scan   multipart file=@photo.jpg  ->  image/jpeg
             multipart file=@doc.pdf    ->  application/pdf (ทุกหน้า)
             multipart file=@doc.pdf&page=2  ->  image/jpeg (หน้าเดียว)
GET  /healthz
"""
from __future__ import annotations

import time
from typing import Optional

import cv2
import numpy as np
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse, Response

import pdf_utils
import vflat_scan as vs

app = FastAPI(title="vFlat Scan API", version="1.1")

MAX_UPLOAD_MB = 40
MAX_SIDE = 4000            # กันภาพยักษ์ทำ RAM บวม
MAX_PDF_PAGES = 50         # กัน PDF มหึมาทำ request ค้างนาน
DEFAULT_PDF_DPI = 200      # ความละเอียดตอนแปลง PDF -> ภาพ (200 dpi ~ คุณภาพสแกนทั่วไป)


@app.on_event("startup")
def _warmup() -> None:
    """รันภาพจิ๋วครั้งเดียวตอนบูต เพื่อให้ request แรกไม่ช้า"""
    dummy = np.full((192, 144, 3), 240, dtype=np.uint8)
    try:
        vs.scan(dummy)
    except Exception:
        pass


@app.get("/healthz")
def healthz() -> JSONResponse:
    return JSONResponse({"status": "ok"})


def _clip_side(img: np.ndarray) -> np.ndarray:
    h, w = img.shape[:2]
    if max(h, w) > MAX_SIDE:
        s = MAX_SIDE / max(h, w)
        img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    return img


def _run_scan(img: np.ndarray, dewarp: bool, sharpen: bool, enhance: bool, trim: bool) -> np.ndarray:
    try:
        return vs.scan(img, do_dewarp=dewarp, do_sharpen=sharpen, do_enhance=enhance, trim=trim)
    except ValueError as e:
        raise HTTPException(422, str(e))


def _encode_jpeg(img: np.ndarray, quality: int) -> bytes:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise HTTPException(500, "encode JPEG ไม่สำเร็จ")
    return buf.tobytes()


@app.post("/scan")
async def scan(
    file: UploadFile = File(...),
    dewarp: bool = Query(True, description="ดัดหน้ากระดาษให้แบน"),
    sharpen: bool = Query(True, description="unsharp mask"),
    enhance: bool = Query(True, description="ลบเงา ทำพื้นหลังขาว"),
    trim: bool = Query(True, description="ตัดขอบที่เกิดจากการ pad"),
    quality: int = Query(95, ge=1, le=100),
    dpi: int = Query(DEFAULT_PDF_DPI, ge=72, le=400, description="ความละเอียดแปลง PDF เป็นภาพ (เฉพาะไฟล์ PDF)"),
    page: Optional[int] = Query(
        None, ge=1, description="เลือกหน้าเดียวจาก PDF (1-indexed) คืนเป็น JPEG; ไม่ระบุ = ทุกหน้า คืนเป็น PDF"
    ),
    pagesize: str = Query(
        "auto",
        pattern="^(auto|a4|letter)$",
        description="ขนาดหน้าของ PDF ที่ได้: auto = ตามขนาดจริงที่ dpi ที่เรนเดอร์, a4, letter",
    ),
) -> Response:
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "ไฟล์ว่าง")
    if len(raw) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"ไฟล์ใหญ่เกิน {MAX_UPLOAD_MB} MB")

    t0 = time.time()

    # ---------------- PDF ----------------
    if pdf_utils.is_pdf(raw):
        try:
            n_pages = pdf_utils.page_count(raw)
        except Exception:
            raise HTTPException(400, "อ่านไฟล์ PDF ไม่ได้ (ไฟล์เสียหรือมีรหัสผ่าน)")

        if page is not None:
            if page > n_pages:
                raise HTTPException(422, f"PDF มีแค่ {n_pages} หน้า (ขอหน้า {page})")
            img = _clip_side(pdf_utils.render_page(raw, page - 1, dpi))
            out = _run_scan(img, dewarp, sharpen, enhance, trim)
            return Response(
                content=_encode_jpeg(out, quality),
                media_type="image/jpeg",
                headers={
                    "X-Elapsed-Seconds": f"{time.time() - t0:.3f}",
                    "X-Page-Count": str(n_pages),
                    "X-Page": str(page),
                    "X-Output-Size": f"{out.shape[1]}x{out.shape[0]}",
                    "Content-Disposition": 'inline; filename="scanned.jpg"',
                },
            )

        if n_pages > MAX_PDF_PAGES:
            raise HTTPException(413, f"PDF มี {n_pages} หน้า เกินจำกัด {MAX_PDF_PAGES} หน้าต่อคำขอ")

        outs = [
            _run_scan(_clip_side(img), dewarp, sharpen, enhance, trim)
            for img in pdf_utils.render_all_pages(raw, dpi)
        ]
        pdf_bytes = pdf_utils.images_to_pdf(outs, quality, pagesize, dpi)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "X-Elapsed-Seconds": f"{time.time() - t0:.3f}",
                "X-Page-Count": str(n_pages),
                "X-Page-Size": pagesize,
                "Content-Disposition": 'attachment; filename="scanned.pdf"',
            },
        )

    # ---------------- ภาพทั่วไป ----------------
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(400, "อ่านไฟล์ไม่ได้ (รองรับ jpg/png/webp/bmp/pdf)")

    h, w = img.shape[:2]
    img = _clip_side(img)
    out = _run_scan(img, dewarp, sharpen, enhance, trim)
    return Response(
        content=_encode_jpeg(out, quality),
        media_type="image/jpeg",
        headers={
            "X-Elapsed-Seconds": f"{time.time() - t0:.3f}",
            "X-Input-Size": f"{w}x{h}",
            "X-Output-Size": f"{out.shape[1]}x{out.shape[0]}",
            "Content-Disposition": 'inline; filename="scanned.jpg"',
        },
    )
