"""แปลง PDF <-> ภาพ สำหรับ endpoint /scan

ใช้ PyMuPDF (fitz) แปลง PDF -> raster ต่อหน้า และ img2pdf ประกอบภาพที่สแกนแล้ว
กลับเป็น PDF (ฝัง JPEG stream ตรง ๆ ไม่ decode ซ้ำ จึงเร็วและไม่เสียคุณภาพ)
"""
from __future__ import annotations

import cv2
import fitz  # PyMuPDF
import img2pdf
import numpy as np

PDF_MAGIC = b"%PDF-"


def is_pdf(raw: bytes) -> bool:
    return raw[:5] == PDF_MAGIC


def page_count(raw: bytes) -> int:
    doc = fitz.open(stream=raw, filetype="pdf")
    try:
        return len(doc)
    finally:
        doc.close()


def _pixmap_to_bgr(pix: "fitz.Pixmap") -> np.ndarray:
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    if pix.n == 4:
        return cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def render_page(raw: bytes, index: int, dpi: int) -> np.ndarray:
    """เรนเดอร์เฉพาะหน้าที่ต้องการ (index เริ่มที่ 0) — ไม่แตะหน้าอื่น จึงเร็วแม้ไฟล์ใหญ่"""
    doc = fitz.open(stream=raw, filetype="pdf")
    try:
        page = doc[index]
        mat = fitz.Matrix(dpi / 72.0, dpi / 72.0)
        pix = page.get_pixmap(matrix=mat, alpha=False, colorspace=fitz.csRGB)
        return _pixmap_to_bgr(pix)
    finally:
        doc.close()


def render_all_pages(raw: bytes, dpi: int) -> list[np.ndarray]:
    doc = fitz.open(stream=raw, filetype="pdf")
    try:
        mat = fitz.Matrix(dpi / 72.0, dpi / 72.0)
        return [
            _pixmap_to_bgr(page.get_pixmap(matrix=mat, alpha=False, colorspace=fitz.csRGB))
            for page in doc
        ]
    finally:
        doc.close()


A4_PT = (img2pdf.mm_to_pt(210), img2pdf.mm_to_pt(297))
LETTER_PT = (img2pdf.in_to_pt(8.5), img2pdf.in_to_pt(11))


def _layout_fun(pagesize: str, dpi: int):
    """กำหนดขนาดหน้ากระดาษของ PDF ที่ได้

    cv2.imencode ไม่ฝัง DPI ลง JPEG ทำให้ img2pdf เดาเป็น 96 dpi
    -> หน้ากระดาษใหญ่เวอร์ (ภาพ 1735 px กลายเป็นหน้า 24 นิ้ว)
    จึงต้องบอก dpi ให้ชัดเจน
    """
    if pagesize == "a4":
        return img2pdf.get_layout_fun(A4_PT)
    if pagesize == "letter":
        return img2pdf.get_layout_fun(LETTER_PT)
    # auto: ใช้ dpi ที่เรนเดอร์มา -> ขนาดจริงใกล้เคียงต้นฉบับ
    return img2pdf.get_fixed_dpi_layout_fun((dpi, dpi))


def images_to_pdf(
    images: list[np.ndarray],
    quality: int = 92,
    pagesize: str = "auto",
    dpi: int = 200,
) -> bytes:
    """ประกอบภาพ (BGR, uint8) หลายภาพกลับเป็น PDF หนึ่งไฟล์"""
    jpegs = []
    for im in images:
        ok, buf = cv2.imencode(".jpg", im, [cv2.IMWRITE_JPEG_QUALITY, quality])
        if not ok:
            raise RuntimeError("encode JPEG ไม่สำเร็จ")
        jpegs.append(buf.tobytes())
    return img2pdf.convert(jpegs, layout_fun=_layout_fun(pagesize, dpi))
