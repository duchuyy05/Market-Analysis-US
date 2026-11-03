"""Validate references and report completeness, without claiming semantic truth."""
from ..workflow.quality import has_forecast, has_backtest


def validate(dataset, evidence):
    errors, gaps = [], []
    products = {p["product_id"]: p for p in dataset["products"]}
    directions = {d["id"]: d for d in dataset["directions"]}
    def visit(value, path="dataset"):
        if isinstance(value, dict):
            ids = value.get("evidence_ids", [])
            if not isinstance(ids, list) or any(i not in evidence for i in ids):
                errors.append(path + ": mã bằng chứng không tồn tại")
            for key, item in value.items():
                visit(item, path + "." + key)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, f"{path}[{index}]")
    visit(dataset)
    for p in products.values():
        if not p["evidence_ids"] or any(d not in directions for d in p["direction_ids"]):
            errors.append("Sản phẩm thiếu nguồn hoặc dẫn hướng không tồn tại")
    for idea in dataset["ideas"]:
        p = products.get(idea["sample_product_id"])
        if not p or idea["direction_id"] not in p["direction_ids"]:
            errors.append("Idea dẫn sai mẫu/hướng")
        quote = idea.get("review_quote")
        if quote:
            if not any(quote["text"] in (evidence[e].get("excerpt") or "") for e in quote["evidence_ids"] if e in evidence):
                errors.append("Quote idea không khớp review")
            if p and any(evidence[e].get("kind") != "review" or evidence[e].get("asin") != p.get("asin") for e in quote["evidence_ids"] if e in evidence):
                errors.append("Review trích dẫn không thuộc sản phẩm của idea")
    niche_count = len(dataset["config"]["niches"])
    if not 3 <= niche_count <= 5:
        gaps.append("Task 1 cần 3–5 niche; lượt này có " + str(niche_count))
    for n in dataset["config"]["niches"]:
        count = sum(i["niche_id"] == n["id"] for i in dataset["ideas"])
        if count < 2:
            gaps.append(f"{n['name']}: chỉ có {count} idea có mẫu nguồn; không tự điền đủ số lượng")
    if not products:
        gaps.append("Chưa có mẫu sản phẩm hợp lệ")
    if dataset["config"].get("sources", {}).get("trends") and directions:
        histories = {h["direction_id"]: h for h in dataset.get("histories", [])}
        observed = sum(histories.get(did, {}).get("status") == "available" and bool(histories.get(did, {}).get("monthly")) for did in directions)
        forecasted = sum(has_forecast(histories.get(did, {})) for did in directions)
        tested = sum(has_backtest(histories.get(did, {})) for did in directions)
        if observed < len(directions):
            gaps.append(f"Lịch sử Trends: chỉ có {observed}/{len(directions)} hướng có chuỗi để đối chiếu các năm; chưa đủ căn cứ kết luận ổn định.")
        if forecasted < len(directions):
            gaps.append(f"Dự báo: chỉ có {forecasted}/{len(directions)} hướng đủ dữ liệu tạo dự báo; không điền dự báo thay cho dữ liệu thiếu.")
        if tested < len(directions):
            gaps.append(f"Kiểm chứng hồi cứu: chỉ có {tested}/{len(directions)} hướng có lần dự đoán năm đã biết và sai số; chưa xác nhận độ chính xác cho các hướng còn lại.")
    for status in dataset["source_status"]:
        if status["status"] in {"unavailable", "empty"}:
            gaps.append(f"{status['source']} / {status['direction_id']}: {status.get('reason', 'Không có kết quả')}")
    return {"status": "failed" if errors else "partial" if gaps else "passed", "errors": sorted(set(errors)), "gaps": sorted(set(gaps)),
        "checks": ["known_evidence_ids", "idea_product_direction_match", "exact_review_quotes", "task1_structure", "source_coverage", "historical_coverage"],
        "limitation": "Kiểm tra tự động về cấu trúc/nguồn; chưa chứng minh mọi diễn giải hoặc giả thuyết kinh doanh đúng."}
