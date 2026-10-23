"""Discover the actual public CSV exports and render a portable download list."""
import csv
from html import escape
from pathlib import Path
import re


CSV_NAME = re.compile(r"[a-z][a-z0-9_]*\.csv")
CSV_LABELS = {
    "keyword_product_evidence.csv": ("Từ khóa → sản phẩm → lượt mua và nhận xét", "Mỗi dòng nối một từ khóa với ASIN, nhãn mua, loại nguồn, ngày quan sát và độ phủ nhận xét."),
    "keyword_market_summary.csv": ("Độ đầy đủ của dữ liệu theo từ khóa", "Tháng nổi bật, số sản phẩm có nhãn mua, review đầy đủ và trích đoạn; giữ cả nhóm thiếu dữ liệu."),
    "amazon_purchase_evidence.csv": ("Bằng chứng lượt mua trên Amazon", "Từng nhãn mua trên trang sản phẩm hoặc kết quả tìm kiếm; nguồn và thời điểm được giữ riêng."),
    "monthly_top5.csv": ("Sản phẩm nổi bật theo tháng", "Danh sách xếp hạng trong mẫu, tháng phù hợp và căn cứ lựa chọn."),
    "products.csv": ("Danh sách sản phẩm", "Tên, ASIN, giá, thuộc tính, đánh giá tổng hợp và lượt mua Amazon hiển thị."),
    "reviews.csv": ("Nhận xét của khách hàng", "Nhận xét đầy đủ và trích đoạn có nguồn; phân biệt bằng review_text_kind, nối ASIN, giữ trống sao/ngày chưa có."),
    "trends.csv": ("Xu hướng tìm kiếm theo tháng", "Chỉ số Google Trends cho từng từ khóa, tháng và năm."),
    "trends_weekly.csv": ("Xu hướng tìm kiếm theo tuần", "Các điểm dữ liệu Google Trends theo tuần dùng để tổng hợp theo tháng."),
    "keywords.csv": ("Từ khóa nghiên cứu", "Từ khóa, nhóm sản phẩm và chỉ số so sánh theo năm."),
    "monthly_keyword_analysis.csv": ("Mùa vụ của từng từ khóa", "Tháng thường được quan tâm nhiều hơn, số năm đủ dữ liệu và mức độ phù hợp."),
    "product_month_opportunities.csv": ("Sản phẩm và tháng phù hợp", "Toàn bộ các cặp sản phẩm – tháng được phân tích trước khi chọn danh sách nổi bật."),
    "web_sources.csv": ("Trang web tham khảo", "Tiêu đề, đường dẫn và nội dung ngữ cảnh tìm được qua Tavily."),
    "keyword_sources.csv": ("Nguồn liên quan đến từ khóa", "Liên kết giữa từ khóa nghiên cứu và các trang web tham khảo."),
    "listing_evidence.csv": ("Thông tin trích từ trang sản phẩm", "Thông số, mô tả và bằng chứng dùng để ghép sản phẩm với từ khóa."),
    "product_components.csv": ("Nhóm của từng sản phẩm", "Quan hệ giữa mã ASIN và nhóm sản phẩm trong nghiên cứu."),
    "review_themes.csv": ("Chủ đề trong nhận xét", "Các nhận xét đã được phân nhóm như đóng gói, kích thước hoặc chất lượng."),
    "review_month_summary.csv": ("Độ phủ nhận xét theo tháng", "Số nhận xét thực lấy được theo ngày đăng trong các tháng nghiên cứu."),
    "monthly_actions.csv": ("Gợi ý theo từng tháng", "Các nhóm và sản phẩm cần xem xét trong từng tháng của kỳ nghiên cứu."),
    "excluded_products.csv": ("Sản phẩm đã loại", "Các sản phẩm không qua bộ lọc và lý do loại."),
}


def csv_files(output):
    output = Path(output).resolve()
    files = []
    for path in output.glob("*.csv"):
        if not CSV_NAME.fullmatch(path.name) or not path.is_file() or not path.resolve().is_relative_to(output):
            continue
        title, description = CSV_LABELS.get(path.name, (path.stem.replace("_", " "), "Bảng dữ liệu của nghiên cứu đang xem."))
        with path.open(encoding="utf-8-sig", newline="") as stream:
            rows = csv.reader(stream)
            next(rows, None)
            count = sum(1 for row in rows if row)
        files.append({"filename":path.name, "title":title, "description":description, "rows":count})
    order = {name:i for i,name in enumerate(CSV_LABELS)}
    return sorted(files, key=lambda item:(order.get(item["filename"],len(order)),item["filename"]))


def csv_downloads_html(files, expanded=False):
    if not files:
        return '<p class="muted">Chưa có file CSV để tải.</p>'
    links = []
    for file in files:
        name = escape(file["filename"], quote=True)
        links.append(f'<a class="csv-file" href="{name}" download="{name}"><span class="csv-file-info"><strong>{escape(file["title"])}</strong>'
                     f'<small>{escape(file["description"])}</small><code>{name} · {file["rows"]:,} dòng dữ liệu</code></span><span class="csv-file-action">Tải CSV ↓</span></a>')
    return (f'<details class="csv-picker"{" open" if expanded else ""}><summary><span><strong>Chọn file CSV để tải</strong><small>{len(files)} file trong nghiên cứu này</small></span>'
            '<span class="csv-picker-arrow" aria-hidden="true">⌄</span></summary><div class="csv-file-list">'+"".join(links)+"</div></details>")
