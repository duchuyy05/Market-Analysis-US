"""Reports are Python documents; optional LLM commentary cannot erase facts."""
from html import escape
from pathlib import Path
from statistics import median

from ..common import now, write_json
from .document import Document, link, cell_html
from .validate import validate

STATUS = {"shortlist": "Ưu tiên kiểm chứng", "watchlist": "Theo dõi", "pending_verification": "Chờ xác minh điều kiện", "unavailable": "Chưa đủ dữ liệu", "stable": "Tương đối ổn định", "variable": "Có biến động", "insufficient": "Thiếu lịch sử", "positive": "Có tín hiệu phù hợp", "negative": "Có tín hiệu bất lợi", "neutral": "Trung tính", "unknown": "Chưa biết"}


def product_label(product):
    return product["title"] + (" · ASIN " + product["asin"] if product.get("asin") else " · " + product["product_id"])


def product_ref(product):
    return link(product_label(product), product["url"])


def missing_detail(product):
    if product.get("detail_status") == "search_only":
        return "Mới có kết quả tìm kiếm; chưa lấy chi tiết sản phẩm"
    fields = [name for name, row in product.get("attributes", {}).items() if isinstance(row, dict) and row.get("status") == "missing"]
    return "Đã lấy chi tiết; nguồn còn thiếu " + ", ".join(fields) if fields else "Đã lấy chi tiết" if product.get("detail_status") == "available" else "Chưa có chi tiết hợp lệ"


def fmt(value, digits=2):
    return "Chưa có" if value is None else f"{value:,.{digits}f}" if isinstance(value, (float, int)) else str(value)


def refs(doc, ids, evidence):
    rows = [[i, evidence[i]["kind"], link("Mở nguồn", evidence[i]["url"]), evidence[i]["retrieved_at"][:10]] for i in dict.fromkeys(ids) if i in evidence]
    doc.table(["Mã bằng chứng", "Loại", "Nguồn", "Ngày truy cập"], rows)


def idea_section(doc, idea, evidence, products=None):
    doc.heading(idea["title"], 4)
    doc.paragraph("Bán gì: " + idea["sell_what"])
    if idea.get("measurement_query"):
        doc.paragraph("Truy vấn kiểm chứng: " + idea["measurement_query"] + "; tháng yêu cầu: " + ", ".join(map(str, idea.get("requested_months", idea.get("analysis_months", [])))) + (" năm " + str(idea["analysis_year"]) if idea.get("analysis_year") else "") + ".")
        if idea.get("selection_basis") == "selected_month_observations":
            doc.paragraph("Tháng đủ tín hiệu của mẫu này: " + (", ".join(map(str, idea.get("verified_months", []))) or "lượt lưu chưa ghi riêng") + ".")
    doc.paragraph("Cho ai — giả thuyết cần xác minh: " + idea["customer"])
    doc.paragraph("Vì sao cân nhắc lúc này: " + idea["why_now"])
    doc.paragraph("Thông tin mẫu được nguồn nêu: " + idea["observed_specification"])
    doc.paragraph("Việc nên thử: " + idea["next_test"])
    if idea["review_quote"]:
        doc.paragraph("Một phản hồi trong mẫu: “" + idea["review_quote"]["text"] + "”. Đây là trích nguyên văn; chưa đại diện toàn thị trường.")
    sample = (products or {}).get(idea["sample_product_id"])
    doc.table(["Trạng thái", "Mẫu tham khảo", "Cách tạo"], [[STATUS.get(idea["status"], idea["status"]), product_ref(sample) if sample else link(idea["sample_product_id"], idea["sample_url"]), "Quy tắc Python có dẫn chứng"]])
    doc.paragraph("Còn thiếu: " + " ".join(idea["limitations"]), "note")
    refs(doc, idea["evidence_ids"], evidence)


def niche_section(doc, niche, data, evidence):
    ds = [d for d in data["directions"] if d["niche_id"] == niche["id"]]
    dids = {d["id"] for d in ds}
    history = {h["direction_id"]: h for h in data["histories"]}
    assessment = {a["direction_id"]: a for a in data["assessments"]["directions"]}
    products = [p for p in data["products"] if dids.intersection(p["direction_ids"])]
    doc.heading(niche["name"], 2)
    if not ds:
        doc.paragraph("Nhóm này chưa có keyword được chọn sau sàng lọc và giới hạn Top N, nên chưa có mẫu, comment hoặc idea đủ nguồn để phân tích. Giữ nhóm để thấy phần nghiên cứu còn thiếu; không điền bảng trống hoặc suy ra nhu cầu bằng 0.", "warning")
        return
    doc.heading("Keyword và tín hiệu quan tâm", 3)
    doc.table(["Hướng / keyword đại diện", "Keyword liên quan", "Tăng trưởng (%)", "Phạm vi tăng trưởng", "Trạng thái"], [[d["name"] + " / " + d["keyword"], ", ".join(k["text"] for k in data["keywords"] if k["id"] in d["keyword_ids"]), fmt(assessment[d["id"]]["growth_pct"]), assessment[d["id"]]["growth_scope"], STATUS[assessment[d["id"]]["status"]]] for d in ds])
    doc.heading("Phân tích mẫu hàng và khách hàng", 3)
    prices = [p["price"] for p in products if p["price"] is not None and p["currency"] == "USD"]
    doc.paragraph(f"Thu thập {len(products)} mẫu định danh trong niche. " + (f"Giá USD trong mẫu: {min(prices):.2f}–{max(prices):.2f}; trung vị {median(prices):.2f}. " if prices else "Chưa có khoảng giá USD. ") + "Giá có thể thuộc quy cách khác nhau; chưa đủ căn cứ kết luận mức cạnh tranh toàn thị trường.")
    doc.paragraph("Khách hàng dự kiến: " + niche.get("customer_hypothesis", "Chưa xác minh") + ". Đây là giả thuyết từ phạm vi nghiên cứu, không phải khảo sát nhân khẩu học.")
    doc.table(["Sản phẩm / ASIN", "Giá / tiền tệ", "Sao / số đánh giá", "Nguồn / nhà bán", "Nhãn mua", "Chi tiết / phần thiếu", "Ngày quan sát"],
        [[product_ref(p), fmt(p["price"]) + " " + str(p["currency"]) if p.get("price") is not None else "Nguồn chưa trả giá",
          (fmt(p["rating"]) if p.get("rating") is not None else "Nguồn chưa trả sao") + " / " + (str(p["review_count"]) + " đánh giá" if p.get("review_count") is not None else "Chưa trả số đánh giá"),
          p.get("source", "") + " / " + p.get("merchant", "Chưa xác định"), p.get("purchase_badge") or "Nguồn không nêu lượt mua",
          missing_detail(p), p["observed_at"][:10]] for p in products])
    doc.paragraph("Sao/số đánh giá ở bảng sản phẩm thuộc listing hoặc nhóm biến thể của nguồn, không phải số review đã thu thập và không thay thế sao của từng comment. Trường thiếu ở đây nghĩa là nguồn hoặc nhánh lấy chi tiết chưa cung cấp, không phải giá trị bằng 0.", "note")
    review_rows = [r for r in data["review_themes"] if r["product_id"] in {p["product_id"] for p in products}]
    unique = []
    for r in review_rows:
        if (r["product_id"], r["theme"]) not in {(x["product_id"], x["theme"]) for x in unique}:
            unique.append(r)
    by_product = {p["product_id"]: p for p in products}
    if unique:
        doc.heading("Chủ đề được nhắc trong phản hồi", 4)
        doc.table(["Sản phẩm / ASIN", "Chủ đề được nhắc", "Trích đoạn nguyên văn", "Sao của review"], [[product_ref(by_product[r["product_id"]]), r["label"], r["excerpt"], r["rating"] if r.get("rating") is not None else "Nguồn không trả sao của review này"] for r in unique[:8]])
    doc.paragraph("Lượt nhắc chủ đề là phân loại theo từ trong nội dung; chưa phải tỷ lệ phàn nàn hay mức hài lòng toàn thị trường.", "note")
    refs(doc, [e for r in unique[:8] for e in r["evidence_ids"]], evidence)
    raw_reviews = [r for r in data["reviews"] if r["product_id"] in by_product]
    doc.heading("Comment đã thu thập và sản phẩm tương ứng", 3)
    if raw_reviews:
        reviewed_ids = {r["product_id"] for r in raw_reviews}
        doc.paragraph(f"Có {len(raw_reviews)} phản hồi trên {len(reviewed_ids)}/{len(products)} sản phẩm trong niche. Các sản phẩm khác chưa có comment được thu thập; không suy rộng nhận xét sang chúng.", "note")
        # Keep the report readable; complete reviews remain in tables/reviews.*.
        queues = [[r for r in raw_reviews if r["product_id"] == pid] for pid in sorted(reviewed_ids)]
        displayed = [queue[i] for i in range(max(map(len, queues), default=0)) for queue in queues if i < len(queue)][:30]
        if len(displayed) < len(raw_reviews):
            doc.paragraph(f"Hiển thị {len(displayed)}/{len(raw_reviews)} comment, xen kẽ sản phẩm để tránh một mẫu chiếm hết chỗ. Toàn bộ comment có trong tables/reviews.csv và JSON.", "note")
        rows = []
        for review in displayed:
            source = next((evidence[e]["url"] for e in review["evidence_ids"] if e in evidence and evidence[e].get("kind") == "review"), by_product[review["product_id"]]["url"])
            rows.append([product_ref(by_product[review["product_id"]]), "Review đầy đủ" if review.get("kind") == "full" else "Trích đoạn từ nguồn",
                review["text"], (str(review["rating"]) + " sao" if review.get("rating") is not None else "Nguồn không nêu sao") + "; " + (review.get("published_at") or "không nêu ngày"), link("Mở comment nguồn", source)])
        doc.table(["Sản phẩm / ASIN", "Loại nội dung", "Comment nguyên văn", "Sao / ngày của comment", "Link comment"], rows)
        doc.paragraph("Trích đoạn có thể bị cắt và thiếu sao/ngày/xác minh mua hàng; không tự dùng sao tổng của sản phẩm để điền vào comment. Mọi dòng giữ đúng sản phẩm và đường dẫn bằng chứng đã thu thập.", "note")
    else:
        doc.paragraph("Chưa thu thập được review hoặc trích đoạn gắn với mẫu trong niche này. Không có phản hồi không đồng nghĩa khách hàng không có ý kiến.", "note")
    doc.heading("Lịch sử " + ", ".join(map(str, data["config"]["history_years"])) + " và dự báo tham khảo " + str(data["config"]["target_year"]), 3)
    for d in ds:
        h = history.get(d["id"], {})
        doc.heading(d["name"], 4)
        if h.get("status") != "available":
            doc.paragraph("Chưa có lịch sử hợp lệ; hướng này vẫn được nghiên cứu từ mẫu hiện tại.")
            continue
        in_season = h.get("analysis_scope") == "selected_months"
        doc.paragraph(("Độ ổn định trong các tháng đã thu: " if in_season else "Độ ổn định mức quan tâm theo năm: ") + STATUS[h["stability"]] + ". Các năm đủ tín hiệu: " + ", ".join(map(str, h["usable_years"])) + ".")
        if in_season:
            doc.paragraph("Chỉ tháng " + ", ".join(map(str, h["collected_months"])) + ". Đơn vị tỷ lệ so anchor = 100, có thể vượt 100; không phải chỉ số raw Google Trends 0–100 hoặc đỉnh của cả năm.", "note")
        if h["annual_means"]:
            doc.table(["Năm", "Trung bình kỳ đã thu" if in_season else "Trung bình chỉ số", "Tháng cao nhất trong kỳ" if in_season else "Tháng cao điểm"], [[r["year"], r["mean_index"], next((p["month"] for p in h["peak_months"] if p["year"] == r["year"]), None)] for r in h["annual_means"]])
        if h.get("comparison_periods"):
            doc.heading("Đối chiếu các khoảng tháng đã chọn", 4)
            doc.table(["Khoảng thời gian", "Chỉ số trung bình", "Độ phủ", "Tháng đầy đủ", "Thay đổi với kỳ trước (%)", "Trạng thái / lưu ý"],
                [[r.get("label") or r["start"] + " đến " + r["end"], fmt(r.get("mean_index")), fmt(r.get("coverage_pct")) + "%", str(r.get("complete_months", 0)) + "/" + str(r.get("requested_months", 0)), fmt(r.get("change_vs_previous_pct")), r.get("status", "") + ": " + r.get("note", "")] for r in h["comparison_periods"]])
        if not any(row.get("prediction") is not None for row in h["forecast"]):
            doc.paragraph("Chuỗi chưa đủ tín hiệu để dựng dự báo: không trình bày biểu đồ trống hoặc bảng dự báo toàn ô thiếu. Quan sát gốc và độ phủ vẫn nằm trong bảng trend_observations/forecasts để kiểm tra.", "note")
            refs(doc, h["evidence_ids"], evidence)
            continue
        test = h["backtest"]
        doc.paragraph(f"Kiểm chứng hồi cứu {test['train_years']} → {test['test_year']}: MAE={fmt(test['mae'])}; mốc cùng kỳ năm trước={fmt(test['seasonal_naive_mae'])}. " + ("Chưa tốt hơn mốc so sánh." if test["better_than_baseline"] is False else "Sai số nhỏ hơn mốc trong phép thử này." if test["better_than_baseline"] is True else "Chưa đủ dữ liệu kiểm chứng."))
        doc.chart(h)
        doc.table(["Tháng", "Dự báo chỉ số", "Quan sát", "Trạng thái quan sát", "Min–max lịch sử"], [[r["month"], fmt(r["prediction"]), fmt(r["observed"]), r["observation_status"], fmt(r["historical_min"]) + "–" + fmt(r["historical_max"])] for r in h["forecast"] if r["selling_month"]])
        refs(doc, h["evidence_ids"], evidence)
    doc.heading("Idea sản phẩm có mẫu đối chiếu", 3)
    ideas = [i for i in data["ideas"] if i["niche_id"] == niche["id"]]
    if len(ideas) < 2:
        doc.paragraph("Chưa đủ hai idea có căn cứ cho niche này. Danh sách giữ đúng những mẫu đã xác minh.", "warning")
    for idea in ideas[:3]:
        idea_section(doc, idea, evidence, by_product)
    if len(ideas) > 3:
        doc.heading("Hướng bổ sung", 4)
        doc.table(["Idea", "Trạng thái", "Mẫu"], [[i["sell_what"], STATUS[i["status"]], link(i["sample_product_id"], i["sample_url"])] for i in ideas[3:]])
    for insight in data.get("commentary", {}).get(niche["id"], []):
        doc.heading("Diễn giải bổ sung từ LLM", 4)
        doc.paragraph(insight["text"])
        if insight.get("quote"):
            doc.paragraph("Trích nguồn: " + insight["quote"]["text"])
        refs(doc, insight["evidence_ids"], evidence)


def export(run, data):
    validation = validate(data, run.evidence)
    write_json(run.output / "validation.json", validation)
    config = data["config"]
    doc = Document()
    doc.heading("Nghiên cứu cơ hội sản phẩm", 1)
    doc.paragraph(config["category"])
    doc.paragraph("Mô tả đầu vào: " + config["brief"])
    doc.paragraph("Cách hiểu: " + config.get("interpretation", config["category"]))
    if data.get("selection"):
        selection = data["selection"]
        doc.paragraph(f"Đã chọn {selection['selected_keywords']}/{selection['available_keywords']} keyword đại diện để tìm mẫu. Trần yêu cầu: {selection['requested'] if selection['requested'] is not None else 'không đặt'}. " + selection["note"], "note")
    mode = "PHÁT LẠI DỮ LIỆU ĐÃ LƯU — không phải nghiên cứu thị trường hiện tại" if config["mode"] == "offline" else "NGHIÊN CỨU NGUỒN THẬT"
    doc.paragraph(mode, "warning" if config["mode"] == "offline" else "note")
    doc.paragraph(f"Ngày chốt: {config['as_of_date']} · Thị trường: US · Tháng bán: {config['selling_months']} · Năm dự báo: {config['target_year']}. Ngày truy cập nằm ở từng nguồn.")
    if run.manifest["warnings"]:
        doc.paragraph("Nguồn/khâu chưa đầy đủ: " + " | ".join(run.manifest["warnings"]), "warning")
    for assumption in config["assumptions"]:
        doc.paragraph("Giả định: " + assumption, "note")
    doc.heading("Kết quả và phạm vi bằng chứng")
    doc.table(["Niche", "Keyword", "Hướng", "Mẫu hàng", "Review đầy đủ", "Trích đoạn"], [[len(config["niches"]), len(data["keywords"]), len(data["directions"]), len(data["products"]), sum(r["kind"] == "full" for r in data["reviews"]), sum(r["kind"] == "excerpt" for r in data["reviews"])]])
    sampled_directions = {did for p in data["products"] for did in p.get("direction_ids", [])}
    active_niches = {d["niche_id"] for d in data["directions"] if d["id"] in sampled_directions}
    detail_count = sum(p.get("detail_status") == "available" for p in data["products"])
    reviewed_ids = {r["product_id"] for r in data["reviews"]}
    doc.table(["Độ phủ nghiên cứu", "Thực tế", "Ý nghĩa"], [["Niche có mẫu", f"{len(active_niches)}/{len(config['niches'])}", "Đếm nhóm có sản phẩm thật, không chỉ nhóm LLM đề xuất"],
        ["Sản phẩm đã lấy chi tiết", f"{detail_count}/{len(data['products'])}", "Kết quả tìm kiếm không thay thế trang chi tiết"],
        ["Sản phẩm có comment thu thập", f"{len(reviewed_ids)}/{len(data['products'])}", "Comment tập trung ở một mẫu không đại diện tất cả mẫu"],
        ["Keyword đã chọn tìm mẫu", f"{len({d['keyword'].casefold() for d in data['directions']})}/{len({k['text'].casefold() for k in data['keywords']})}", "Số keyword thấp sẽ giới hạn độ rộng mẫu dù còn quota"]])
    doc.paragraph("Các đề xuất là ưu tiên kiểm chứng trong mẫu. Keyword tăng, nhãn mua, mùa vụ và độ đầy đủ nguồn là những tín hiệu riêng; chưa có giá vốn để kết luận lợi nhuận.")
    if data.get("keyword_screening") and data.get("screening", {}).get("status") != "skipped":
        from .keywords import screening_details
        screening_details(doc, data)
        refs(doc, [e for r in data["keyword_screening"] for e in r["evidence_ids"]], run.evidence)
    if data.get("discovery_sources"):
        doc.heading("Khám phá từ trang công khai ngoài Amazon")
        doc.paragraph("Tavily tìm trang được lập chỉ mục, có ưu tiên Mỹ trong truy vấn. Chưa xác minh quốc gia người xem hay lượng mua. Có thể không có kết quả ở từng nền tảng; lượt xem, lượt thích, quảng cáo và keyword không phải doanh số.", "note")
        doc.table(["Nhánh / nền tảng", "Trạng thái", "Số trang", "Còn thiếu"], [[", ".join(r.get("sites", [r["branch"]])), r["status"], r.get("count"), r.get("reason")] for r in data["discovery_sources"]])
        doc.table(["Nền tảng", "Trang tham khảo", "Ngày xuất bản nguồn nêu"], [[p["platform"], link(p["title"], p["url"]), p.get("published_at")] for p in data["web_context"] if p.get("url")])
        refs(doc, [e for p in data["web_context"] for e in p["evidence_ids"]], run.evidence)
    for niche in config["niches"]:
        niche_section(doc, niche, data, run.evidence)
        separate = Document()
        separate.heading("Báo cáo niche — " + niche["name"], 1)
        separate.paragraph(mode + " · " + config["as_of_date"])
        niche_section(separate, niche, data, run.evidence)
        write_document(run.output / "niches" / niche["id"], separate, niche["name"], mode)
    doc.heading("Xếp hạng niche và ba idea nổi bật")
    names = {n["id"]: n["name"] for n in config["niches"]}
    ranking = data["rankings"]
    rows = [r for r in ranking["items"] if r["ranking_id"] == "niche_priority"]
    doc.table(["Nhóm so sánh", "Hạng (có thể đồng hạng)", "Niche", "Rubric mùa / cầu / mua / khác biệt / phù hợp"], [[r["group"], r["rank"], names[r["entity_id"]], r["metric"]] for r in rows])
    top = [r for r in ranking["items"] if r["ranking_id"] == "idea_priority"][:3]
    by_idea = {i["id"]: i for i in data["ideas"]}
    doc.table(["Nhóm so sánh", "Hạng", "Idea", "Niche", "Mẫu"], [[r["group"], r["rank"], by_idea[r["entity_id"]]["sell_what"], names[by_idea[r["entity_id"]]["niche_id"]], link("Mở mẫu", by_idea[r["entity_id"]]["sample_url"])] for r in top])
    doc.paragraph("Ba dòng là phần tóm tắt; các idea đồng hạng chưa được chứng minh hơn kém nhau. Không so thứ hạng giữa các nhóm known có độ đầy đủ thông tin khác nhau. Rubric lần lượt là mùa, cầu, mua, khác biệt và phù hợp; True nghĩa là có tín hiệu dương. Danh sách đầy đủ vẫn nằm trong bảng dữ liệu và báo cáo niche.", "note")
    doc.heading("Các bảng xếp hạng")
    entity_names = {**names, **{d["id"]: d["name"] for d in data["directions"]}, **{k["id"]: k["text"] for k in data["keywords"]}, **{p["product_id"]: p["title"] for p in data["products"]}, **{i["id"]: i["title"] for i in data["ideas"]}}
    for definition in ranking["definitions"]:
        doc.heading(definition["label"], 3)
        doc.paragraph(definition["scope"] + ". Phiên bản: " + definition["version"])
        ranked = [r for r in ranking["items"] if r["ranking_id"] == definition["id"]]
        if not ranked:
            doc.paragraph(definition["reason"])
        else:
            doc.table(["Nhóm so sánh", "Hạng", "Đối tượng", "Chỉ số/rubric"], [[r["group"], r["rank"], entity_names.get(r["entity_id"], r["entity_id"]), r["metric"]] for r in ranked[:config["limits"]["ranking_rows"]]])
    doc.heading("Phương pháp, chi phí và phần còn thiếu")
    doc.paragraph("Python tạo toàn bộ báo cáo, bảng, biểu đồ và idea từ quy tắc. LLM, nếu bật, chỉ hiểu mô tả, gom keyword và bổ sung diễn giải có nguồn. Trường thiếu giữ nguyên chưa biết; không gán thành số không.")
    doc.paragraph("Lịch sử dùng trung vị cùng tháng của các năm đã hoàn tất. CV mức quan tâm năm ≤ 0,25 được gắn tương đối ổn định. Chuỗi ít tín hiệu không dự báo. Dữ liệu 2026 không dùng để fit dự báo 2026. Min–max lịch sử không phải khoảng tin cậy. Nguồn tải hồi cứu không phải snapshot quá khứ.")
    usage = run.manifest["usage"]
    known = [u["cost_usd"] for u in usage if isinstance(u.get("cost_usd"), (float, int))]
    limits = config["limits"]
    counts = {provider: sum(u["provider"] == provider for u in usage) for provider in ("serpapi", "tavily", "exa", "openrouter", "google_trends_free")}
    doc.table(["Nguồn", "Trần của lượt", "Lần thử đã dùng", "Còn trong trần", "Chi phí biết được"], [[provider, limits.get(key), counts[provider], max(0, limits.get(key, 0)-counts[provider]), fmt(sum(u["cost_usd"] for u in usage if u["provider"] == provider and isinstance(u.get("cost_usd"), (float, int)))) if any(u["provider"] == provider and u.get("cost_usd") is not None for u in usage) else "Chưa biết / dùng quota tài khoản"] for provider, key in (("serpapi", "serpapi_requests"), ("tavily", "tavily_requests"), ("exa", "exa_requests"), ("openrouter", "llm_requests"), ("google_trends_free", "free_trends_requests"))])
    trend_used = sum(u["provider"] == "serpapi" and u.get("engine") == "google_trends" for u in usage)
    trend_cap = min(limits.get("trends_serpapi_requests", limits["serpapi_requests"]), max(0, limits["serpapi_requests"]-limits.get("serpapi_product_reserve", 0)))
    doc.table(["Phần SerpApi", "Lần thử đã dùng", "Giới hạn / phạm vi"], [["Trends (sàng lọc + lịch sử + related)", trend_used, str(trend_cap) + " trong tổng SerpApi"],
        ["Tìm Amazon", sum(u["provider"] == "serpapi" and u.get("engine") == "amazon" for u in usage), "Theo keyword đã được chọn"],
        ["Tìm Shopping", sum(u["provider"] == "serpapi" and u.get("engine") == "google_shopping" for u in usage), "Theo lựa chọn và trần Shopping của lượt"],
        ["Chi tiết Amazon", sum(u["provider"] == "serpapi" and u.get("engine") == "amazon_product" for u in usage), str(limits.get("product_details", "chưa đặt")) + " mục tiêu chi tiết toàn lượt"]])
    doc.paragraph("Trần API là giới hạn trên, không phải mục tiêu gọi cho hết. Trần Trends riêng, số keyword đo được và số mẫu lấy chi tiết có thể làm dừng từng nhánh khi tổng SerpApi vẫn còn. Còn quota không chứng minh dữ liệu đã đủ; xem bảng độ phủ và phần thiếu trước khi quyết định.", "note")
    doc.paragraph(f"Đọc cache trong lượt: {run.manifest.get('cache_hits', 0)}; cache dùng chung: {run.manifest.get('shared_cache_hits', 0)}. Offline không phát sinh request. Tổng chi phí chưa xác định khi nguồn không cung cấp đơn giá.")
    for gap in validation["gaps"] + validation["errors"]:
        doc.paragraph(gap, "note")
    doc.paragraph(validation["limitation"], "note")
    doc.paragraph("Tài liệu phương pháp: https://support.google.com/trends/answer/4365533 · https://otexts.com/fpp3/toolbox.html")
    # Retain all evidence and raw tables in a companion rather than repeating
    # them in the reader-facing six-part report.
    write_document(run.output / "report-details", doc, "Phụ lục đầy đủ: cơ hội sản phẩm", mode)
    from .summary import build
    doc = build(run, data)
    images = [{"product_id": block["product"].get("product_id"), **block.get("image", {})} for block in doc.blocks if block["type"] == "product_card"]
    image_status = {"requested": len(images), "available": sum(row.get("status") == "available" for row in images), "items": images,
                    "note": "Ảnh tải từ CDN công khai/cache; không dùng lượt SerpApi/Tavily/OpenRouter."}
    write_json(run.output / "image-status.json", image_status)
    run.manifest["report_images"] = {k: v for k, v in image_status.items() if k != "items"}
    if hasattr(run, "log"):
        run.log("report", "product_images_prepared", "Đã chuẩn bị ảnh sản phẩm cho báo cáo", requested=image_status["requested"], available=image_status["available"], missing=[{"product_id": item["product_id"], "reason": item.get("reason"), "error_code": item.get("error_code")} for item in images if item.get("status") != "available"])
    from .keywords import build as keyword_document
    write_document(run.output / "keyword-monthly", keyword_document(data), "Keyword và xếp hạng tháng", mode)
    from .pdf import export_pdf
    pdf_status = export_pdf(run.output / "report.pdf", doc, "Báo cáo cơ hội sản phẩm", mode + " · " + config["as_of_date"])
    write_json(run.output / "pdf-status.json", pdf_status)
    run.manifest["pdf"] = pdf_status
    catalog(run, data, mode)
    write_json(run.output / "dataset.json", data)
    write_json(run.output / "sources.json", run.evidence)
    write_json(run.output / "usage.json", {"requests": usage, "known_cost_usd": sum(known), "total_cost_status": "known" if usage and len(known) == len(usage) else "unknown" if usage else "no_requests", "cache_hits": run.manifest.get("cache_hits", 0), "shared_cache_hits": run.manifest.get("shared_cache_hits", 0)})
    # Publish the main report after its PDF/data/usage companions are available.
    # PDF generation takes longer than a UI poll, so early HTML exposed a report
    # whose linked usage/data files still returned 404.
    write_document(run.output / "report", doc, "Báo cáo cơ hội sản phẩm", mode)
    if pdf_status["status"] == "available":
        report = run.output / "report.html"
        report.write_text(report.read_text(encoding="utf-8").replace('<nav>', '<nav><a href="report.pdf" download>Tải PDF có link bấm được</a><a href="keyword-monthly.html">Keyword theo tháng phân tích</a><a href="report-details.html">Phụ lục đầy đủ</a><a href="catalog.html">Tất cả mẫu sản phẩm</a>'), encoding="utf-8")
    return validation


def write_document(path, doc, title, subtitle):
    path.parent.mkdir(parents=True, exist_ok=True)
    md, html = doc.render(title, subtitle)
    path.with_suffix(".md").write_text(md, encoding="utf-8")
    path.with_suffix(".html").write_text(html, encoding="utf-8")


def catalog(run, data, mode):
    doc = Document()
    doc.heading("Catalog mẫu sản phẩm", 1)
    doc.paragraph(mode)
    doc.paragraph("Mẫu để đối chiếu; thứ tự hiển thị không phải xếp hạng bán chạy. Rating và nhãn mua giữ phạm vi của nguồn.")
    doc.html.append('<label class="filter">Tìm mẫu <input id="filter" placeholder="Nhập tên, ASIN hoặc nhà bán"></label>')
    directions = {d["id"]: d["name"] for d in data["directions"]}
    for p in data["products"]:
        body = '<article class="catalog-card" data-search="' + escape((p["title"] + " " + str(p["asin"]) + " " + p["merchant"]).lower(), quote=True) + '">'
        if p.get("thumbnail"):
            body += '<img loading="lazy" alt="Ảnh mẫu từ nguồn" src="' + escape(p["thumbnail"], quote=True) + '">'
        body += '<h3>' + cell_html(link(p["title"], p["url"])) + '</h3><p>' + escape(p["merchant"] + " · " + str(p["currency"]) + " " + fmt(p["price"]) + " · " + p["observed_at"][:10]) + '</p><p>' + escape("; ".join(directions[i] for i in p["direction_ids"])) + '</p><p>' + escape("Nhãn mua: " + (p["purchase_badge"] or "Chưa có") + " · Chi tiết: " + p["detail_status"]) + '</p><p class="note">' + escape("Nguồn: " + ", ".join(p["evidence_ids"])) + '</p></article>'
        doc.html.append(body)
    doc.html.append('<script>document.getElementById("filter").addEventListener("input",e=>{document.querySelectorAll("[data-search]").forEach(c=>c.hidden=!c.dataset.search.includes(e.target.value.toLowerCase()))})</script>')
    doc.table(["Sản phẩm", "Hướng", "Giá", "Tiền tệ", "Nhãn mua", "Ngày", "Phạm vi đánh giá"], [[link(p["title"], p["url"]), "; ".join(directions[i] for i in p["direction_ids"]), p["price"], p["currency"], p["purchase_badge"], p["observed_at"], p["rating_scope"]] for p in data["products"]])
    write_document(run.output / "catalog", doc, "Catalog mẫu sản phẩm", mode)
