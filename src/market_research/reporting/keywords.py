"""Readable monthly overview and a full, linked keyword evidence companion."""
from .document import Document
from ..workflow.selection import verified_months


def fmt(value):
    return "Chưa có" if value is None else f"{value:.2f}" if isinstance(value, float) else str(value)


def interest(value):
    return "<0.01" if value is not None and 0 < value < .01 else fmt(value)


def month_scope(data):
    selected = data.get("selection", {}).get("selection_basis") in {"historical_selling_months", "selected_month_observations"}
    seasonal = data["config"].get("trends", {}).get("history_scope") == "seasonal"
    return selected or seasonal


def observed_month_scope(data):
    return (data.get("selection", {}).get("selection_basis") or data.get("screening", {}).get("selection_basis")) == "selected_month_observations"


def verified_month_label(row):
    months = verified_months(row)
    return ", ".join(map(str, months)) if months else "Chưa ghi riêng tháng đủ tín hiệu" if "monthly_metrics" not in row else "Không có tháng đủ tín hiệu"


def screening_details(doc, data):
    """Keep the model's distinguishing features and measured period visible."""
    monthly = month_scope(data)
    months = data["config"].get("selling_months") or data["config"].get("trends", {}).get("history_months", [])
    doc.heading("Sàng lọc mẫu hàng và keyword trước khi tìm sản phẩm")
    doc.paragraph(data.get("selection", {}).get("note") or data.get("screening", {}).get("note", ""), "note")
    if monthly:
        year = data.get("screening", {}).get("analysis_year") or data["config"].get("trends", {}).get("analysis_year")
        doc.paragraph("Tháng phân tích: " + ", ".join(map(str, months)) + (" năm " + str(year) if year else "") + ". So sánh đúng truy vấn mẫu hàng: kiểu dáng, cấu trúc, vật liệu, hoàn thiện hoặc họa tiết đã nêu trên cùng thang đo; mức quan tâm tìm kiếm không phải số lượng đã bán.", "note")
    rows = data.get("keyword_selection") or data.get("keyword_screening", [])
    observed = observed_month_scope(data)
    def scope(row):
        return "loại hàng rộng hơn; chưa xác minh riêng mẫu cụ thể" if row.get("measurement_scope") == "broader_product_type" else "đúng cụm truy vấn đã nêu"
    def choice(row):
        if row.get("selected"):
            return "Có · đã đo" if row.get("rank") is not None else "Có · chưa xác minh Trends"
        return "Không: " + row.get("reason", "Chưa đủ phép đo hoặc ngoài Top N")
    if observed:
        doc.paragraph("Mỗi mẫu được kiểm tra riêng từng tháng. Điểm đại diện dùng tháng đủ tín hiệu mạnh nhất; một mẫu đạt trong tháng 12 không có nghĩa tháng 10 cũng đạt.", "note")
        doc.table(["Mẫu hàng / keyword", "Truy vấn thực sự đo", "Tháng đủ tín hiệu", "Tháng mạnh nhất / quan tâm anchor", "Điểm / hạng tháng mạnh nhất", "Chọn / lý do"],
            [[r["keyword"], r.get("measurement_query") or r["keyword"], verified_month_label(r),
              (str(r["peak_month"]) + " / " + interest(r.get("peak_relative_interest"))) if r.get("peak_month") is not None else "Chưa ghi riêng / " + interest(r.get("relative_interest")),
              fmt(r.get("score")) + " / " + fmt(r.get("rank")), choice(r)] for r in rows])
        month_rows = [[r["keyword"], str(metric.get("month")) + "/" + str(metric.get("year", r.get("analysis_year", ""))),
            "Đủ tín hiệu" if metric.get("status") == "available" else "Ít tín hiệu" if metric.get("status") == "low_signal" else "Chưa đủ dữ liệu",
            interest(metric.get("relative_interest")), fmt(metric.get("rank")), metric.get("observed_days", 0),
            str(metric.get("positive_points", 0)) + "/" + str(metric.get("required_positive_points", "?")), metric.get("reason", "")]
            for r in rows for metric in r.get("monthly_metrics", [])]
        if month_rows:
            doc.table(["Mẫu / keyword", "Tháng/năm", "Kết quả tháng", "Quan tâm / anchor", "Hạng tháng", "Ngày quan sát", "Mốc dương / yêu cầu", "Căn cứ"], month_rows)
    elif monthly:
        doc.table(["Mẫu hàng / keyword", "Truy vấn thực sự đo", "Phạm vi", "Quan tâm kỳ chọn / anchor", "Điểm / hạng kỳ chọn", "Chọn / lý do"],
            [[r["keyword"], r.get("measurement_query") or r["keyword"], scope(r), fmt(r.get("monthly_demand_ratio") if r.get("selection_basis") == "historical_selling_months" else r.get("relative_interest")),
              fmt(r.get("score")) + " / " + fmt(r.get("rank")), choice(r)] for r in rows])
    else:
        doc.table(["Keyword ứng viên", "Truy vấn thực sự đo", "Tín hiệu / phạm vi", "Quan tâm / anchor", "Tăng 28 ngày (%)", "Điểm / hạng", "Chọn / lý do"],
            [[r["keyword"], r.get("measurement_query") or r["keyword"],
              (str(r["positive_points"]) + "/" + str(r.get("observed_points", "?")) + " điểm có tín hiệu; " if r.get("positive_points") is not None else "") + scope(r),
              fmt(r.get("relative_interest")), fmt(r.get("growth_pct")), fmt(r.get("score")) + " / " + fmt(r.get("rank")), choice(r)] for r in rows])
    doc.paragraph("Phép đo loại hàng rộng chỉ hỗ trợ nhu cầu loại hàng đó. Truy vấn phải giữ các đặc điểm phân biệt mẫu như dáng móc khóa, kiểu lịch, kết cấu gáy, chất liệu, hoàn thiện hoặc họa tiết để so sánh mẫu tương ứng; listing và nhãn mua được kiểm tra riêng tại ngày quan sát.", "note")


def monthly_overview(doc, data):
    monthly = data.get("keyword_monthly", {})
    coverage = monthly.get("coverage", {})
    seasonal = data["config"].get("trends", {}).get("history_scope") == "seasonal"
    selected_months = data["config"].get("trends", {}).get("history_months", [10, 11, 12])
    doc.heading("Xếp hạng keyword tháng " + ", ".join(map(str, selected_months)) if seasonal else "Xếp hạng keyword theo tháng 1–12", 3)
    doc.paragraph(f"Tập khám phá: {len(data.get('keywords', []))} dòng keyword; "
        f"{coverage.get('candidate_keywords', 0)} truy vấn đo duy nhất, "
        f"{coverage.get('keywords_with_two_complete_cycles', 0)} truy vấn đủ ít nhất hai chu kỳ năm. "
        "Số lượng là độ rộng khảo sát, không phải độ chính xác. Danh sách đầy đủ và các dòng thiếu nằm trong keyword-monthly.html và CSV.", "note")
    doc.paragraph(monthly.get("note") or "Chưa có lịch sử đủ để xếp hạng theo tháng.", "note")
    rows = []
    for item in monthly.get("months", []):
        if seasonal and item["month"] not in selected_months:
            continue
        ranked = item.get("rankings", [])
        anchor_groups = {r["comparison_group"] for r in ranked if r.get("demand_metric_kind") == "query_to_anchor_ratio" and r.get("demand_rank") is not None}
        if len(anchor_groups) == 1:
            group = next(iter(anchor_groups))
            selected = sorted([r for r in ranked if r.get("comparison_group") == group and r.get("demand_rank") is not None], key=lambda r: (r["demand_rank"], r["measurement_query"]))[:3]
            basis = "Quan tâm so anchor chung; không phải doanh số"
            scores = "; ".join(fmt(r.get("demand_metric")) for r in selected)
        else:
            selected = ranked[:3]
            basis = "Phù hợp mùa vụ so đỉnh riêng; chưa có thang quan tâm chung"
            scores = "; ".join(fmt(r.get("seasonal_score")) for r in selected)
        rows.append(["Tháng " + str(item["month"]) + (" · kỳ bán" if item.get("selling_month") else ""),
            "; ".join(r["measurement_query"] for r in selected) or "Chưa đủ dữ liệu", scores or "Chưa có",
            f"{item.get('ranked_keywords', 0)}/{item.get('candidate_keywords', 0)} đủ lịch sử. {basis}"])
    if rows:
        doc.table(["Tháng", "Ba keyword ưu tiên trong mẫu", "Chỉ số theo thứ tự", "Độ phủ / cách đọc"], rows)


def build(data):
    doc = Document()
    doc.heading("Toàn bộ keyword và xếp hạng theo tháng", 1)
    doc.paragraph("Ứng viên LLM là giả thuyết; chỉ các dòng có dữ liệu nguồn mới được xếp hạng. Không coi số lượng keyword là độ chính xác hay quy mô toàn thị trường.", "note")
    metrics = {r["keyword_id"]: r for r in data.get("keyword_screening", [])}
    selected = {r["keyword_id"] for r in data.get("keyword_selection", []) if r.get("selected")}
    names = {n["id"]: n["name"] for n in data["config"]["niches"]}
    doc.heading("1. Tập ứng viên và kết quả sàng lọc", 2)
    doc.table(["Mẫu hàng / keyword / niche", "Truy vấn đo", "Nguồn / trạng thái", "Điểm tháng mạnh nhất" if observed_month_scope(data) else "Điểm kỳ chọn" if month_scope(data) else "Điểm gần đây", "Tháng đủ tín hiệu", "Tìm mẫu"], [
        [k["text"] + " / " + names.get(k["niche_id"], ""), metrics.get(k["id"], {}).get("measurement_query") or k["text"],
         str(k.get("origin", "seed")) + " / " + str(metrics.get(k["id"], {}).get("status", "chưa đo")),
         fmt(metrics.get(k["id"], {}).get("score")), verified_month_label(metrics.get(k["id"], {})) if observed_month_scope(data) else "Xem phạm vi kỳ đo", "Có" if k["id"] in selected else "Không"] for k in data.get("keywords", [])])
    if observed_month_scope(data):
        screening_details(doc, data)
    monthly = data.get("keyword_monthly", {})
    doc.paragraph(monthly.get("note") or "Chưa có chuỗi theo tháng.", "note")
    for month in monthly.get("months", []):
        if data["config"].get("trends", {}).get("history_scope") == "seasonal" and month["month"] not in data["config"]["trends"]["history_months"]:
            continue
        doc.heading("Tháng " + str(month["month"]), 2)
        values = [r for r in monthly.get("rows", []) if r["month"] == month["month"]]
        values.sort(key=lambda r: (r.get("seasonality_rank") or 99999, r["measurement_query"].casefold()))
        doc.table(["Keyword", "Hạng mùa vụ / điểm", "Hạng quan tâm / nhóm", "Cùng tháng qua các năm", "Căn cứ"], [[
            r["measurement_query"], fmt(r.get("seasonality_rank")) + " / " + fmt(r.get("seasonal_score")),
            fmt(r.get("demand_rank")) + " / " + r.get("comparison_label", "Chưa có"),
            "; ".join(str(y["year"]) + ": " + fmt(y["value"]) for y in r.get("year_observations", [])), r.get("reason", "Chưa có")] for r in values])
    return doc
