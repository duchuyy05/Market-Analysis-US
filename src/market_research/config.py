"""One validated input contract for CLI, UI and resume."""
from copy import deepcopy
from datetime import date
from pathlib import Path
import json
import math

from .common import today

DEFAULT_LIMITS = {
    "top_keywords": 10,
    "candidate_keywords": 64, "free_trends_requests": 40, "product_details": 3, "shopping_keywords": 2,
    "serpapi_requests": 20, "tavily_requests": 3, "exa_requests": 4, "llm_requests": 8,
    "monthly_keywords": 64, "monthly_rows": 10,
    "trends_serpapi_requests": 8, "serpapi_product_reserve": 10, "trends_related_requests": 0,
    "keywords_per_niche": 40, "directions_per_niche": 4, "related_seeds_per_niche": 2,
    "products_per_direction": 8, "enrich_per_niche": 4, "reviews_per_product": 20,
    "ranking_rows": 10, "timeout_seconds": 45, "retry_attempts": 1,
    "max_run_seconds": 1800, "max_output_tokens": 5000,
    "scraper_requests": 30,
}


def load_config(path):
    path = Path(path)
    body = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() in {".yaml", ".yml"}:
        import yaml
        return validate_config(yaml.safe_load(body))
    return validate_config(json.loads(body))


def validate_config(value):
    if not isinstance(value, dict):
        raise ValueError("Cấu hình phải là object JSON/YAML")
    c = deepcopy(value)
    def reject_secrets(item):
        if isinstance(item, dict):
            for key, child in item.items():
                if str(key).lower() in {"api_key", "serpapi_api_key", "tavily_api_key", "exa_api_key", "x-api-key", "openrouter_api_key", "authorization", "secret", "access_token"}:
                    raise ValueError("API key/secret phải nằm trong .env, không nằm trong cấu hình nghiên cứu")
                reject_secrets(child)
        elif isinstance(item, list):
            for child in item:
                reject_secrets(child)
    reject_secrets(c)
    c.setdefault("brief", "")
    c.setdefault("category", "")
    c.setdefault("niches", [])
    if not isinstance(c["brief"], str) or len(c["brief"]) > 12000:
        raise ValueError("Mô tả phải là văn bản, tối đa 12.000 ký tự")
    if not c["brief"].strip() and not c["niches"]:
        raise ValueError("Nhập mô tả nghiên cứu hoặc danh sách niche")
    c.setdefault("mode", "live")
    if c["mode"] not in {"live", "offline"}:
        raise ValueError("mode chỉ nhận live hoặc offline")
    from .business.domain import CATEGORY_LABELS
    business = c.setdefault("business", {"profile": "general" if c["mode"] == "offline" else "custom_manufacturing"})
    if not isinstance(business, dict) or set(business) - {"profile", "categories"} or business.get("profile", "custom_manufacturing") not in ("general", "custom_manufacturing"):
        raise ValueError("business cần profile general/custom_manufacturing và danh sách categories")
    profile = business.get("profile", "custom_manufacturing")
    categories = business.get("categories", list(CATEGORY_LABELS) if profile == "custom_manufacturing" else [])
    if not isinstance(categories, list) or any(not isinstance(value, str) or value not in CATEGORY_LABELS for value in categories) or (profile == "custom_manufacturing" and not categories):
        raise ValueError("Chọn ít nhất một nhóm hàng gia công hợp lệ")
    c["business"] = {"profile": profile, "categories": list(dict.fromkeys(categories))}
    c.setdefault("market", "US")
    if c["market"] != "US":
        raise ValueError("MVP hỗ trợ thị trường US; không tự đổi thị trường đã nhập")
    c.setdefault("query_language", "en")
    c.setdefault("report_language", "vi")
    if c["query_language"] != "en" or c["report_language"] != "vi":
        raise ValueError("MVP dùng truy vấn tiếng Anh và báo cáo tiếng Việt")
    c.setdefault("as_of_date", today().isoformat())
    cutoff = date.fromisoformat(c["as_of_date"])
    if cutoff > today():
        raise ValueError("Ngày chốt không được nằm trong tương lai")
    from .forecasting.periods import validate_periods
    c["comparison_periods"] = validate_periods(c.get("comparison_periods", []), c["as_of_date"])
    c.setdefault("history_years", [2023, 2024, 2025])
    years = c["history_years"]
    if not isinstance(years, list) or not 2 <= len(years) <= 6 or any(type(y) is not int or not 2004 <= y < cutoff.year for y in years):
        raise ValueError("Cần 2–6 năm lịch sử đã hoàn tất, trước năm chốt")
    c["history_years"] = sorted(set(years))
    if len(c["history_years"]) < 2:
        raise ValueError("Cần ít nhất hai năm lịch sử khác nhau để đối chiếu")
    c.setdefault("target_year", cutoff.year)
    if type(c["target_year"]) is not int or c["target_year"] <= max(years):
        raise ValueError("Năm dự báo phải sau các năm lịch sử")
    # None lets the brief interpreter supply the selling window.
    c.setdefault("selling_months", None)
    if c["selling_months"] is not None:
        if not isinstance(c["selling_months"], list) or not c["selling_months"] or any(type(m) is not int or not 1 <= m <= 12 for m in c["selling_months"]):
            raise ValueError("Tháng bán phải thuộc 1–12")
        c["selling_months"] = sorted(set(c["selling_months"]))
    c.setdefault("price_range", None)
    if c["price_range"] is not None:
        prices = c["price_range"]
        if not isinstance(prices, list) or len(prices) != 2 or any(type(p) not in {int, float} or not math.isfinite(p) or p < 0 for p in prices) or prices[0] > prices[1]:
            raise ValueError("price_range cần [giá thấp, giá cao] bằng USD")
    c.setdefault("required_features", [])
    c.setdefault("excluded_features", [])
    c.setdefault("preferences", [])
    for field in ("required_features", "excluded_features", "preferences"):
        if not isinstance(c[field], list) or any(not isinstance(x, str) or len(x) > 200 for x in c[field]):
            raise ValueError(f"{field} phải là danh sách cụm từ")
    c.setdefault("preparation_days", None)
    if c["preparation_days"] is not None and (type(c["preparation_days"]) is not int or not 0 <= c["preparation_days"] <= 730):
        raise ValueError("preparation_days cần số ngày 0–730")
    if not isinstance(c["niches"], list) or len(c["niches"]) > 5:
        raise ValueError("Tối đa 5 niche")
    for n in c["niches"]:
        if not isinstance(n, dict) or not isinstance(n.get("name"), str) or not n["name"].strip():
            raise ValueError("Mỗi niche cần name")
        if not isinstance(n.get("seeds", []), list) or any(not isinstance(k, str) or len(k) > 200 for k in n.get("seeds", [])):
            raise ValueError("seeds phải là danh sách keyword")
    supplied = c.get("limits", {})
    if not isinstance(supplied, dict) or set(supplied) - set(DEFAULT_LIMITS):
        raise ValueError("Tên giới hạn không hợp lệ")
    c["limits"] = {**DEFAULT_LIMITS, **supplied}
    for k, v in c["limits"].items():
        maximum = 100000 if k in {"max_run_seconds", "max_output_tokens"} else 1000
        if type(v) is not int or not 0 <= v <= maximum:
            raise ValueError(f"limits.{k} phải là số nguyên 0–{maximum}")
    if c["limits"]["directions_per_niche"] < 1 or c["limits"]["keywords_per_niche"] < 1 or c["limits"]["timeout_seconds"] < 1:
        raise ValueError("Số keyword/hướng và timeout phải lớn hơn 0")
    if not 1 <= c["limits"]["top_keywords"] <= 100:
        raise ValueError("Top keyword phải từ 1 đến 100")
    c.setdefault("sources", {})
    if not isinstance(c["sources"], dict) or set(c["sources"]) - {"trends", "amazon", "shopping", "web"} or any(type(v) is not bool for v in c["sources"].values()):
        raise ValueError("sources cần các cờ boolean hợp lệ")
    c["sources"] = {"trends": True, "amazon": True, "shopping": False, "web": True, **c["sources"]}
    collection = c.setdefault("product_collection", {})
    if not isinstance(collection, dict) or set(collection) - {"mode", "sources", "cache_hours", "detail_limit"}:
        raise ValueError("product_collection cần mode, sources, cache_hours, detail_limit")
    c["product_collection"] = {"mode": "api", "sources": ["amazon", "etsy", "reddit"], "cache_hours": 24, "detail_limit": 2, **collection}
    collection = c["product_collection"]
    if collection["mode"] not in ("scraper", "hybrid", "api") or not isinstance(collection["sources"], list) or any(s not in ("amazon", "etsy", "reddit") for s in collection["sources"]):
        raise ValueError("Chọn chế độ và nguồn lấy sản phẩm hợp lệ")
    collection["sources"]=list(dict.fromkeys(collection["sources"]))
    if collection["mode"]=="scraper":
        # The total/Trends caps are unchanged; there is no product API budget
        # to reserve when only direct collectors may retrieve products.
        c["limits"]["serpapi_product_reserve"]=0
    for field, maximum in (("cache_hours",168),("detail_limit",20)):
        if type(collection[field]) is not int or not 0 <= collection[field] <= maximum:
            raise ValueError("product_collection."+field+" ngoài giới hạn")
    from .providers.web import SOURCE_DOMAINS
    discovery = c.setdefault("discovery", {})
    if not isinstance(discovery, dict) or set(discovery) - {"enabled", "sites", "focus", "web_provider"}:
        raise ValueError("discovery chỉ nhận enabled, sites, focus và web_provider")
    c["discovery"] = {"enabled": True, "sites": list(SOURCE_DOMAINS), "focus": "auto", "web_provider": "auto", **discovery}
    if c["discovery"]["web_provider"] not in ("auto", "tavily", "exa", "combined"):
        raise ValueError("discovery.web_provider cần auto, tavily, exa hoặc combined")
    if c["discovery"]["focus"] not in ("auto", "designs", "models"):
        raise ValueError("discovery.focus cần auto, designs hoặc models")
    if type(c["discovery"]["enabled"]) is not bool or not isinstance(c["discovery"]["sites"], list) or any(not isinstance(s, str) or s not in SOURCE_DOMAINS for s in c["discovery"]["sites"]):
        raise ValueError("Nguồn web khám phá không hợp lệ")
    c["discovery"]["sites"] = list(dict.fromkeys(c["discovery"]["sites"]))
    trend_config = c.setdefault("trends", {})
    if not isinstance(trend_config, dict):
        raise ValueError("trends phải là một object cấu hình, không phải chuỗi hoặc danh sách")
    unsupported = set(trend_config) - {"provider", "anchor", "screen_days", "cache_hours", "required", "monthly_rankings", "history_scope", "history_months", "analysis_year"}
    if unsupported:
        raise ValueError("Cấu hình Trends có trường không hỗ trợ: " + ", ".join(sorted(map(str, unsupported))) + ". Kiểm tra tên trường và khởi động lại server sau khi cập nhật code.")
    c["trends"] = {"provider": "auto", "anchor": "gift basket", "screen_days": 90, "cache_hours": 24, "required": True, "monthly_rankings": False, "history_scope": "full", "history_months": [10, 11, 12], "analysis_year": None, **trend_config}
    t = c["trends"]
    if not isinstance(t["provider"], str) or t["provider"] not in {"auto", "free", "serpapi"} or not isinstance(t["anchor"], str) or not 2 <= len(t["anchor"].strip()) <= 100 or not t["anchor"].isascii():
        raise ValueError("Trends cần provider auto/free/serpapi và anchor tiếng Anh")
    if type(t["required"]) is not bool:
        raise ValueError("trends.required phải là boolean")
    if t["analysis_year"] is not None and (type(t["analysis_year"]) is not int or not 2004 <= t["analysis_year"] <= cutoff.year):
        raise ValueError("Năm phân tích Trends phải từ 2004 đến năm của ngày chốt, hoặc null để dùng kỳ quan sát gần nhất")
    if type(t["monthly_rankings"]) is not bool or not 1 <= c["limits"]["monthly_keywords"] <= 100 or not 1 <= c["limits"]["monthly_rows"] <= 50:
        raise ValueError("Xếp hạng tháng cần cờ boolean, 1–100 keyword và 1–50 dòng/tháng")
    if t["history_scope"] not in ("full", "seasonal") or not isinstance(t["history_months"], list) or not t["history_months"] or any(type(month) is not int or not 1 <= month <= 12 for month in t["history_months"]):
        raise ValueError("Phạm vi lịch sử cần full/seasonal và history_months thuộc 1–12")
    t["history_months"] = sorted(set(t["history_months"]))
    if t["history_scope"] == "seasonal":
        if c["mode"] == "offline":
            raise ValueError("Bộ offline chỉ phát lại dữ liệu đã lưu; dùng live để chọn phạm vi thu thập theo mùa")
        t["monthly_rankings"] = True
        if c["selling_months"] and set(c["selling_months"]) - set(t["history_months"]):
            raise ValueError("Tháng bán phải nằm trong các tháng lịch sử đã chọn khi chỉ thu thập theo mùa")
        from .forecasting.periods import month_index
        for period in c["comparison_periods"]:
            for value in range(month_index(period["start"]), month_index(period["end"]) + 1):
                year, offset = divmod(value, 12)
                if year not in c["history_years"] or offset + 1 not in t["history_months"]:
                    raise ValueError("Khoảng so sánh vượt các năm/tháng được phép thu thập theo mùa")
    t["anchor"] = " ".join(t["anchor"].split())
    if type(t["screen_days"]) is not int or not 60 <= t["screen_days"] <= 365 or type(t["cache_hours"]) is not int or not 0 <= t["cache_hours"] <= 168:
        raise ValueError("Cửa sổ Trends 60–365 ngày; cache 0–168 giờ")
    if not 1 <= c["limits"]["candidate_keywords"] <= 100:
        raise ValueError("candidate_keywords phải từ 1 đến 100")
    c.setdefault("llm", {"enabled": True, "commentary": False, "model": None})
    if not isinstance(c["llm"], dict):
        raise ValueError("llm phải là object")
    c["llm"] = {"enabled": True, "commentary": False, "model": None, **c["llm"]}
    if any(type(c["llm"][k]) is not bool for k in ("enabled", "commentary")) or (c["llm"]["model"] is not None and not isinstance(c["llm"]["model"], str)):
        raise ValueError("Cấu hình LLM cần cờ boolean và model dạng chuỗi")
    c["schema_version"] = 2
    c.setdefault("assumptions", [])
    if not isinstance(c["assumptions"], list) or any(not isinstance(a, str) for a in c["assumptions"]):
        raise ValueError("assumptions phải là danh sách văn bản")
    return c
