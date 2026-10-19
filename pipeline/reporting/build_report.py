# -*- coding: utf-8 -*-
"""build_report.py: NCSA TLP:AMBER report builder (house style of the approved edition (Sarabun, justified body, continuous figure numbers)).

Keeps everything from TEMPLATE (headers, footers, TLP badges, embedded Sarabun font, styles)
and replaces only the body. TEMPLATE = the latest approved report .docx (preferred) or template.docx.
"""
import os, re, shutil, zipfile

CONTENT_W = 9071            # twips: A4 21.0 cm minus left 3.00 cm and right 2.00 cm = 16.0 cm
IMG_W = 5760000             # EMU: 16.0 cm (full content width)
IMG_MAX_H = 4320000         # EMU: 12.0 cm, keeps two framed figures per page
PGMAR = ('<w:pgMar w:top="1123" w:right="1134" w:bottom="648" w:left="1701" '
         'w:header="680" w:footer="680" w:gutter="0"/>')
RF = ('<w:rFonts w:ascii="Sarabun" w:eastAsia="Sarabun" '
      'w:hAnsi="Sarabun" w:cs="Sarabun"/>')
MONO = ('<w:rFonts w:ascii="Courier New" w:eastAsia="Courier New" '
        'w:hAnsi="Courier New" w:cs="Sarabun"/>')
IMG_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"


def _esc(t):
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _run(text="", b=False, sz=32, color="000000", tab=False, font=RF):
    bb = "<w:b/><w:bCs/>" if b else ""
    t = f'<w:t xml:space="preserve">{_esc(text)}</w:t>' if text != "" else ""
    return (f'<w:r><w:rPr>{font}{bb}<w:color w:val="{color}"/><w:sz w:val="{sz}"/>'
            f'<w:szCs w:val="{sz}"/></w:rPr>{"<w:tab/>" if tab else ""}{t}</w:r>')


def _p(runs, jc="both", before=0, after=0, ind="", keep=False, pbb=False, sz=32, font=RF, line=240):
    j = f'<w:jc w:val="{jc}"/>' if jc else ""
    k = "<w:keepNext/>" if keep else ""
    pb = "<w:pageBreakBefore/>" if pbb else ""
    return (f'<w:p><w:pPr>{k}{pb}<w:spacing w:before="{before}" w:after="{after}" '
            f'w:line="{line}" w:lineRule="auto"/>{ind}{j}<w:rPr>{font}<w:sz w:val="{sz}"/>'
            f'<w:szCs w:val="{sz}"/></w:rPr></w:pPr>{runs}</w:p>')


class Report:
    def __init__(self, template, fig_numbering="continuous"):
        """fig_numbering: 'continuous' (approved: 1..N across the whole report) or 'per_section'."""
        self.template = os.path.abspath(template)
        with zipfile.ZipFile(self.template) as z:
            self._names = z.namelist()
            doc = z.read("word/document.xml").decode("utf-8")
            self._rels = z.read("word/_rels/document.xml.rels").decode("utf-8")
            keep = set()
            for n in self._names:  # media still used by headers/footers
                if re.match(r"word/_rels/(header|footer)\d*\.xml\.rels$", n):
                    keep |= {"word/" + m for m in re.findall(r'Target="(media/[^"]+)"', z.read(n).decode())}
        self._head = doc[:doc.index("<w:body>") + len("<w:body>")]
        sect = re.findall(r"<w:sectPr[ >].*?</w:sectPr>", doc, re.S)[-1]
        self._sectpr = re.sub(r"<w:pgMar [^>]*/>", PGMAR, sect)
        # drop the template's body images (relationships + media) so they do not bloat the output
        self._drop = set()
        for m in re.finditer(r'<Relationship [^>]*Type="' + re.escape(IMG_REL) + r'"[^>]*/>', self._rels):
            tgt = re.search(r'Target="([^"]+)"', m.group(0)).group(1)
            if "word/" + tgt not in keep:
                self._drop.add("word/" + tgt)
        self._rels = re.sub(r'<Relationship [^>]*Type="' + re.escape(IMG_REL) + r'"[^>]*/>', "", self._rels)
        self.blocks, self._images = [], []
        self._rid, self._did = 900, 900
        self.fig_numbering, self._fig = fig_numbering, 0

    # ---------------- text ----------------
    def title(self, text):
        self.blocks.append(_p(_run(text, b=True), jc=""))

    def date(self, text):
        self.blocks.append(_p(_run(text), jc="", after=220))

    def heading(self, text, new_page=False):
        if self.fig_numbering == "per_section":
            self._fig = 0
        self.blocks.append(_p(_run(text, b=True), jc="both", before=180, after=60, keep=True, pbb=new_page))

    def sub(self, text, new_page=False):
        if self.fig_numbering == "per_section":
            self._fig = 0
        self.blocks.append(_p(_run(text, b=True), jc="both", before=100, after=40, keep=True, pbb=new_page))

    def plain(self, text, tab=True):
        self.blocks.append(_p(_run(text, tab=tab)))

    def lead(self, label, text):
        self.blocks.append(_p(_run(label.rstrip() + " ", b=True, tab=True) + _run(text)))

    def bullet(self, text):
        self.blocks.append(_p(_run("•  " + text, tab=True)))

    def dash(self, text):
        self.blocks.append(_p(_run("- " + text, tab=True)))

    def numbered(self, n, text):
        self.blocks.append(_p(_run(f"{n}) {text}", tab=True)))

    def status(self, value):
        self.blocks.append(_p(_run("สถานะ: ", b=True) + _run(value), jc="both", before=20, after=60))

    def note(self, text):
        self.blocks.append(_p(_run("หมายเหตุ: ", b=True), jc="", before=120, keep=True))
        self.blocks.append(_p(_run(text), ind='<w:ind w:firstLine="720"/>'))

    def signature(self, date_text, unit="ฝ่ายปฏิบัติการทางไซเบอร์ สำนักปฏิบัติการ"):
        self.blocks.append(_p("", jc=""))
        self.blocks.append(_p(_run(unit), jc="both"))
        self.blocks.append(_p(_run(date_text), jc="both"))

    def spacer(self):
        self.blocks.append(_p("", jc=""))

    def page_break(self):
        self.blocks.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')

    def code_block(self, lines, sz=18):
        """monospace box (e.g. source tree); Thai falls back to Sarabun."""
        paras = "".join(_p(_run(ln if ln.strip() else " ", sz=sz, color="333333", font=MONO),
                           jc="left", ind='<w:ind w:left="120"/>', sz=sz, font=MONO) for ln in lines)
        self.blocks.append(self._frame(paras, border="BFBFBF", bsz=4, fill="F7F7F7", height=None) + _p("", jc=""))

    # ---------------- figures ----------------
    def _frame(self, inner, border="808080", bsz=8, fill=None, height=3000):
        bd = "".join((f'<w:{s} w:val="single" w:sz="{bsz}" w:space="0" w:color="{border}"/>' if border
                      else f'<w:{s} w:val="nil"/>') for s in ("top", "left", "bottom", "right"))
        shd = f'<w:shd w:val="clear" w:color="auto" w:fill="{fill}"/>' if fill else ""
        h = f'<w:trHeight w:val="{height}" w:hRule="atLeast"/>' if height else ""
        return (f'<w:tbl><w:tblPr><w:tblW w:w="{CONTENT_W}" w:type="dxa"/><w:jc w:val="center"/>'
                f'<w:tblLayout w:type="fixed"/><w:tblCellMar><w:top w:w="60" w:type="dxa"/>'
                f'<w:left w:w="60" w:type="dxa"/><w:bottom w:w="60" w:type="dxa"/><w:right w:w="60" w:type="dxa"/>'
                f'</w:tblCellMar><w:tblLook w:val="04A0"/></w:tblPr><w:tblGrid><w:gridCol w:w="{CONTENT_W}"/>'
                f'</w:tblGrid><w:tr><w:trPr><w:cantSplit/>{h}<w:jc w:val="center"/></w:trPr><w:tc><w:tcPr>'
                f'<w:tcW w:w="{CONTENT_W}" w:type="dxa"/><w:tcBorders>{bd}</w:tcBorders>{shd}'
                f'<w:vAlign w:val="center"/></w:tcPr>{inner}</w:tc></w:tr></w:tbl>')

    def _caption(self, text):
        self._fig += 1
        self.blocks.append(_p(_run(f"รูปภาพที่ {self._fig}", b=True) + _run(" " + text),
                              jc="center", before=40, after=120))
        return self._fig

    def figure(self, image_path, caption, width_cm=None, border=True):
        """inline image 16 cm wide (or width_cm) in a framed cell, caption below. Returns figure number."""
        from PIL import Image
        n = len(self._images) + 1
        rid, did = f"rId{self._rid}", self._did
        self._rid += 1; self._did += 1
        ext = os.path.splitext(image_path)[1].lower() or ".png"
        arc = f"rpt_fig{n}{ext}"
        self._images.append((arc, os.path.abspath(image_path), rid))
        w, h = Image.open(image_path).size
        cx = int(width_cm * 360000) if width_cm else IMG_W
        cy = int(cx * h / w)
        if cy > IMG_MAX_H:
            cx, cy = int(cx * IMG_MAX_H / cy), IMG_MAX_H
        A = "http://schemas.openxmlformats.org/drawingml/2006/main"
        drawing = (f'<w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{cx}" cy="{cy}"/>'
                   f'<wp:effectExtent l="0" t="0" r="0" b="0"/><wp:docPr id="{did}" name="figure{n}"/>'
                   f'<wp:cNvGraphicFramePr><a:graphicFrameLocks xmlns:a="{A}" noChangeAspect="1"/></wp:cNvGraphicFramePr>'
                   f'<a:graphic xmlns:a="{A}"><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
                   f'<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:nvPicPr>'
                   f'<pic:cNvPr id="{did}" name="figure{n}"/><pic:cNvPicPr/></pic:nvPicPr><pic:blipFill>'
                   f'<a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill><pic:spPr>'
                   f'<a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm><a:prstGeom prst="rect">'
                   f'<a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing>')
        cell = _p(f'<w:r><w:rPr><w:noProof/></w:rPr>{drawing}</w:r>', jc="center", keep=True)
        self.blocks.append(self._frame(cell, border="808080" if border else None, height=None))
        return self._caption(caption)

    def placeholder(self, caption, note="[ พื้นที่สำหรับแนบภาพหน้าจอ ]", height=3000):
        cell = _p(_run(note, color="808080"), jc="center", keep=True)
        self.blocks.append(self._frame(cell, height=height))
        return self._caption(caption)

    # ---------------- tables ----------------
    def table(self, rows, widths, header=True):
        """data table: 16 cm, BFBFBF 0.5 pt borders, grey bold header row repeated on each page."""
        assert abs(sum(widths) - CONTENT_W) <= 5, f"widths must sum to {CONTENT_W}, got {sum(widths)}"
        bd = "".join(f'<w:{s} w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>'
                     for s in ("top", "left", "bottom", "right", "insideH", "insideV"))
        out = [f'<w:tbl><w:tblPr><w:tblW w:w="{CONTENT_W}" w:type="dxa"/><w:jc w:val="center"/>'
               f'<w:tblBorders>{bd}</w:tblBorders><w:tblLayout w:type="fixed"/><w:tblCellMar>'
               f'<w:top w:w="100" w:type="dxa"/><w:left w:w="100" w:type="dxa"/><w:bottom w:w="100" w:type="dxa"/>'
               f'<w:right w:w="100" w:type="dxa"/></w:tblCellMar><w:tblLook w:val="04A0"/></w:tblPr><w:tblGrid>'
               + "".join(f'<w:gridCol w:w="{w}"/>' for w in widths) + "</w:tblGrid>"]
        for i, row in enumerate(rows):
            hd = header and i == 0
            trpr = "<w:cantSplit/>" + ("<w:tblHeader/>" if hd else "")
            cells = ""
            for j, c in enumerate(row):
                shd = '<w:shd w:val="clear" w:color="auto" w:fill="E7E6E6"/>' if hd else ""
                cells += (f'<w:tc><w:tcPr><w:tcW w:w="{widths[j]}" w:type="dxa"/>{shd}<w:vAlign w:val="center"/>'
                          f'</w:tcPr>{_p(_run(c, b=hd), jc="center" if hd else "left", line=360)}</w:tc>')
            out.append(f'<w:tr><w:trPr>{trpr}<w:jc w:val="center"/></w:trPr>{cells}</w:tr>')
        out.append("</w:tbl>")
        self.blocks.append("".join(out) + _p("", jc=""))

    # ---------------- save ----------------
    def save(self, out_path):
        doc = self._head + "".join(self.blocks) + self._sectpr + "</w:body></w:document>"
        rels = self._rels.replace("</Relationships>", "".join(
            f'<Relationship Id="{rid}" Type="{IMG_REL}" Target="media/{arc}"/>'
            for arc, _, rid in self._images) + "</Relationships>")
        ct_add = {os.path.splitext(a)[1][1:] for a, _, _ in self._images}
        tmp = out_path + ".tmpdir"
        shutil.rmtree(tmp, ignore_errors=True)
        with zipfile.ZipFile(self.template) as z:
            z.extractall(tmp)
        for n in self._drop:
            p = os.path.join(tmp, n)
            if os.path.exists(p):
                os.remove(p)
        open(os.path.join(tmp, "word/document.xml"), "w", encoding="utf-8").write(doc)
        open(os.path.join(tmp, "word/_rels/document.xml.rels"), "w", encoding="utf-8").write(rels)
        os.makedirs(os.path.join(tmp, "word/media"), exist_ok=True)
        for arc, path, _ in self._images:
            shutil.copy(path, os.path.join(tmp, "word/media", arc))
        ctp = os.path.join(tmp, "[Content_Types].xml")
        ct = open(ctp, encoding="utf-8").read()
        for e in ct_add:
            if f'Extension="{e}"' not in ct:
                mime = "image/jpeg" if e in ("jpg", "jpeg") else f"image/{e}"
                ct = ct.replace("</Types>", f'<Default Extension="{e}" ContentType="{mime}"/></Types>')
        open(ctp, "w", encoding="utf-8").write(ct)
        if os.path.exists(out_path):
            os.remove(out_path)
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
            for root, _, files in os.walk(tmp):
                for fn in files:
                    fp = os.path.join(root, fn)
                    z.write(fp, os.path.relpath(fp, tmp))
        shutil.rmtree(tmp)
        return out_path
