"""A single block document rendered to escaped HTML and Markdown."""
from html import escape
import re
import math

from ..common import safe_url


def chart_upper(values):
    observed = [value for value in values if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0]
    return max(100, math.ceil(max(observed, default=100) / 50) * 50)


def metric_caption(unit):
    return "Tỷ lệ quan tâm so anchor = 100; có thể vượt 100" if unit in {"anchor_100", "anchor100", "anchor_ratio_100"} else "Chỉ số Google Trends tương đối 0–100"


def link(label, url):
    return (str(label), url) if safe_url(url) else str(label)


def cell_html(value):
    if isinstance(value, tuple) and len(value) == 2 and all(isinstance(v, str) for v in value) and safe_url(value[1]):
        return '<a href="' + escape(value[1], quote=True) + '" target="_blank" rel="noopener noreferrer">' + escape(value[0]) + '</a>'
    return escape("Chưa có" if value is None else str(value))


def cell_md(value):
    if isinstance(value, tuple) and len(value) == 2 and all(isinstance(v, str) for v in value) and safe_url(value[1]):
        return "[" + value[0].replace("[", "").replace("]", "") + "](<" + value[1].replace(">", "%3E") + ">)"
    return ("Chưa có" if value is None else str(value)).replace("|", "\\|").replace("\n", " ").replace("<", "&lt;").replace(">", "&gt;")


class Document:
    def __init__(self):
        self.html, self.md = [], []
        # One semantic source for HTML, Markdown and a real hyperlinked PDF.
        self.blocks = []

    def heading(self, title, level=2):
        self.blocks.append({"type": "heading", "text": title, "level": level})
        self.html.append(f"<h{level}>" + escape(title) + f"</h{level}>")
        self.md.append("#" * level + " " + title + "\n")

    def paragraph(self, value, kind=""):
        self.blocks.append({"type": "paragraph", "text": str(value), "kind": kind})
        self.html.append('<p class="' + kind + '">' + escape(str(value)) + "</p>")
        self.md.append(str(value) + "\n")

    def table(self, headers, rows):
        if not rows:
            self.paragraph("Chưa đủ dữ liệu cho bảng này.")
            return
        self.blocks.append({"type": "table", "headers": list(headers), "rows": list(rows)})
        self.html.append('<div class="table-scroll"><table><thead><tr>' + "".join("<th>" + cell_html(h) + "</th>" for h in headers) + "</tr></thead><tbody>" + "".join("<tr>" + "".join("<td>" + cell_html(v) + "</td>" for v in row) + "</tr>" for row in rows) + "</tbody></table></div>")
        self.md.extend(["| " + " | ".join(map(cell_md, headers)) + " |", "| " + " | ".join("---" for _ in headers) + " |"] + ["| " + " | ".join(map(cell_md, row)) + " |" for row in rows] + [""])

    def chart(self, history):
        series = history.get("forecast", [])
        if not series:
            return
        upper = chart_upper([row.get(key) for row in series for key in ("prediction", "observed")])
        self.blocks.append({"type": "chart", "history": history, "y_max": upper})
        lines = []
        for key, color in (("prediction", "#4754d8"), ("observed", "#0d8d78")):
            segments, segment = [], []
            previous_month = None
            for row in series:
                if previous_month is not None and row["month"] != previous_month + 1 and segment:
                    segments.append(segment); segment = []
                previous_month = row["month"]
                value = row.get(key)
                if key == "observed" and row.get("observation_status") != "complete":
                    value = None
                if value is None:
                    if segment:
                        segments.append(segment)
                        segment = []
                else:
                    segment.append(f"{30 + (row['month']-1)*45},{150 - max(0,value)/upper*120:.2f}")
            if segment:
                segments.append(segment)
            lines.extend(f'<polyline fill="none" stroke="{color}" stroke-width="3" points="{" ".join(points)}"/>' for points in segments)
        labels = "".join(f'<text x="{30+(m-1)*45}" y="175" text-anchor="middle">{m}</text>' for m in range(1, 13))
        self.html.append('<figure><svg role="img" aria-label="Dự báo tham khảo và các tháng đã quan sát" viewBox="0 0 565 185"><path d="M25 20V155H540" fill="none" stroke="#b9c3d5"/>' + "".join(lines) + labels + '</svg><figcaption>' + metric_caption(history.get("metric_unit")) + '; trục Y 0–' + str(upper) + '. Tím: dự báo · Xanh: quan sát đầy đủ. Tháng không thu để trống; không phải doanh số.</figcaption></figure>')
        self.md.append("Biểu đồ dự báo và quan sát có trong bản HTML; các giá trị đầy đủ nằm ở bảng forecast.\n")

    def historical_chart(self, title, monthly, years, metric_unit=None):
        """Same-query yearly profiles retain missing months as gaps."""
        years = list(years)
        upper = chart_upper([row.get("value") for row in monthly])
        self.blocks.append({"type": "historical_chart", "title": title, "monthly": monthly, "years": years, "y_max": upper, "metric_unit": metric_unit})
        palette = ["#354bd6", "#0b8f7a", "#c07c22", "#a15fb4", "#d15c72", "#526b83"]
        paths = []
        for index, year in enumerate(years):
            rows = {r["month"]: r for r in monthly if r["year"] == year}
            segment = []
            for month in range(1, 13):
                row = rows.get(month, {})
                value = row.get("value") if row.get("status") == "complete" else None
                if value is None:
                    if segment:
                        paths.append('<polyline fill="none" stroke="' + palette[index % len(palette)] + '" stroke-width="2" points="' + " ".join(segment) + '"/>')
                        segment = []
                else:
                    segment.append(f"{30+(month-1)*45},{150-max(0,value)/upper*120:.2f}")
            if segment:
                paths.append('<polyline fill="none" stroke="' + palette[index % len(palette)] + '" stroke-width="2" points="' + " ".join(segment) + '"/>')
        labels = "".join(f'<text x="{30+(m-1)*45}" y="175" text-anchor="middle">{m}</text>' for m in range(1,13))
        legend = " · ".join('<span style="color:' + palette[i % len(palette)] + '">' + str(y) + '</span>' for i,y in enumerate(years))
        self.html.append('<figure><strong>' + escape(title) + '</strong><svg role="img" aria-label="So sánh cùng tháng theo năm" viewBox="0 0 565 185"><path d="M25 20V155H540" fill="none" stroke="#b9c3d5"/>' + "".join(paths) + labels + '</svg><figcaption>Năm: ' + legend + '. ' + metric_caption(metric_unit) + '; trục Y 0–' + str(upper) + '. Cùng truy vấn/thang; tháng không thu hoặc thiếu để trống.</figcaption></figure>')
        self.md.append("Biểu đồ cùng kỳ: " + title + "; năm " + ", ".join(map(str, years)) + ". Xem HTML/PDF; bảng gốc ở trend_observations.\n")

    def product_card(self, product, image_asset=None):
        self.blocks.append({"type": "product_card", "product": product, "image": image_asset or {}})
        picture = image_asset or {}
        body = '<article class="catalog-card">'
        if picture.get("status") == "available":
            body += '<img alt="Ảnh sản phẩm từ nguồn" src="' + escape(picture["relative"], quote=True) + '">'
        body += '<h4>' + cell_html(link(product["name"], product["url"])) + '</h4>'
        for key in ("identity", "price", "signals", "description", "review", "history"):
            if product.get(key):
                body += '<p>' + escape(product[key]) + '</p>'
        if picture.get("status") != "available":
            body += '<p class="note">Ảnh: ' + escape(picture.get("reason", "Nguồn chưa có ảnh")) + '</p>'
        if product.get("review_url"):
            body += '<p>' + cell_html(link("Mở phản hồi nguồn", product["review_url"])) + '</p>'
        self.html.append(body + '</article>')
        self.md.append("### " + product["name"] + "\n")
        self.md.append(cell_md(link("Mở sản phẩm", product["url"])) + "\n")
        for key in ("identity", "price", "signals", "description", "review", "history"):
            if product.get(key):
                self.md.append(product[key] + "\n")
        if product.get("review_url"):
            self.md.append(cell_md(link("Phản hồi nguồn", product["review_url"])) + "\n")

    def render(self, title, subtitle):
        css = """
        :root{font-family:Segoe UI,Arial,sans-serif;color:#18253d;background:#edf1f7;line-height:1.65}body{margin:0}main{max-width:1120px;margin:28px auto;background:white;padding:44px;border-radius:18px;box-shadow:0 14px 60px #172b4d12}h1{font-size:32px;line-height:1.25;letter-spacing:-.8px}h2{margin-top:40px;padding-top:20px;border-top:1px solid #e4e9f1;color:#263b6d}h3{margin-top:30px}h4{font-size:17px}p{max-width:1000px}a{color:#354bd6;overflow-wrap:anywhere}.subtitle,.note,figcaption{color:#58657b;font-size:14px}.warning{background:#fff4d6;border-left:4px solid #d39a1f;padding:14px}.table-scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:13px;margin:18px 0}th{background:#f0f3fc;text-align:left;color:#293e6c}td,th{padding:11px;border-bottom:1px solid #e3e8f1;vertical-align:top;min-width:70px;overflow-wrap:anywhere}tr:nth-child(even){background:#fafbfe}svg{width:min(100%,650px);font-size:12px}figure{margin:20px 0}nav{display:flex;gap:16px;padding:16px 0}button{border:0;background:#4754d8;color:white;padding:10px 16px;border-radius:7px;cursor:pointer}.catalog-card{border:1px solid #e2e7f0;border-radius:12px;padding:18px;margin:14px 0}.catalog-card img{width:110px;height:110px;object-fit:contain;float:right}input{padding:12px;border:1px solid #bbc5d7;border-radius:8px;width:min(90%,450px)}@media(max-width:700px){main{margin:0;padding:22px;border-radius:0}h1{font-size:26px}}@media print{body{background:white}main{margin:0;padding:0;box-shadow:none;max-width:none}nav,.filter{display:none}table{font-size:10px}tr,figure,.catalog-card{break-inside:avoid}h2,h3,h4{break-after:avoid}.table-scroll{overflow:visible}a{color:#263b6d}}
        """
        html = '<!doctype html><html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>' + escape(title) + '</title><style>' + css + '</style></head><body><main><nav><button onclick="window.print()">In trang HTML</button></nav><p class="subtitle">' + escape(subtitle) + '</p>' + "".join(self.html) + '</main></body></html>'
        return "\n".join(self.md), html
