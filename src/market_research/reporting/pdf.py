"""Selectable Unicode PDF with real URI annotations from the report document.

ReportLab is optional. JSON/HTML/Markdown continue to work if it is unavailable.
No browser, screenshot printing, or network access is used by this renderer.
"""
from html import escape
from pathlib import Path
import re
import sys
import unicodedata

from ..common import ROOT, safe_url
from .document import metric_caption
_glyphs = None


def runtime():
    try:
        import reportlab
    except ImportError:
        # A scoped runtime installed for this workspace; do not modify global env.
        local = ROOT / ".artifact-runtime/pdf-deps"
        if local.is_dir() and str(local) not in sys.path:
            sys.path.append(str(local))
        import reportlab
    return reportlab


def fonts():
    global _glyphs
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    if "ResearchSans" in pdfmetrics.getRegisteredFontNames():
        _glyphs = pdfmetrics.getFont("ResearchSans").face.charToGlyph
        return
    choices = [(Path("C:/Windows/Fonts/arial.ttf"), Path("C:/Windows/Fonts/arialbd.ttf")),
               (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")),
               (Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"), Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"))]
    regular, bold = next(((a, b) for a, b in choices if a.is_file() and b.is_file()), (None, None))
    if regular is None:
        raise OSError("Thiếu font Unicode Arial/DejaVu Sans/Liberation Sans để xuất PDF tiếng Việt")
    pdfmetrics.registerFont(TTFont("ResearchSans", str(regular)))
    pdfmetrics.registerFont(TTFont("ResearchSansBold", str(bold)))
    pdfmetrics.registerFontFamily("ResearchSans", normal="ResearchSans", bold="ResearchSansBold", italic="ResearchSans", boldItalic="ResearchSansBold")
    _glyphs = pdfmetrics.getFont("ResearchSans").face.charToGlyph


def text(value):
    value = "Nguồn chưa cung cấp" if value is None else str(value)
    value = unicodedata.normalize("NFC", value).replace("\u2011", "-").replace("\u2013", "-").replace("\u2014", "-")
    return "".join(c if c in "\n\r\t" or _glyphs is None or ord(c) in _glyphs else "[U+" + format(ord(c), "04X") + "]" for c in value)


def markup(value):
    if isinstance(value, tuple) and len(value) == 2 and safe_url(value[1]):
        return '<link href="' + escape(value[1], quote=True) + '" color="#354bd6">' + escape(text(value[0])).replace("\n", "<br/>") + '</link>'
    # Method/source URLs inside a paragraph must be clickable too.
    parts, cursor = [], 0
    raw = text(value)
    for match in re.finditer(r"https?://[^\s<>]+", raw):
        url = match.group().rstrip(".,;)")
        parts.append(escape(raw[cursor:match.start()]))
        parts.append('<link href="' + escape(url, quote=True) + '" color="#354bd6">' + escape(url) + '</link>')
        cursor = match.start() + len(url)
    parts.append(escape(raw[cursor:]))
    return "".join(parts).replace("\n", "<br/>")


def export_pdf(path, document, title, subtitle):
    """Return a serializable capability/result; never silently drop PDF errors."""
    path = Path(path)
    temporary = path.with_suffix(".pdf.tmp")
    try:
        runtime()
        fonts()
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_LEFT
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, LongTable, TableStyle, KeepTogether, Image, PageBreak
        from reportlab.graphics.shapes import Drawing, Line, String, PolyLine

        blue, ink, muted = colors.HexColor("#263b6d"), colors.HexColor("#223149"), colors.HexColor("#65718a")
        base = ParagraphStyle("ResearchBody", fontName="ResearchSans", fontSize=9, leading=13, textColor=ink, spaceAfter=7, alignment=TA_LEFT)
        small = ParagraphStyle("ResearchSmall", parent=base, fontSize=8, leading=11, textColor=muted)
        note = ParagraphStyle("ResearchNote", parent=small, backColor=colors.HexColor("#f2f4fb"), borderPadding=7, spaceBefore=4, spaceAfter=10)
        warning = ParagraphStyle("ResearchWarning", parent=small, backColor=colors.HexColor("#fff5dd"), borderPadding=7, spaceBefore=4, spaceAfter=10)
        headings = {level: ParagraphStyle("ResearchH" + str(level), parent=base, fontName="ResearchSansBold", fontSize=size, leading=size+5,
            textColor=blue, keepWithNext=True, spaceBefore=before, spaceAfter=after) for level, size, before, after in ((1, 21, 0, 13), (2, 15, 18, 8), (3, 11, 13, 7), (4, 10, 9, 6))}
        body_table = ParagraphStyle("ResearchTable", parent=base, fontSize=8, leading=10.5, spaceAfter=0, splitLongWords=True)
        header_table = ParagraphStyle("ResearchHeader", parent=body_table, fontName="ResearchSansBold", textColor=blue)
        path.parent.mkdir(parents=True, exist_ok=True)
        pdf = SimpleDocTemplate(str(temporary), pagesize=landscape(A4), leftMargin=36, rightMargin=36, topMargin=43, bottomMargin=35,
            title=title, author="Market Research", subject="Báo cáo có nguồn; link bấm được, review gắn sản phẩm")
        story = [Paragraph(markup(subtitle), small)]

        def widths(headers):
            # Reader report columns have very different text density.
            if headers[:2] == ["Nội dung", "Phạm vi nghiên cứu"]:
                weights = [1, 4]
            elif headers[:2] == ["Niche", "Khách hàng dự kiến"]:
                weights = [1.5, 3, .7]
            elif headers[0] == "Niche / keyword":
                weights = [2.1, 1.4, .8, 2.5]
            elif headers[0] == "Bán gì / cho ai":
                weights = [2.2, 2.4, 1.8, 1.7]
            elif headers[:2] == ["Loại hàng", "Dự báo chỉ số cho tháng bán"]:
                weights = [1.5, 1.7, 1.0, 2.7]
            else:
                weights = None
            if weights:
                return [pdf.width * weight / sum(weights) for weight in weights]
            weights = []
            for header in headers:
                label = str(header).casefold()
                weight = 3.2 if "trích đoạn" in label or "comment nguyên văn" in label else 2.4 if any(k in label for k in ("sản phẩm", "mẫu /", "keyword", "trang tham", "đối tượng", "còn thiếu", "nguồn /", "truy vấn thực")) else 1.0
                weights.append(weight)
            return [pdf.width * weight / sum(weights) for weight in weights]

        for block in document.blocks:
            kind = block["type"]
            if kind == "heading":
                if block["level"] == 2 and re.match(r"^[2-6]\. ", block["text"]):
                    story.append(PageBreak())
                story.append(Paragraph(markup(block["text"]), headings.get(block["level"], headings[4])))
            elif kind == "paragraph":
                style = warning if block.get("kind") == "warning" else note if block.get("kind") == "note" else base
                story.append(Paragraph(markup(block["text"]), style))
            elif kind == "table":
                cells = [[Paragraph(markup(v), header_table) for v in block["headers"]]]
                cells += [[Paragraph(markup(v), body_table) for v in row] for row in block["rows"]]
                table = LongTable(cells, colWidths=widths(block["headers"]), repeatRows=1, splitByRow=1, splitInRow=0, hAlign="LEFT", spaceAfter=10)
                table.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.HexColor("#edf1fb")), ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#fafbfe")]),
                    ("VALIGN", (0,0), (-1,-1), "TOP"), ("LEFTPADDING", (0,0), (-1,-1), 7), ("RIGHTPADDING", (0,0), (-1,-1), 7), ("TOPPADDING", (0,0), (-1,-1), 5), ("BOTTOMPADDING", (0,0), (-1,-1), 5),
                    ("LINEBELOW", (0,0), (-1,0), .7, colors.HexColor("#cbd5ea")), ("LINEBELOW", (0,1), (-1,-1), .3, colors.HexColor("#e2e7f0"))]))
                story.append(table)
            elif kind == "product_card":
                product, picture = block["product"], block.get("image", {})
                details = [Paragraph(markup((product["name"], product["url"])), header_table)]
                details.append(Paragraph(markup(product.get("identity")), small))
                details.append(Paragraph("<b>" + markup(product.get("price")) + "</b> | " + markup(product.get("signals")), body_table))
                for key in ("description", "review", "history"):
                    if product.get(key):
                        details.append(Paragraph(markup(product[key]), body_table))
                if product.get("review_url"):
                    details.append(Paragraph(markup(("Mở phản hồi của mẫu này", product["review_url"])), small))
                image = None
                if picture.get("status") == "available":
                    try:
                        image = Image(picture["path"])
                        scale = min(86/image.imageWidth, 86/image.imageHeight)
                        image.drawWidth, image.drawHeight = image.imageWidth*scale, image.imageHeight*scale
                        image.hAlign = "CENTER"
                    except (OSError, ValueError, TypeError):
                        image = None
                if image is None:
                    image = Paragraph("Ảnh chưa có.<br/>Mở link sản phẩm để xem mẫu nguồn.", small)
                card = LongTable([[image, details]], colWidths=[103, pdf.width-103], hAlign="LEFT", spaceAfter=10)
                card.setStyle(TableStyle([("VALIGN", (0,0), (-1,-1), "TOP"), ("BOX", (0,0), (-1,-1), .5, colors.HexColor("#d9e1f0")),
                    ("BACKGROUND", (0,0), (0,0), colors.HexColor("#f6f8fc")), ("TOPPADDING", (0,0), (-1,-1), 9), ("BOTTOMPADDING", (0,0), (-1,-1), 9),
                    ("LEFTPADDING", (0,0), (-1,-1), 10), ("RIGHTPADDING", (0,0), (-1,-1), 10)]))
                story.append(KeepTogether([card]))
            elif kind == "historical_chart":
                drawing = Drawing(pdf.width, 117)
                left, bottom, width, height = 30, 24, min(610, pdf.width-80), 65
                palette = ["#354bd6", "#0b8f7a", "#c07c22", "#a15fb4", "#d15c72", "#526b83"]
                upper = block.get("y_max", 100)
                for value in (0, upper/2, upper):
                    y = bottom + value*height/upper
                    drawing.add(Line(left, y, left+width, y, strokeColor=colors.HexColor("#e2e7f0")))
                    drawing.add(String(left-7, y-3, f"{value:g}", fontName="ResearchSans", fontSize=7, textAnchor="end", fillColor=muted))
                for month in range(1, 13):
                    drawing.add(String(left+(month-1)*width/11, bottom-12, str(month), fontName="ResearchSans", fontSize=7, textAnchor="middle", fillColor=muted))
                for index, year in enumerate(block["years"]):
                    color = colors.HexColor(palette[index % len(palette)])
                    rows = {r["month"]: r for r in block["monthly"] if r["year"] == year}
                    segment = []
                    for month in range(1, 13):
                        row = rows.get(month, {})
                        value = row.get("value") if row.get("status") == "complete" else None
                        if value is None:
                            if len(segment) >= 4:
                                drawing.add(PolyLine(segment, strokeColor=color, strokeWidth=1.8))
                            segment = []
                        else:
                            segment.extend([left+(month-1)*width/11, bottom+max(0,value)*height/upper])
                    if len(segment) >= 4:
                        drawing.add(PolyLine(segment, strokeColor=color, strokeWidth=1.8))
                    legend_x = left + index*72
                    drawing.add(Line(legend_x, 107, legend_x+14, 107, strokeColor=color, strokeWidth=2))
                    drawing.add(String(legend_x+19, 104, str(year), fontName="ResearchSans", fontSize=8, fillColor=ink))
                caption = Paragraph(markup(block["title"]) + "<br/><font size=8>" + markup(metric_caption(block.get("metric_unit"))) + "; trục ngang: tháng. Tháng không thu hoặc thiếu để trống.</font>", small)
                story.append(KeepTogether([caption, drawing]))
            elif kind == "chart":
                rows = block["history"].get("forecast", [])
                upper = block.get("y_max", 100)
                drawing = Drawing(pdf.width, 145)
                left, bottom, width, height = 28, 30, min(610, pdf.width - 60), 100
                drawing.add(Line(left,bottom,left+width,bottom,strokeColor=colors.HexColor("#bdc7d9")))
                drawing.add(Line(left,bottom,left,bottom+height,strokeColor=colors.HexColor("#bdc7d9")))
                for month in range(1, 13):
                    drawing.add(String(left+(month-1)*width/11,bottom-15,str(month),fontName="ResearchSans",fontSize=8,textAnchor="middle",fillColor=muted))
                for key, color in (("prediction", colors.HexColor("#4754d8")), ("observed", colors.HexColor("#0d8d78"))):
                    segment = []
                    previous_month = None
                    for row in rows:
                        if previous_month is not None and row["month"] != previous_month + 1:
                            if len(segment) >= 4:
                                drawing.add(PolyLine(segment, strokeColor=color, strokeWidth=2))
                            segment = []
                        previous_month = row["month"]
                        value = row.get(key)
                        if key == "observed" and row.get("observation_status") != "complete":
                            value = None
                        if value is None:
                            if len(segment) >= 4:
                                drawing.add(PolyLine(segment, strokeColor=color, strokeWidth=2))
                            segment = []
                        else:
                            segment += [left+(row["month"]-1)*width/11, bottom+max(0,value)*height/upper]
                    if len(segment) >= 4:
                        drawing.add(PolyLine(segment,strokeColor=color,strokeWidth=2))
                drawing.add(String(left,bottom+height+8,text(metric_caption(block["history"].get("metric_unit"))),fontName="ResearchSans",fontSize=8,fillColor=muted))
                story.append(KeepTogether([drawing, Paragraph("Tím: dự báo tham khảo. Xanh: tháng quan sát đầy đủ; khoảng thiếu được để trống.",small)]))

        def page(canvas, doc):
            canvas.saveState()
            width, height = landscape(A4)
            canvas.setFillColor(muted)
            canvas.setFont("ResearchSans", 8)
            canvas.drawString(36, height-24, "MARKET RESEARCH  /  BÁO CÁO CÓ NGUỒN")
            canvas.setStrokeColor(colors.HexColor("#d9dfed"))
            canvas.line(36, 27, width-36, 27)
            canvas.drawString(36, 15, "Link màu xanh bấm được. Dữ liệu thiếu được ghi rõ; không suy ra doanh số.")
            canvas.drawRightString(width-36,15,"Trang " + str(doc.page))
            canvas.restoreState()
        pdf.build(story,onFirstPage=page,onLaterPages=page)
        temporary.replace(path)
        return {"status": "available", "file": path.name, "renderer": "reportlab", "hyperlinks": True, "selectable_text": True}
    except (ImportError, OSError) as error:
        return {"status": "unavailable", "reason": str(error), "install": "python -m pip install -e .[pdf]"}
    except Exception as error:
        return {"status": "failed", "reason": type(error).__name__ + ": " + str(error)[:600]}
    finally:
        temporary.unlink(missing_ok=True)
