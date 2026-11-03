# Chuyển từ bản seasonal sang v2

**Cập nhật SQLite:** chạy `python run.py migrate-db` để nhập các run hiện có; server cũng nhập phần thiếu khi khởi động. Không xóa JSON/raw cũ hay đặt lại quota. Database chính là `data/market_research.sqlite3`; từ sau migration, chỉnh bản JSON xuất không thay trạng thái backend. Xem [database](database.md). Báo cáo cũ có thể dựng lại sáu phần bằng `python run.py report --run-id <id>`; không gọi thêm API nghiên cứu và không tạo năm lịch sử chưa có.

Code chạy hiện tại nằm hoàn toàn trong `src/market_research`. Đã loại bỏ `market_analysis/`, `market_radar/`, `config/` và các test/UI test gắn với bản cũ sau khi có kiểm thử thay thế.

- `study.py` cũ → `workflow/understand.py` và `workflow/discover.py`.
- Thu thập một vòng theo family → `providers/` và các stage riêng có checkpoint.
- `seasonality.py` → `forecasting/series.py` và `forecasting/assess.py`.
- Top 5 theo tháng → `analysis/`, `ranking/` và nhiều bảng có scope/rules/ties.
- Báo cáo phụ thuộc đoạn LLM → `reporting/` dựng Python; LLM commentary tùy chọn.
- Dashboard cũ → `ui/`, cùng gọi `pipeline.execute()` với CLI.

`data/seasonal-gifts-us/` chỉ giữ phần cần cho offline replay: dataset sản phẩm/review, chỉ mục Trends và raw nguồn được tham chiếu. Báo cáo, CSV, dashboard, kết quả LLM cũ và metadata không dùng đã được xóa. `examples/archive-plan.json` là phạm vi gốc của bộ đó; không phải cấu hình cứng của workflow live. Xem `data/seasonal-gifts-us/README.md` để biết lý do giữ từng phần.

`market-research-crew/` đã được xóa theo yêu cầu dọn dự án sau khi tham khảo; code v2 không phụ thuộc repo này. Lần dọn hiện tại giữ `venv/` để có thể dùng lại môi trường Python; nó không phải code ứng dụng cũ. `.artifact-runtime/pdf-deps/` được giữ vì đang hỗ trợ xuất PDF. Kết quả test tạm, cache Python/pytest và ảnh kiểm tra PDF trong `tmp/` đã được dọn; bộ test nguồn trong `tests/` vẫn được giữ để bảo trì.

Theo yêu cầu dọn phần không dùng, đã xóa `output/`, `latex.md`, tài liệu giải thích pipeline cũ, ảnh dashboard cũ trong `docs/images/` và thư mục job cũ trống. Các tài liệu đang dùng gồm README, doc.md, hướng dẫn v2, tài liệu trong docs và đề gốc TASK-1.md.

Không sửa hoặc in giá trị `api/.env`; v2 vẫn đọc file này để tương thích và hỗ trợ thêm `.env` ở thư mục gốc. Các run/báo cáo v2 trong `data/runs/`, `outputs/` và báo cáo mẫu trong `examples/reports/` được giữ để ứng dụng mở lại và đối chiếu.
