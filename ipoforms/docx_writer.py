"""Write a render model (see prefill.build_form) as an editable Word .docx.

Uses only the standard library: a .docx is a zip of WordprocessingML parts.
Blank fields are left as empty table cells so they can be typed into in Word.
"""

from __future__ import annotations

import io
import re
import zipfile
from datetime import datetime, timezone
from xml.sax.saxutils import escape

FONT = "Times New Roman"
SYMBOL_FONT = "Segoe UI Symbol"
PAGE_W, PAGE_H, MARGIN = 11906, 16838, 1134       # A4, 2 cm margins (twips)
TEXT_W = PAGE_W - 2 * MARGIN
LABEL_W = 3500
BORDER = "A6A6A6"
LABEL_FILL = "F2F2F2"
CHECKED, UNCHECKED = "☒", "☐"
_XML_BAD = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")

W_NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')


# --------------------------------------------------------------------------
# XML primitives
# --------------------------------------------------------------------------

def _run(text: str, *, bold=False, italic=False, strike=False, underline=False,
         size: int | None = None, font: str | None = None) -> str:
    props = []
    if font:
        props.append(f'<w:rFonts w:ascii="{font}" w:hAnsi="{font}" w:cs="{font}"/>')
    if bold:
        props.append("<w:b/>")
    if italic:
        props.append("<w:i/>")
    if strike:
        props.append("<w:strike/>")
    if underline:
        props.append('<w:u w:val="single"/>')
    if size:
        props.append(f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>')
    rpr = f"<w:rPr>{''.join(props)}</w:rPr>" if props else ""
    pieces = []
    # Characters XML forbids (stray control codes from pasted text) would make
    # the document unopenable, so they become spaces.
    text = _XML_BAD.sub(" ", str(text).replace("\r\n", "\n").replace("\r", "\n"))
    for i, line in enumerate(text.split("\n")):
        if i:
            pieces.append("<w:br/>")
        pieces.append(f'<w:t xml:space="preserve">{escape(line)}</w:t>')
    return f"<w:r>{rpr}{''.join(pieces)}</w:r>"


def _para(runs: str = "", *, align: str | None = None, before=0, after=80,
          keep_next=False) -> str:
    ppr = []
    if keep_next:
        ppr.append("<w:keepNext/>")
    ppr.append(f'<w:spacing w:before="{before}" w:after="{after}"/>')
    if align:
        ppr.append(f'<w:jc w:val="{align}"/>')
    return f"<w:p><w:pPr>{''.join(ppr)}</w:pPr>{runs}</w:p>"


def _cell(content: str, width: int, fill: str | None = None, span: int = 1) -> str:
    tcpr = f'<w:tcW w:w="{width}" w:type="dxa"/>'
    if span > 1:
        tcpr += f'<w:gridSpan w:val="{span}"/>'
    if fill:
        tcpr += f'<w:shd w:val="clear" w:color="auto" w:fill="{fill}"/>'
    return f"<w:tc><w:tcPr>{tcpr}</w:tcPr>{content or _para()}</w:tc>"


def _table(rows: list[str], widths: list[int]) -> str:
    borders = "".join(
        f'<w:{side} w:val="single" w:sz="4" w:space="0" w:color="{BORDER}"/>'
        for side in ("top", "left", "bottom", "right", "insideH", "insideV"))
    grid = "".join(f'<w:gridCol w:w="{w}"/>' for w in widths)
    return (f'<w:tbl><w:tblPr><w:tblW w:w="{sum(widths)}" w:type="dxa"/>'
            f'<w:tblLayout w:type="fixed"/><w:tblBorders>{borders}</w:tblBorders>'
            f'<w:tblCellMar><w:top w:w="40" w:type="dxa"/><w:left w:w="100" w:type="dxa"/>'
            f'<w:bottom w:w="40" w:type="dxa"/><w:right w:w="100" w:type="dxa"/></w:tblCellMar>'
            f'</w:tblPr><w:tblGrid>{grid}</w:tblGrid>{"".join(rows)}</w:tbl>'
            + _para(after=60))


def _tr(cells: str, min_height: int | None = None) -> str:
    height = f'<w:trHeight w:val="{min_height}"/>' if min_height else ""
    return f"<w:tr><w:trPr><w:cantSplit/>{height}</w:trPr>{cells}</w:tr>"


# --------------------------------------------------------------------------
# Blocks
# --------------------------------------------------------------------------

def _choice_runs(row: dict) -> str:
    opts = row.get("options") or []
    kind = row["kind"]
    any_sel = any(o["selected"] for o in opts)
    if kind == "strikeoutChoice":
        parts = []
        for i, o in enumerate(opts):
            if i:
                parts.append(_run(" / "))
            parts.append(_run(o["label"], strike=any_sel and not o["selected"],
                              bold=o["selected"]))
        return _para("".join(parts), after=0)
    if kind == "dropdown" and any_sel:
        return _para(_run(row["value"]), after=0)
    paras = []
    for o in opts:
        mark = CHECKED if o["selected"] else UNCHECKED
        paras.append(_para(_run(mark + " ", font=SYMBOL_FONT) + _run(o["label"]), after=20))
    return "".join(paras)


def _field_row(row: dict) -> str:
    label = _cell(_para(_run(row["label"], size=20), after=0), LABEL_W, LABEL_FILL)
    if row.get("options") is not None:
        value = _choice_runs(row)
    elif row["value"]:
        value = _para(_run(row["value"]), after=0)
    else:
        value = _para(after=0)
    height = None
    if not row["value"] and row.get("options") is None:
        if row["kind"] == "signature":
            height = 700
        elif row.get("multiline"):
            height = 900
    return _tr(label + _cell(value, TEXT_W - LABEL_W), height)


def _block(block: dict) -> str:
    t = block["type"]
    if t == "text":
        return _para(_run(block["text"]), align="both", after=100)
    if t == "subheading":
        return _para(_run(block["text"], bold=True, underline=True, size=21),
                     before=120, after=60, keep_next=True)
    if t == "fields":
        return _table([_field_row(r) for r in block["rows"]], [LABEL_W, TEXT_W - LABEL_W])
    if t == "table":
        cols = block["columns"] or [""]
        w = TEXT_W // len(cols)
        widths = [w] * len(cols)
        head = _tr("".join(_cell(_para(_run(c, bold=True, size=19), after=0), w, LABEL_FILL)
                           for c in cols))
        body = [_tr("".join(_cell(_para(_run(v), after=0), w) for v in r), 450)
                for r in block["rows"]]
        return (_para(_run(block["label"], italic=True), after=60, keep_next=True)
                + _table([head] + body, widths))
    return ""


def _document_xml(model: dict) -> str:
    f = model["form"]
    out = [
        _para(_run(f["act"], bold=True, size=24), align="center", after=0),
        _para(_run("&", bold=True, size=24), align="center", after=0),
        _para(_run(f["rules"], bold=True, size=24), align="center", after=160),
        _para(_run(f"FORM {f['number']}", bold=True, size=28), align="center", after=60),
        _para(_run(f["name"].upper(), bold=True, size=24), align="center", after=60),
    ]
    if f.get("see"):
        out.append(_para(_run(f"[See {f['see']}]", italic=True, size=21), align="center", after=240))
    for sec in model["sections"]:
        if not sec["blocks"] and not sec["title"]:
            continue
        if sec["title"]:
            out.append(_para(_run(sec["title"], bold=True, size=22),
                             before=200, after=80, keep_next=True))
        for b in sec["blocks"]:
            out.append(_block(b))
    sect = (f'<w:sectPr><w:footerReference w:type="default" r:id="rId2"/>'
            f'<w:pgSz w:w="{PAGE_W}" w:h="{PAGE_H}"/>'
            f'<w:pgMar w:top="{MARGIN}" w:right="{MARGIN}" w:bottom="{MARGIN}" '
            f'w:left="{MARGIN}" w:header="567" w:footer="567" w:gutter="0"/></w:sectPr>')
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<w:document {W_NS}><w:body>{"".join(out)}{sect}</w:body></w:document>')


def _field_run(instr: str) -> str:
    return (f'<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            f'<w:r><w:instrText xml:space="preserve"> {instr} </w:instrText></w:r>'
            f'<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            f'<w:r><w:t>1</w:t></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r>')


def _footer_xml(form_number: str) -> str:
    runs = (_run(f"Form {form_number}  |  Page ", size=18) + _field_run("PAGE")
            + _run(" of ", size=18) + _field_run("NUMPAGES"))
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<w:ftr {W_NS}>{_para(runs, align="center", after=0)}</w:ftr>')


STYLES = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:docDefaults><w:rPrDefault><w:rPr>
<w:rFonts w:ascii="{FONT}" w:eastAsia="{FONT}" w:hAnsi="{FONT}" w:cs="{FONT}"/>
<w:sz w:val="22"/><w:szCs w:val="22"/><w:lang w:val="en-IN"/></w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr><w:spacing w:after="80" w:line="252" w:lineRule="auto"/></w:pPr></w:pPrDefault>
</w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>
<w:style w:type="table" w:default="1" w:styleId="TableNormal"><w:name w:val="Normal Table"/>
<w:tblPr><w:tblInd w:w="0" w:type="dxa"/><w:tblCellMar><w:top w:w="0" w:type="dxa"/>
<w:left w:w="108" w:type="dxa"/><w:bottom w:w="0" w:type="dxa"/><w:right w:w="108" w:type="dxa"/>
</w:tblCellMar></w:tblPr></w:style>
</w:styles>"""

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
</Types>"""

ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
</Relationships>"""

DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>
</Relationships>"""


def _core_xml(title: str) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            f'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
            f'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f'<dc:title>{escape(title)}</dc:title><dc:creator>IPO Form Filler</dc:creator>'
            f'<dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>'
            f'<dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified>'
            f'</cp:coreProperties>')


def build_docx(model: dict) -> bytes:
    f = model["form"]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", ROOT_RELS)
        z.writestr("word/_rels/document.xml.rels", DOC_RELS)
        z.writestr("word/document.xml", _document_xml(model))
        z.writestr("word/styles.xml", STYLES)
        z.writestr("word/footer1.xml", _footer_xml(f["number"]))
        z.writestr("docProps/core.xml", _core_xml(f"Form {f['number']} - {f['name']}"))
    return buf.getvalue()
