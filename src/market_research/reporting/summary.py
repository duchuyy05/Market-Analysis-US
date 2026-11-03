"""A bounded six-part reader report; detailed exports stay separate."""
from ..common import ROOT
from .document import Document, link
from .images import prepare
from ..workflow.quality import has_forecast, has_backtest
from ..workflow.selection import verified_months
from .keywords import interest

SECTIONS = ["1. Mục tiêu nghiên cứu", "2. Keyword và xu hướng", "3. Kiểm chứng và dự báo",
            "4. Sản phẩm và bằng chứng thị trường", "5. Đề xuất nên cân nhắc bán", "6. Tổng kết ưu tiên"]
LABELS = {"stable": "Ổn định tương đối", "variable": "Có biến động", "insufficient": "Thiếu lịch sử", "shortlist": "Ưu tiên kiểm chứng", "watchlist": "Theo dõi", "pending_verification": "Cần xác minh", "available": "Có dữ liệu", "unavailable": "Chưa đủ dữ liệu", "complete": "Đầy đủ", "partial": "Có phần thiếu", "limited": "Hạn chế", "moderate": "Vừa", "stronger_evidence": "Nhiều bằng chứng hơn"}


def fmt(value, digits=2):
    return "Chưa có" if value is None else f"{value:,.{digits}f}" if isinstance(value, (int, float)) else str(value)


def short(value, maximum=180):
    text = " ".join(str(value or "").split())
    return text if len(text) <= maximum else text[:maximum-1].rstrip() + "…"


def query(direction, history):
    return history.get("measurement_query") or direction.get("measurement_query") or direction["keyword"]


def selection_reason(row):
    if row.get("selection_basis") == "historical_selling_months":
        basis = "Kỳ bán: quan tâm/anchor " + fmt(row.get("monthly_demand_ratio")) + "; mùa vụ " + fmt(row.get("seasonal_score")) + ". "
    elif row.get("selection_basis") == "selected_month_observations":
        year = " năm " + str(row["analysis_year"]) if row.get("analysis_year") else ""
        months = verified_months(row)
        if months:
            basis = "Đủ tín hiệu tháng " + ", ".join(map(str, months)) + year + ". "
            peak = next((metric for metric in row.get("monthly_metrics", []) if metric.get("month") == row.get("peak_month")), {})
            basis += "Mạnh nhất tháng " + str(row.get("peak_month")) + ": quan tâm/anchor " + interest(row.get("peak_relative_interest", row.get("relative_interest")))
            if peak.get("observed_days") is not None:
                basis += "; " + str(peak["observed_days"]) + " ngày ở tháng này"
            basis += ". "
        else:
            basis = "Kỳ đã chọn" + year + ": quan tâm/anchor " + fmt(row.get("relative_interest")) + "; chưa ghi riêng tháng đủ tín hiệu. "
    else:
        ratio = row.get("relative_interest")
        growth = fmt(row["growth_pct"]) + "%" if row.get("growth_pct") is not None else "chưa đủ mốc so sánh"
        basis = "So anchor " + ("<0.01" if 0 < (ratio or 0) < .01 else fmt(ratio)) + "; tăng 28 ngày " + growth + ". "
    return basis + short(row.get("reason") or "Chưa có lý do từ nguồn", 100)


def stability(history):
    return history.get("seasonal_stability", {}).get("status", history.get("stability"))


def representative(histories, directions, niches):
    by_id = {h["direction_id"]: h for h in histories}
    output = []
    for niche in niches:
        candidates = [d for d in directions if d["niche_id"] == niche["id"]]
        candidates.sort(key=lambda d: (by_id.get(d["id"], {}).get("status") != "available", -len(by_id.get(d["id"], {}).get("usable_years", []))))
        if candidates:
            output.append((candidates[0], by_id.get(candidates[0]["id"], {})))
    return output


def build(run, data):
    c, evidence = data["config"], run.evidence
    selected_scope = c.get("trends", {}).get("history_scope") == "seasonal"
    niches, directions, products = c["niches"], data["directions"], data["products"]
    names = {n["id"]: n["name"] for n in niches}
    by_product = {p["product_id"]: p for p in products}
    histories = {h["direction_id"]: h for h in data["histories"]}
    chosen = [r for r in data.get("keyword_selection", []) if r.get("selected")]
    doc = Document()
    doc.heading("Nghiên cứu cơ hội sản phẩm", 1)
    mode = "PHÁT LẠI DỮ LIỆU ĐÃ LƯU" if c["mode"] == "offline" else "NGHIÊN CỨU NGUỒN THẬT"
    doc.paragraph(f"{mode} | Chốt dữ liệu: {c['as_of_date']} | Thị trường: {c['market']} | Năm dự báo: {c['target_year']}", "note")
    sampled = {d["niche_id"] for d in directions if any(d["id"] in p["direction_ids"] for p in products)}
    review_products = len({r["product_id"] for r in data["reviews"]})
    doc.paragraph(f"Phạm vi thực tế: {len(chosen) or len(directions)} dòng keyword chọn, {len(products)} mẫu, {len(sampled)}/{len(niches)} niche có sản phẩm, {len(data['reviews'])} phản hồi/trích đoạn thuộc {review_products}/{len(products)} mẫu. Báo cáo là ưu tiên kiểm chứng trong mẫu, chưa phải kết luận doanh số hoặc lợi nhuận.")
    observed = sum(h.get("status") == "available" and bool(h.get("monthly")) for h in histories.values())
    predicted = sum(has_forecast(h) for h in histories.values())
    tested = sum(has_backtest(h) for h in histories.values())
    doc.paragraph(f"Kiểm chứng lịch sử: {observed}/{len(directions)} hướng có chuỗi; {predicted}/{len(directions)} hướng có dự báo; {tested}/{len(directions)} có sai số hồi cứu. " + ("Chưa thể kết luận toàn bộ hướng ổn định qua các năm." if observed < len(directions) or predicted < len(directions) or tested < len(directions) else "Xem sai số hồi cứu và giới hạn ở phần 3."), "warning" if predicted < len(directions) or tested < len(directions) else "note")

    doc.heading(SECTIONS[0])
    doc.table(["Nội dung", "Phạm vi nghiên cứu"], [
        ["Đầu vào", short(c["brief"], 500)], ["Danh mục", short(c["category"], 200)],
        ["Thị trường / kỳ bán", f"{c['market']} / tháng " + ", ".join(map(str, c["selling_months"])) + f" năm {c['target_year']}"],
        ["Lịch sử đối chiếu", ", ".join(map(str, c["history_years"]))],
        ["Phạm vi dữ liệu", "Chỉ tháng " + ", ".join(map(str, c["trends"]["history_months"])) + " của từng năm lịch sử; tháng khác không thu" if selected_scope else "Chuỗi cả năm đến ngày chốt"],
        ["Điều kiện", ("Giá USD " + "–".join(map(str, c["price_range"])) if c.get("price_range") else "Chưa có khoảng giá cố định") + "; bắt buộc: " + (", ".join(c.get("required_features", [])) or "chưa khai báo")],
        ["Chuẩn bị / loại trừ", (str(c["preparation_days"]) + " ngày" if c.get("preparation_days") is not None else "Chưa biết số ngày chuẩn bị") + "; " + (", ".join(c.get("excluded_features", [])) or "chưa có loại trừ")]])
    if c.get("business", {}).get("profile") == "custom_manufacturing":
        from ..business.domain import CATEGORY_LABELS
        doc.paragraph("Domain công ty: " + "; ".join(CATEGORY_LABELS[key] for key in c["business"]["categories"]) + ". Loại thực phẩm, mỹ phẩm và thiết bị/máy móc phức tạp. Phân loại phù hợp nhóm hàng chưa chứng minh nhà máy sản xuất được mọi quy cách.", "note")
    if data.get("selection", {}).get("selection_basis") == "selected_month_observations":
        year = data.get("screening", {}).get("analysis_year")
        windows = data.get("screening", {}).get("analysis_windows", [])
        label = "; ".join(str(w.get("start", "")) + " → " + str(w.get("end", "")) for w in windows)
        doc.paragraph("Kỳ sàng lọc mẫu hàng: " + (label or ("tháng " + ", ".join(map(str, c["selling_months"])) + (" năm " + str(year) if year else ""))) + ". Kỳ quan sát này được tách khỏi năm dự báo và các năm lịch sử đối chiếu.", "note")
    doc.table(["Niche", "Khách hàng dự kiến", "Mẫu thu được"], [[n["name"], short(n.get("customer_hypothesis") or "Giả thuyết chưa xác minh", 150),
        sum(bool(set(p["direction_ids"]) & {d["id"] for d in directions if d["niche_id"] == n["id"]}) for p in products)] for n in niches])
    if c.get("assumptions"):
        doc.paragraph("Giả định cần kiểm tra: " + short(c["assumptions"][0], 220) + ". Các giả định đầy đủ có trong phụ lục.", "note")

    doc.heading(SECTIONS[1])
    from .design_content import overview as design_overview
    design_overview(doc, data, evidence)
    if data.get("selection", {}).get("selection_basis") in {"historical_selling_months", "selected_month_observations"}:
        doc.paragraph(data["selection"]["note"], "note")
    elif data.get("selection", {}).get("is_trends_hot_ranking"):
        doc.paragraph("Thứ tự trong tập ứng viên: 70% phân vị mức quan tâm so anchor + 30% phân vị tăng trưởng 28 ngày. Truy vấn đo loại hàng rộng được ghi riêng; không coi mọi biến thể cá nhân hóa có cùng độ hot.", "note")
    else:
        doc.paragraph("Danh sách đại diện theo nguồn/seed đã thu được, chưa phải Top độ hot qua Trends. Không đổi thứ tự thu thập thành bằng chứng sản phẩm đang bán chạy.", "warning")
    ranked = sorted(chosen, key=lambda r: (r.get("search_order") or 999, r["keyword"]))
    if not ranked:
        ranked = [{"keyword": d["keyword"], "niche_id": d["niche_id"], "measurement_query": d.get("measurement_query"), "rank": None, "reason": "Keyword đại diện; không có sàng lọc hiện tại trong bộ lưu trữ"} for d in directions]
    doc.table(["Niche / keyword", "Truy vấn đo", "Hạng / điểm tháng mạnh nhất" if data.get("selection", {}).get("selection_basis") == "selected_month_observations" else "Hạng / điểm", "Căn cứ lựa chọn"], [[names.get(r.get("niche_id"), "") + " / " + r["keyword"], r.get("measurement_query") or r["keyword"],
        (str(r["rank"]) + " / " + fmt(r.get("score"))) if r.get("rank") is not None else "Chưa xếp hạng",
         selection_reason(r)] for r in ranked[:10]])
    from .keywords import monthly_overview
    if data.get("keyword_monthly"):
        monthly_overview(doc, data)
    unit_note = "Chỉ số tỷ lệ so anchor = 100, có thể vượt 100; biến động là tương đối so anchor trong các kỳ đã chọn. Không kết luận đỉnh cả năm khi chỉ thu một mùa." if selected_scope else "Chỉ số 0–100 không phải số lượt tìm kiếm tuyệt đối."
    doc.paragraph(("Các đường năm bên dưới so cùng tháng trên cùng truy vấn/thang. " if observed else "Chưa lấy được chuỗi lịch sử để vẽ so sánh năm. ") + unit_note + " Tháng không thu hoặc thiếu để trống. Điểm xếp hạng 0 là vị trí thấp trong tập, không có nghĩa không ai tìm kiếm. Toàn bộ ứng viên và lý do loại có trong bảng keyword_screening/keyword_selection.", "note")
    if any(d.get("grouping_method") == "seed_rules" for d in directions):
        doc.paragraph("Một số hướng được gom theo seed bằng Python khi LLM không sẵn sàng; cách gom nhóm không phải bằng chứng độ hot. Phép đo Trends và mẫu sản phẩm được lưu riêng.", "note")
    reps = representative(data["histories"], directions, niches)
    for d, h in reps[:3]:
        if h.get("monthly"):
            doc.historical_chart(names[d["niche_id"]] + " / " + (h.get("measurement_query") or d.get("measurement_query") or d["keyword"]), h["monthly"], c["history_years"], h.get("metric_unit"))
    period_rows = []
    for d, h in reps:
        rows = h.get("same_period") or h.get("annual_means", [])
        for row in rows:
            period_rows.append([query(d, h), row["year"], fmt(row.get("mean_index")), fmt(row.get("yoy_pct")), fmt(row.get("coverage_pct")), LABELS.get(row.get("status", stability(h)), row.get("status", stability(h)))])
    if period_rows:
        doc.table(["Loại hàng / cùng kỳ tháng bán", "Năm", "Chỉ số TB", "Thay đổi (%)", "Độ phủ (%)", "Trạng thái"], period_rows[:18])
    comparisons = [[query(d, h), row.get("label") or str(row["start"]) + " → " + str(row["end"]), fmt(row.get("mean_index")), fmt(row.get("coverage_pct")), fmt(row.get("change_vs_previous_pct"))]
        for d, h in reps for row in h.get("comparison_periods", [])]
    if comparisons:
        doc.table(["Loại hàng / khoảng tự chọn", "Tháng bắt đầu – kết thúc", "Chỉ số TB", "Độ phủ (%)", "Đổi so khoảng trước (%)"], comparisons[:12])
        doc.paragraph("Khoảng tự chọn được giữ riêng với kỳ bán; chỉ so chỉ số của cùng truy vấn và cùng thang. Các khoảng còn lại trong phụ lục/bảng comparison_periods.", "note")
    stability_rows = []
    for d, h in reps:
        seasonal = h.get("seasonal_stability", {})
        stability_rows.append([query(d, h),
            LABELS.get(stability(h), "Thiếu lịch sử"), fmt(seasonal.get("annual_cv", h.get("annual_cv"))),
            fmt(seasonal.get("profile_correlation")), fmt(seasonal.get("peak_consistency", h.get("peak_consistency")))])
    doc.table(["Loại hàng", "Ổn định trong kỳ" if selected_scope else "Độ ổn định", "CV kỳ đã thu" if selected_scope else "CV mức năm", "Tương quan trong kỳ" if selected_scope else "Tương quan mùa", "Lặp tháng đỉnh trong kỳ" if selected_scope else "Lặp tháng đỉnh (0–1)"], stability_rows)
    doc.paragraph("Các chỉ tiêu chỉ phản ánh tháng đã chọn, không phản ánh cả năm." if selected_scope else "CV nhỏ thể hiện mức trung bình năm ít dao động; tương quan mùa gần 1 thể hiện nhịp các tháng giống nhau; tỷ lệ lặp đỉnh đo khả năng cao điểm quay lại cùng tháng. Không có dữ liệu giữ trống, không gán thành 0.", "note")

    doc.heading(SECTIONS[2])
    doc.paragraph("Lịch sử " + ", ".join(map(str, c["history_years"])) + " và dự báo tham khảo " + str(c["target_year"]) + ". Kiểm chứng: dùng các năm trước để dự đoán năm đã biết rồi đối chiếu thực tế; so với mốc cùng kỳ năm trước. Năm đích không được dùng để huấn luyện.")
    validation_rows, forecast_rows = [], []
    for d in directions:
        h = histories.get(d["id"], {})
        val = h.get("validation", {})
        metrics = val.get("metrics", {})
        baseline = val.get("baseline_metrics", {})
        old = h.get("backtest", {})
        confidence = val.get("confidence", {})
        tested_years = ", ".join(str(f["test_year"]) for f in val.get("folds", [])) or (str(old.get("test_year")) if old.get("months_tested") else "Chưa có")
        validation_rows.append([query(d, h), tested_years,
            fmt(metrics.get("mae", old.get("mae"))), fmt(baseline.get("mae", old.get("seasonal_naive_mae"))), fmt(metrics.get("wape_pct")), fmt(val.get("skill_pct")),
            LABELS.get(confidence.get("level"), "Chưa đánh giá") + "; " + LABELS.get(stability(h), "Thiếu lịch sử")])
        selling = [r for r in h.get("forecast", []) if r.get("selling_month")]
        available = [r for r in selling if r.get("prediction") is not None]
        forecast_rows.append([query(d, h), ", ".join(str(r["month"]) + ": " + fmt(r.get("prediction")) for r in available) or "Chưa đủ dữ liệu dự báo",
            str(len(h.get("usable_years", []))) + " năm đủ tín hiệu", short("; ".join(confidence.get("reasons", [])[:2]) if confidence else h.get("reason") or "Kiểm chứng hồi cứu còn hạn chế", 140)])
    doc.table(["Truy vấn kiểm chứng", "Năm đã dự đoán thử", "MAE", "MAE mốc cơ sở", "WAPE (%)", "Cải thiện (%)", "Độ tin cậy / ổn định"], validation_rows[:10])
    doc.paragraph("MAE thấp hơn nghĩa là sai số chỉ số nhỏ hơn; WAPE là sai số tổng tuyệt đối theo tổng quan sát (để thiếu khi mẫu nền bằng 0). Cải thiện dương nghĩa là tốt hơn mốc cơ sở, không phải xác suất dự báo đúng. Nhãn độ tin cậy là đánh giá về độ phủ/lần kiểm chứng, không phải phần trăm bảo đảm.", "note")
    doc.table(["Loại hàng", "Dự báo chỉ số cho tháng bán", "Lịch sử đủ dùng", "Giới hạn"], forecast_rows[:10])
    doc.paragraph(("Chỉ dự báo các tháng đã chọn; tháng ngoài phạm vi không được tạo dữ liệu." if selected_scope else "Biểu đồ dự báo đủ 12 tháng nằm trong phụ lục.") + " Min–max lịch sử là độ phân tán quan sát, không phải khoảng tin cậy xác suất. Kiểm chứng trên keyword chọn ở hiện tại có thiên lệch chọn mẫu; chưa chứng minh đã tìm được cơ hội ở thời điểm quá khứ.", "note")

    doc.heading(SECTIONS[3])
    if data.get("discovery_sources") or data.get("web_context"):
        doc.paragraph("Khám phá từ trang công khai: " + str(len(data.get("web_context", []))) + " trang đã thu thập. Tavily tìm nội dung được lập chỉ mục để bổ sung ý tưởng/nguồn; không truy cập dữ liệu riêng của tài khoản hoặc chứng minh doanh số tại Mỹ.", "note")
    selected_products, used = [], set()
    for niche in niches:
        if len(selected_products) >= 9:
            break
        dids = {d["id"] for d in directions if d["niche_id"] == niche["id"]}
        samples = [p for p in products if dids & set(p["direction_ids"])]
        idea_samples = {i["sample_product_id"] for i in data["ideas"] if i["niche_id"] == niche["id"]}
        samples.sort(key=lambda p: (p["product_id"] not in idea_samples, p.get("detail_status") != "available", -(p.get("purchase_lower_bound") or 0), -(p.get("review_count") or 0)))
        for p in samples:
            if p["product_id"] not in used:
                selected_products.append((niche, p))
                used.add(p["product_id"])
                if sum(n["id"] == niche["id"] for n, _ in selected_products) >= 3 or len(selected_products) >= 9:
                    break
    if not selected_products:
        doc.paragraph("Chưa có mẫu sản phẩm hợp lệ. Không tạo mẫu giả để đủ số lượng.", "warning")
    else:
        doc.paragraph(f"Bản chính trình bày {len(selected_products)}/{len(products)} mẫu, tối đa ba mẫu/niche và chín mẫu toàn báo cáo; catalog và bảng dữ liệu giữ tất cả mẫu, phản hồi và nguồn. Giá/nhãn mua là quan sát tại ngày lấy, chưa phải lịch sử bán hàng.", "note")
    prepared = prepare(run, [p for _, p in selected_products], allow_network=run.root == ROOT and c["mode"] == "live", limit=15)
    product_history = data.get("product_history", {})
    snapshot_items = {row.get("product_id"): row for row in product_history.get("items", [])}
    for niche, p in selected_products[:9]:
        reviews = [r for r in data["reviews"] if r["product_id"] == p["product_id"]]
        review = reviews[0] if reviews else None
        review_url = next((evidence[e]["url"] for e in (review or {}).get("evidence_ids", []) if e in evidence and evidence[e].get("url")), None)
        captures = snapshot_items.get(p["product_id"], {})
        captured_years = captures.get("captured_years", [])
        history_text = "Bản ghi sản phẩm có ở năm: " + ", ".join(map(str, captured_years)) if captured_years else "Chưa có chuỗi giá/tín hiệu mua nhiều năm cho đúng mẫu này; không suy lịch sử Amazon từ Trends loại hàng."
        card = {"product_id": p["product_id"], "name": short(p["title"], 115), "url": p["url"], "identity": names[niche["id"]] + " | " + ("ASIN " + p["asin"] if p.get("asin") else "Nguồn " + p.get("source", "shopping")),
            "price": (fmt(p["price"]) + " " + str(p.get("currency") or "chưa rõ tiền tệ")) if p.get("price") is not None else "Nguồn chưa trả giá",
            "signals": (p.get("purchase_badge") or "Chưa có nhãn mua") + " | Sao listing: " + fmt(p.get("rating")) + " | Số đánh giá: " + fmt(p.get("review_count"), 0) + " | Ngày lấy: " + p["observed_at"][:10],
            "description": short(p.get("description") or "Mẫu tham khảo theo tiêu đề nguồn; chưa có mô tả chi tiết được thu thập.", 160),
            "review": ("Trích đoạn: " + short(review["text"], 180) + ". Sao riêng: " + fmt(review.get("rating"))) if review else "Chưa thu thập phản hồi của mẫu này; không mượn nhận xét từ sản phẩm khác.",
            "review_url": review_url, "history": history_text}
        picture = prepared.get(p["product_id"], {})
        doc.product_card(card, picture)
    evidence_rows = []
    for direction in directions:
        samples = [p for p in products if direction["id"] in p["direction_ids"]]
        pids = {p["product_id"] for p in samples}
        prices = [p["price"] for p in samples if p.get("currency") == "USD" and p.get("price") is not None]
        rr = [r for r in data["reviews"] if r["product_id"] in pids]
        evidence_rows.append([direction["keyword"], f"{len(samples)} / {sum(p.get('detail_status') == 'available' for p in samples)}", f"{fmt(min(prices))}–{fmt(max(prices))}" if prices else "Chưa có", f"{len(rr)} trích đoạn / {len({r['product_id'] for r in rr})} mẫu", ", ".join(sorted({p.get("source", "") for p in samples})) or "Chưa có"])
    if evidence_rows:
        doc.heading("Độ phủ bằng chứng theo hướng sản phẩm", 3)
        doc.table(["Hướng", "Mẫu / có chi tiết", "Khoảng giá USD", "Phản hồi thực lấy", "Nguồn mẫu"], evidence_rows)
        doc.paragraph("Giá là quan sát listing, chưa đồng nhất quy cách/phí vận chuyển. Tổng số sao và số đánh giá trên listing khác số phản hồi đã thu. Khớp keyword là bước lọc sơ bộ; mục đích sử dụng và phù hợp người nhận cần kiểm tra.", "note")
    tool_sources=[row for row in data.get("source_status",[]) if row.get("collection_method")=="public_http"]
    if tool_sources:
        doc.heading("Kết quả công cụ thu thập trực tiếp",3)
        doc.table(["Nguồn", "Trạng thái", "Mẫu / thảo luận", "Ghi nhận"],[[row["source"],row.get("status"),row.get("count",0),row.get("reason") or "Dữ liệu trang công khai tại thời điểm lấy"] for row in tool_sources[:15]])
    if data.get("discussions"):
        doc.heading("Thảo luận Reddit — nguồn ngữ cảnh, chưa xác minh người mua",3)
        doc.table(["Thảo luận", "Điểm / bình luận", "Ngày đăng", "Phạm vi"], [[link(short(row["title"],160),row["link"]),str(row.get("score"))+" / "+str(row.get("num_comments")),row.get("published_at") or "Chưa có","Không phải doanh số hoặc review khách mua"] for row in data["discussions"][:10]])
    social = [p for p in data.get("web_context", []) if p.get("url") and p.get("platform") in {"facebook", "tiktok"}]
    if social:
        doc.table(["Nguồn công khai", "Trang liên quan", "Cách sử dụng"], [[p["platform"], link(short(p["title"], 110), p["url"]), "Khám phá ngữ cảnh/ý tưởng; chưa phải doanh số hoặc khán giả Mỹ đã xác minh"] for p in social[:3]])
    doc.paragraph(product_history.get("note") or "Đối chiếu nhiều năm của keyword nói về loại hàng. Độ ổn định của đúng ASIN, giá và nhãn mua cần các snapshot thực tế theo thời gian; thiếu bản ghi quá khứ thì ghi chưa đủ dữ liệu.", "note")

    doc.heading(SECTIONS[4])
    for niche in niches:
        doc.heading(niche["name"], 3)
        ideas = [i for i in data["ideas"] if i["niche_id"] == niche["id"]]
        if not ideas:
            doc.paragraph("Chưa có idea có mẫu đủ nguồn cho niche này. Cần bổ sung keyword/mẫu phù hợp; không điền sản phẩm giả.")
            continue
        if len(ideas) < 2:
            doc.paragraph("Mục tiêu 2–3 idea; hiện chỉ đủ " + str(len(ideas)) + " idea có mẫu, phần thiếu được giữ rõ.", "note")
        doc.table(["Bán gì / cho ai", "Căn cứ / điểm cần kiểm tra", "Mẫu đối chiếu / giá", "Mẫu thay thế / giá"], [
            [short(i["sell_what"], 120) + " | " + short(i["customer"], 110), short(i["why_now"], 150) + " | " + short("; ".join(i.get("evidence_gaps", [])) or i.get("observed_specification"), 120),
             link(short(by_product[i["sample_product_id"]]["title"], 75) + " | " + fmt(by_product[i["sample_product_id"]].get("price")) + " " + str(by_product[i["sample_product_id"]].get("currency") or ""), i["sample_url"]) if i["sample_product_id"] in by_product else link("Mở mẫu", i["sample_url"]),
             link(short(i["alternatives"][0]["title"], 75) + " | " + fmt(i["alternatives"][0].get("price")) + " " + str(i["alternatives"][0].get("currency") or ""), i["alternatives"][0]["url"]) if i.get("alternatives") else "Chưa có mẫu thay thế cùng hướng"] for i in ideas[:3]])

    doc.heading(SECTIONS[5])
    rows = []
    for niche in niches:
        aa = [a for a in data["assessments"]["directions"] if a["niche_id"] == niche["id"]]
        sampled_products = [p for p in products if set(p["direction_ids"]) & {d["id"] for d in directions if d["niche_id"] == niche["id"]}]
        hs = [histories.get(d["id"], {}) for d in directions if d["niche_id"] == niche["id"]]
        state = "Ưu tiên kiểm chứng" if any(a["status"] == "shortlist" for a in aa) else "Theo dõi" if sampled_products else "Cần bổ sung dữ liệu"
        stable = sum(stability(h) == "stable" for h in hs)
        rows.append([niche["name"], state, len(sampled_products), f"{stable}/{len(hs)} hướng ổn định", "Thử mẫu/giá vốn/quy cách" if sampled_products else "Tìm keyword đo được và mẫu nguồn"])
    doc.table(["Niche", "Ưu tiên trong mẫu", "Mẫu", "Bằng chứng lịch sử", "Bước tiếp theo"], rows)
    doc.paragraph("Ưu tiên kiểm chứng phụ thuộc độ đủ nguồn và điều kiện sản phẩm; không tự đổi thành khuyến nghị mua hàng hay bảo đảm bán chạy. Trước nhập hàng cần giá vốn, phí sàn/vận chuyển, kiểm tra mẫu và thử bán.")
    missing = list(dict.fromkeys([str(w) for w in run.manifest.get("warnings", [])]))
    if missing:
        doc.paragraph("Thông tin còn thiếu: " + " | ".join(short(w, 160) for w in missing[:3]) + (f" | Còn {len(missing)-3} cảnh báo khác trong nhật ký." if len(missing)>3 else ""), "warning")
    usage = run.manifest.get("usage", [])
    used = {name: sum(u["provider"] == name for u in usage) for name in ("public_scraper", "serpapi", "tavily", "exa", "openrouter")}
    doc.table(["Ngân sách", "Đã dùng / trần", "Lưu ý"], [[name, str(used[name]) + " / " + str(c["limits"].get(key, 0)), "Gồm thất bại/thử lại; ứng dụng chưa biết số dư credit miễn phí"] for name,key in (("public_scraper","scraper_requests"),("serpapi","serpapi_requests"),("tavily","tavily_requests"),("exa","exa_requests"),("openrouter","llm_requests"))])
    doc.paragraph("Chi tiết kiểm tra: catalog.html giữ toàn bộ mẫu; report-details.html có toàn bộ review/nguồn/ranking; tables/ giữ chuỗi và sai số; dữ liệu database lưu quan sát để đối chiếu các lần chạy. Bản chính giới hạn số dòng để đọc nhanh, không xóa dữ liệu đầy đủ.", "note")
    return doc
