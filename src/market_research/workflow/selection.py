"""Bound product-search queries without claiming an unsupported Trends ranking."""
from ..common import identity
from .trend_queries import product_context, candidate_level, research_focus


def verified_months(row):
    """Month-specific proof must not expand to every requested month."""
    declared = row.get("qualifying_months", row.get("verified_months", []))
    if "monthly_metrics" in row:
        measured = {metric["month"] for metric in row.get("monthly_metrics", [])
                    if metric.get("status") == "available" and metric.get("rank") is not None}
        return sorted(measured & set(declared) if "qualifying_months" in row else measured)
    return sorted({month for month in declared if type(month) is int and 1 <= month <= 12})


def selected_month_reason(metric):
    months = verified_months(metric)
    year = " năm " + str(metric["analysis_year"]) if metric.get("analysis_year") else ""
    if not months:
        if "monthly_metrics" in metric:
            return "Chưa có tháng đủ tín hiệu của đúng truy vấn" + year + "; mẫu chưa được xác minh bằng Trends."
        return "Quan sát trong kỳ đã chọn" + year + "; lượt lưu chưa ghi riêng tháng đủ tín hiệu."
    reason = "Đủ tín hiệu tháng " + ", ".join(map(str, months)) + year
    if metric.get("peak_month") in months:
        reason += "; mạnh nhất tháng " + str(metric["peak_month"])
    return reason + ". Chỉ các tháng này hỗ trợ lựa chọn mẫu; không suy ra cả kỳ đều có nhu cầu."


def ranked(config, discovery, screening, groups):
    metrics = {}
    by_id = {keyword["id"]: keyword for keyword in discovery["keywords"]}
    for original in screening["rows"]:
        row = dict(original)
        from .design_content import design_metadata
        keyword_row = by_id[row["keyword_id"]]
        row.update(design_metadata(keyword_row["text"], config))
        if keyword_row.get("source_design"):
            row["source_design"] = keyword_row["source_design"]
        expected = " ".join(by_id[row["keyword_id"]]["text"].casefold().split())
        measured = " ".join((row.get("measurement_query") or expected).casefold().split())
        exact = measured == expected and row.get("measurement_scope", "exact_keyword") == "exact_keyword"
        context_only = product_context(by_id[row["keyword_id"]]["text"], config)
        row["exact_design_measured"] = exact and not context_only and row.get("rank") is not None
        if not exact:
            row.update(proxy_rank=row.get("rank"), proxy_score=row.get("score"), rank=None, score=None,
                reason="Phép đo nhóm hàng rộng chưa xác minh mẫu sản phẩm, định dạng, hình dạng hoặc chủ đề cụ thể; cần đo đúng keyword trước khi xếp hạng mẫu.")
        if context_only:
            row.update(context_rank=row.get("rank"), rank=None, score=None, product_context=True,
                reason="Keyword chỉ mô tả nhóm hàng; không đưa vào Top khi yêu cầu mẫu hoặc chủ đề thiết kế cụ thể.")
        if row.get("selection_basis") == "selected_month_observations" and "monthly_metrics" in row and not verified_months(row):
            row.update(rank=None, score=None, exact_design_measured=False,
                       reason="Chưa có tháng nào đủ tín hiệu của đúng truy vấn; không dùng phép đo nhóm hàng thay cho mẫu.")
        metrics[row["keyword_id"]] = row
    ordered = sorted(discovery["keywords"], key=lambda k: (metrics[k["id"]]["rank"] is None, metrics[k["id"]]["rank"] or 0))
    chosen, chosen_queries, directions, rows = {}, {}, [], []
    maximum = config["limits"]["top_keywords"]
    require_measured = config["sources"]["trends"] and config.get("trends", {}).get("required", False)
    niches = {n["id"]: n for n in config["niches"]}
    for keyword in ordered:
        metric = metrics[keyword["id"]]
        query = " ".join(keyword["text"].casefold().split())
        if query not in chosen and len(chosen) < maximum and not metric.get("product_context") and (not require_measured or metric["rank"] is not None):
            chosen[query] = len(chosen) + 1
            chosen_queries[query] = keyword["text"]
        included = query in chosen
        did = identity("D", keyword["niche_id"], keyword["id"])
        rows.append({**metric, "direction_id": did, "selected": included, "search_order": chosen.get(query),
                     "reason": metric.get("reason", "Ưu tiên tháng bán theo lịch sử đã đo") if included and metric.get("selection_basis") == "historical_selling_months" else "Ưu tiên theo Trends trong tập ứng viên" if included and metric["rank"] is not None else "Chọn bổ sung chưa xác minh Trends" if included else "Thiếu phép đo Trends; không tự đưa sang tìm mẫu" if require_measured and metric["rank"] is None else "Ngoài Top N"})
        if included and metric.get("selection_basis") == "selected_month_observations" and metric.get("rank") is not None:
            rows[-1]["reason"] = selected_month_reason(metric)
        if metric.get("product_context"):
            rows[-1]["reason"] = metric["reason"]
        if included:
            group = next((g for g in groups if g["niche_id"] == keyword["niche_id"] and keyword["id"] in g["keyword_ids"]), {})
            directions.append({"id": did, "niche_id": keyword["niche_id"], "name": keyword["text"], "group_name": group.get("name"),
                "grouping_method": group.get("grouping_method", "ungrouped"),
                "keyword_id": keyword["id"], "keyword": keyword["text"], "keyword_ids": [keyword["id"]], "search_query": chosen_queries[query],
                "measurement_query": metric.get("measurement_query") or keyword["text"], "measurement_scope": metric.get("measurement_scope", "exact_keyword"),
                "candidate_level": keyword.get("candidate_level") or candidate_level(keyword["text"], config),
                "research_focus": research_focus(config)["level"],
                **{field: metric[field] for field in ("content_focus", "design_subject_terms", "design_content_status", "source_design") if field in metric},
                **{field: metric.get(field, screening.get(field)) for field in ("analysis_year", "screening_scope", "selection_basis", "selection_months", "analysis_windows", "analysis_observations", "observed_days", "monthly_metrics", "qualifying_months", "missing_months", "peak_month", "peak_relative_interest", "aggregation")
                   if field in metric or field in screening},
                "verified_months": verified_months(metric),
                "customer_hypothesis": niches[keyword["niche_id"]].get("customer_hypothesis"),
                "evidence_ids": sorted(set(keyword["evidence_ids"] + metric["evidence_ids"]))})
    verified = len({r["keyword"].casefold() for r in rows if r["selected"] and r.get("exact_design_measured")})
    return {"directions": directions, "rows": rows, "requested": maximum, "available_keywords": len({(r.get("measurement_query") or r["keyword"]).casefold() for r in metrics.values()}),
        "original_candidates": len(discovery["keywords"]), "selected_search_queries": len(set(chosen_queries.values())),
        "selected_keywords": len(chosen), "trends_verified_keywords": verified, "method": screening["method"],
        "is_trends_hot_ranking": verified == len(chosen) and verified > 0, "selection_basis": screening.get("selection_basis", "recent_interest"),
        "requested_months": list(screening.get("selection_months") or config.get("selling_months") or []),
        "verified_months": sorted({month for row in rows if row["selected"] for month in verified_months(row)}),
        "aggregation": screening.get("aggregation"),
        "note": screening["note"] + f" Đã chọn {verified} keyword có phép đo và {len(chosen)-verified} keyword bổ sung chưa xác minh Trends." + (" Chế độ bắt buộc Trends: chỉ tìm mẫu cho keyword có phép đo; có thể ít hơn Top N yêu cầu." if require_measured else "")}


def select(config, balanced_directions):
    requested = config["limits"].get("top_keywords")
    queries = {}
    for direction in balanced_directions:
        query = " ".join(direction["search_query"].casefold().split())
        if query not in queries:
            queries[query] = direction["search_query"]
    chosen = list(queries)[:requested] if requested is not None else list(queries)
    positions = {query: index + 1 for index, query in enumerate(chosen)}
    directions, rows = [], []
    for direction in balanced_directions:
        query = " ".join(direction["search_query"].casefold().split())
        included = query in positions
        if included:
            directions.append(direction)
        rows.append({"direction_id": direction["id"], "niche_id": direction["niche_id"], "keyword_id": direction["keyword_id"],
                     "keyword": direction["keyword"], "selected": included, "search_order": positions.get(query),
                     "reason": "Chọn sau gom nhóm, luân phiên niche" if included else "Ngoài giới hạn keyword tìm sản phẩm"})
    return {"directions": directions, "rows": rows, "requested": requested, "available_keywords": len(queries), "selected_keywords": len(chosen),
            "method": "niche_balanced_query_cap_v1", "is_trends_hot_ranking": False,
            "note": "Giới hạn keyword đại diện sau gom nhóm, phân bổ luân phiên niche; chưa phải Top độ hot trên Trends. Các niche cùng truy vấn được giữ chung, không tính thêm keyword."}
