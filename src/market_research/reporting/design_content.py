"""Keep the design subject, measured query, month and actual sample together."""
from .document import link
from ..workflow.design_content import content_mode
from ..workflow.selection import verified_months


def overview(doc, data, evidence):
    if content_mode(data["config"]) != "designs":
        return
    directions = data.get("directions", [])
    doc.heading("Nội dung trên mẫu → keyword → sản phẩm đối chiếu", 3)
    rows = []
    for direction in directions:
        design = direction.get("source_design") or {}
        keyword = direction.get("measurement_query") or direction["keyword"]
        subject = design.get("subject") or direction["keyword"]
        sources = [evidence[eid] for eid in design.get("evidence_ids", []) if eid in evidence and evidence[eid].get("url")]
        source = link("Nguồn nội dung: " + subject, sources[0]["url"]) if sources else subject + " (nội dung trong keyword)"
        samples = [p for p in data.get("products", []) if direction["id"] in p.get("direction_ids", [])]
        months = verified_months(direction)
        period = ", ".join(map(str, months)) + (" / " + str(direction["analysis_year"]) if direction.get("analysis_year") else "") if months else "Chưa xác minh"
        sample = link(samples[0]["title"], samples[0]["url"]) if samples else "Chưa tìm được mẫu khớp nội dung"
        rows.append([source, keyword, period, sample])
    if rows:
        doc.table(["Hình / nhân vật / câu chữ", "Keyword đã đo", "Tháng đủ tín hiệu", "Mẫu hàng khớp"], rows)
        doc.paragraph("Ảnh và link của các mẫu nằm ở phần sản phẩm. Hình/câu chữ được đối chiếu theo văn bản nguồn/tiêu đề; cần kiểm tra ảnh và đúng biến thể trước khi gia công. Mức quan tâm Trends không phải doanh số.", "note")
    else:
        doc.paragraph("Chưa xác minh được nội dung hình/câu chữ trên mẫu. Cần tìm thêm nguồn và đo keyword chứa nội dung; không thay bằng độ hot của phôi hoặc loại áo chung.", "warning")
