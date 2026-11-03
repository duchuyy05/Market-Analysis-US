"""Saved items, editable report copies and a sortable, source-backed product grid."""
import csv
import io
import json
import math
from pathlib import Path
import re
import threading
import secrets

from ..common import now, read_json, safe_url, write_json
from ..reporting.document import Document, link
from ..storage.database import Database


ID = re.compile(r"[a-zA-Z0-9_-]{1,100}")
SORT_FIELDS = {"title", "price", "rating", "review_count", "observed_at"}


def sort_rules(query):
    if "sorts" in query:
        try:
            rules = json.loads(query["sorts"])
        except (ValueError, TypeError):
            raise ValueError("Danh sách tiêu chí sắp xếp không hợp lệ") from None
    else:
        rules = [{"field": query.get("sort", "observed_at"), "order": query.get("order", "desc")}]
    if not isinstance(rules, list) or not 1 <= len(rules) <= len(SORT_FIELDS):
        raise ValueError("Chọn từ 1 đến 5 tiêu chí sắp xếp")
    used = set()
    for rule in rules:
        if not isinstance(rule, dict) or not isinstance(rule.get("field"), str) or rule["field"] not in SORT_FIELDS or rule.get("order") not in {"asc", "desc"}:
            raise ValueError("Cột hoặc thứ tự sắp xếp không hợp lệ")
        if rule["field"] in used:
            raise ValueError("Mỗi cột chỉ được chọn một lần trong thứ tự ưu tiên")
        used.add(rule["field"])
    return rules


def run_path(root, run_id):
    if not isinstance(run_id, str) or not ID.fullmatch(run_id):
        raise ValueError("Mã nghiên cứu không hợp lệ")
    path = (Path(root) / "data/runs" / run_id).resolve()
    if not path.is_relative_to((Path(root) / "data/runs").resolve()) or not ((path / "manifest.json").is_file() or Database(root).get_manifest(run_id) is not None):
        raise ValueError("Không có lượt nghiên cứu này")
    return path


class Workspace:
    def __init__(self, root):
        self.root = Path(root)
        self.path = self.root / "data/workspace/state.json"
        self.guard = threading.RLock()
        self.db = Database(self.root)

    def state(self):
        value = self.db.get_workspace()
        return value if value is not None else read_json(self.path, {"saved_runs": [], "saved_products": [], "edited": {}})

    def save_item(self, body):
        run_id = body.get("run_id")
        run_path(self.root, run_id)
        kind, saved = body.get("kind"), body.get("saved")
        if kind not in {"run", "product"} or type(saved) is not bool:
            raise ValueError("Chọn loại mục và trạng thái lưu hợp lệ")
        key = run_id
        if kind == "product":
            product_id = body.get("product_id")
            if not any(p["product_id"] == product_id for p in self._products(run_id)):
                raise ValueError("Không có sản phẩm trong nghiên cứu này")
            key += ":" + product_id
        with self.guard:
            state = self.state()
            field = "saved_runs" if kind == "run" else "saved_products"
            values = set(state[field])
            values.add(key) if saved else values.discard(key)
            state[field] = sorted(values)
            self.db.save_workspace(state)
            write_json(self.path, state)
        return {"saved": saved, "key": key}

    def _products(self, run_id):
        path = run_path(self.root, run_id)
        dataset = self.db.get_dataset(run_id)
        if dataset is None:
            dataset = read_json(path / "dataset.json")
        if dataset is None:
            dataset = self.db.get_checkpoint(run_id, "enrich") or self.db.get_checkpoint(run_id, "search") or read_json(path / "checkpoints/enrich.json") or read_json(path / "checkpoints/search.json", {})
        return dataset.get("products", [])

    def products(self, query):
        state = self.state()
        selected = query.get("run_id", "all")
        run_ids = {row["run_id"] for row in self.db.list_runs()} | {p.parent.name for p in (self.root / "data/runs").glob("*/manifest.json")}
        runs = [selected] if selected != "all" else sorted(run_ids, reverse=True)
        search = query.get("q", "").casefold().strip()
        source = query.get("source", "all")
        saved_only = query.get("saved", "0") == "1"
        rules = sort_rules(query)
        if source not in {"all", "amazon", "shopping", "public_web"}:
            raise ValueError("Nguồn sản phẩm không hợp lệ")
        bounds = []
        for field in ("min_price", "max_price"):
            value = query.get(field, "")
            number = float(value) if value != "" else None
            if number is not None and (not math.isfinite(number) or number < 0):
                raise ValueError("Giá lọc phải là số không âm")
            bounds.append(number)
        if all(n is not None for n in bounds) and bounds[0] > bounds[1]:
            raise ValueError("Giá thấp không được lớn hơn giá cao")
        rows = []
        for rid in runs:
            path = run_path(self.root, rid)
            manifest = self.db.get_manifest(rid)
            if manifest is None:
                manifest = read_json(path / "manifest.json", {})
            for product in self._products(rid):
                row = {k: product.get(k) for k in (
                    "product_id", "title", "asin", "merchant", "source", "price", "currency", "rating", "review_count",
                    "purchase_badge", "observed_at", "url", "thumbnail", "detail_status", "evidence_ids",
                )}
                row.update(run_id=rid, research=state["edited"].get(rid, {}).get("title") or manifest.get("summary", {}).get("category") or rid,
                           mode=manifest.get("mode"), saved=rid + ":" + row["product_id"] in state["saved_products"])
                if source != "all" and row["source"] != source or saved_only and not row["saved"]:
                    continue
                if search and search not in " ".join(str(row.get(k) or "") for k in ("title", "asin", "merchant", "research")).casefold():
                    continue
                price = row.get("price")
                if any(n is not None for n in bounds):
                    if price is None or row["currency"] != "USD" or bounds[0] is not None and price < bounds[0] or bounds[1] is not None and price > bounds[1]:
                        continue
                rows.append(row)
        # Stable sorts from the last priority to the first implement ordered
        # tie-breaks. Unknowns stay last inside each earlier-priority group.
        for rule in reversed(rules):
            field = rule["field"]
            known = [r for r in rows if r.get(field) is not None]
            unknown = [r for r in rows if r.get(field) is None]
            known.sort(key=lambda r: r[field].casefold() if isinstance(r[field], str) else r[field], reverse=rule["order"] == "desc")
            if field == "price":
                known.sort(key=lambda r: r.get("currency") or "~")
            rows = known + unknown
        return rows

    def editor(self, run_id):
        run_path(self.root, run_id)
        base = self.root / "outputs" / run_id
        original = base / "report.md"
        if not original.is_file():
            raise ValueError("Chưa có báo cáo để biên tập; hãy hoàn tất nghiên cứu trước")
        meta = self.state()["edited"].get(run_id, {})
        edited = base / "report-edited.md"
        return {"run_id": run_id, "title": meta.get("title", "Báo cáo nghiên cứu"), "content": (edited if edited.is_file() else original).read_text(encoding="utf-8-sig"),
                "updated_at": meta.get("updated_at"), "edited": edited.is_file()}

    def save_editor(self, run_id, body):
        path = run_path(self.root, run_id)
        self.editor(run_id)
        title, content = body.get("title"), body.get("content")
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 160 or not isinstance(content, str) or len(content) > 250000:
            raise ValueError("Tiêu đề cần 1–160 ký tự; nội dung tối đa 250.000 ký tự")
        stamp = now()
        record = {"title": title.strip(), "content": content, "updated_at": stamp}
        with self.guard:
            # Retain every explicit save; generated report.md remains untouched.
            write_json(path / "edits" / (stamp.replace(":", "").replace(".", "") + "-" + secrets.token_hex(6) + ".json"), record)
            base = self.root / "outputs" / run_id
            (base / "report-edited.md").write_text(content, encoding="utf-8")
            (base / "report-edited.html").write_text(render_edit(title.strip(), content), encoding="utf-8")
            state = self.state()
            state["edited"][run_id] = {"title": title.strip(), "updated_at": stamp}
            state["saved_runs"] = sorted(set(state["saved_runs"]) | {run_id})
            self.db.save_workspace(state)
            write_json(self.path, state)
        return {"saved": True, "updated_at": stamp, "url": f"/outputs/{run_id}/report-edited.html"}


def render_edit(title, content):
    """Render a safe Markdown subset, including generated report tables."""
    doc = Document()
    doc.paragraph("Bản biên tập của người dùng · Số liệu sửa tay chưa được kiểm tra lại · Báo cáo gốc được giữ riêng", "warning")
    lines = content.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading:
            doc.heading(heading[2], len(heading[1]))
        elif line.startswith("|") and index + 1 < len(lines) and re.fullmatch(r"[| :\-]+", lines[index + 1]):
            def cells(text):
                return [re.sub(r"\\\|", "|", cell.strip()) for cell in re.split(r"(?<!\\)\|", text.strip().strip("|"))]
            headers = cells(line)
            index += 2
            rows = []
            while index < len(lines) and lines[index].startswith("|"):
                values = []
                for cell in cells(lines[index]):
                    target = re.fullmatch(r"\[([^]]+)\]\(<?([^>)]+)>?\)", cell)
                    values.append(link(target[1], target[2]) if target and safe_url(target[2]) else cell)
                rows.append((values + [""] * len(headers))[:len(headers)])
                index += 1
            doc.table(headers, rows)
            continue
        elif line.strip():
            doc.paragraph(line)
        index += 1
    return doc.render(title, "Bản lưu biên tập · " + now()[:10])[1]


def product_csv(rows):
    columns = [
        ("title", "Sản phẩm"), ("price", "Giá"), ("currency", "Tiền tệ"), ("rating", "Điểm sao"), ("review_count", "Lượt đánh giá"),
        ("purchase_badge", "Nhãn mua"), ("merchant", "Nhà bán"), ("source", "Nguồn"), ("asin", "ASIN"),
        ("observed_at", "Ngày quan sát"), ("research", "Nghiên cứu"), ("mode", "Chế độ"), ("url", "Link sản phẩm"), ("evidence_ids", "Mã bằng chứng"),
    ]
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow([label for _, label in columns])
    for row in rows:
        values = []
        for key, _ in columns:
            value = row.get(key)
            if isinstance(value, list):
                value = "; ".join(map(str, value))
            if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r", "\n")):
                value = "'" + value
            values.append("" if value is None else value)
        writer.writerow(values)
    return output.getvalue().encode("utf-8-sig")
