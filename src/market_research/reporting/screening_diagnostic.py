"""A source-backed diagnostic artifact, never a fabricated product report."""
from html import escape

from ..common import write_json
from ..workflow.diagnostics import screening_diagnostics


def export_screening_diagnostic(output, config, screening, usage=()):
    output.mkdir(parents=True, exist_ok=True)
    info = screening_diagnostics(config, screening, usage)
    write_json(output / "screening-diagnostic.json", info)
    table = []
    for row in screening.get("rows", []):
        observations = row.get("analysis_observations", [])
        positive = sum(item.get("positive_points", 0) for item in observations)
        cells = [row.get("keyword", ""), row.get("status", ""), row.get("observed_days", ""), positive,
                 ", ".join(map(str, row.get("qualifying_months", []))) or "Chưa có", row.get("reason", "")]
        table.append("<tr>" + "".join("<td>" + escape(str(value)) + "</td>" for value in cells) + "</tr>")
    body = ("<!doctype html><html lang='vi'><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>Chẩn đoán bước sàng lọc Trends</title><style>body{font:16px system-ui;max-width:1100px;margin:32px auto;padding:0 20px;color:#243047}"
        "table{width:100%;border-collapse:collapse}td,th{padding:10px;border:1px solid #d9dfe8;text-align:left}th{background:#f3f5f9}p{line-height:1.6}</style>"
        "<h1>Chẩn đoán bước sàng lọc Trends</h1><p>" + escape(info.get("summary", "Chưa có phép đo")) + "</p><p>" +
        escape(info.get("explanation", "")) + "</p><p>" + escape(info.get("action", "")) + "</p>"
        "<p>Tài liệu này dùng kết quả đã lưu, không gọi nguồn mới, không tăng quota và không xác nhận mẫu nào đang bán chạy.</p>"
        "<table><thead><tr><th>Keyword đã đo</th><th>Trạng thái</th><th>Ngày có quan sát</th><th>Mốc dương</th><th>Tháng đủ tín hiệu</th><th>Lý do</th></tr></thead><tbody>" +
        "".join(table) + "</tbody></table></html>")
    (output / "screening-diagnostic.html").write_text(body, encoding="utf-8")
    return info
