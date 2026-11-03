# Lưu trữ bằng SQLite

Cập nhật 29/10/2026. Backend dùng **SQLite làm nơi lưu có cấu trúc chính**, tại:

```text
data/market_research.sqlite3
```

SQLite có sẵn trong Python, không cần cài PostgreSQL/MySQL hay chạy server database riêng. Kết nối dùng transaction, foreign key, WAL và timeout chờ ghi để phục vụ luồng nền cùng các lần frontend đọc tiến trình.

## Dữ liệu được lưu ở đâu?

| Bảng SQLite | Nội dung |
|---|---|
| `runs`, `stages` | Input đã khóa, trạng thái run và từng bước |
| `api_calls` | Từng lần gọi nguồn, mục đích, trạng thái, token/cost nếu nguồn trả |
| `checkpoints`, `datasets` | Kết quả khôi phục từng bước và bộ dữ liệu tổng hợp |
| `evidence`, `events` | Mã nguồn/link/ngày lấy và nhật ký xử lý đã che key |
| `niches`, `directions`, `keywords`, `keyword_screening` | Phạm vi nghiên cứu, keyword, truy vấn thực sự đo, chỉ số và hạng |
| `product_snapshots`, `offer_snapshots` | Bản quan sát sản phẩm/giá theo từng run và thời điểm lấy thật |
| `reviews` | Comment gắn với product ID/ASIN; không tự điền sao hoặc ngày thiếu |
| `trend_observations`, `forecast_values` | Quan tâm theo năm/tháng, dự báo và trạng thái quan sát |
| `forecast_backtests` | Các fold kiểm chứng, năm huấn luyện/test, MAE và mốc cơ sở |
| `workspace_state` | Nghiên cứu/sản phẩm đã lưu và thông tin bản biên tập |
| `imports` | Dấu vết nhập dữ liệu legacy |

Các bảng có cột có kiểu để truy vấn/lọc, đồng thời giữ payload JSON trong database để không làm mất trường nguồn hoặc dữ liệu của các phiên bản trước. Database chứa JSON payload vẫn là database; ứng dụng đọc SQLite trước và không phụ thuộc CSV để chạy.

`forecast_backtests` lưu cả kiểm chứng một năm cũ (`fold_id = summary` hoặc chỉ số fold) và kiểm chứng cuốn chiếu mới (`validation-summary`, `validation-0`, `validation-1`…). MAE và MAE mốc cơ sở được tách thành cột, còn WAPE, số mẫu, kết quả từng tháng và phương pháp kiểm chứng được giữ đầy đủ trong `payload_json`.

## Vì sao vẫn còn `data/runs/` và `outputs/`?

- `data/runs/<id>/raw/` giữ bản phản hồi gốc/cache để kiểm tra nguồn và tránh gọi lại API. Ảnh và PDF cũng phù hợp lưu như file kèm theo database.
- Manifest/checkpoint/dataset JSON và `events.jsonl` vẫn được ghi như bản tương thích/xuất để người dùng kiểm tra bằng công cụ thông thường. **Khi DB đã có bản ghi, đọc backend ưu tiên DB**; sửa tay JSON không tự sửa dữ liệu DB.
- `outputs/<id>/` tiếp tục chứa báo cáo HTML/Markdown/PDF, CSV/JSON dành cho xem, tải và chia sẻ. Đây là kết quả xuất, không phải database chính.
- Không xóa raw hay bản xuất cũ khi nhập database. Việc chuyển storage không tiêu quota API.

## Chuyển dữ liệu cũ

`Database.migrate_legacy()` đọc các thư mục `data/runs/*`, nhập input/usage/evidence/checkpoint/dataset/log, chuẩn hóa snapshot và nhập mục workspace. Hàm có thể chạy lại: chỉ bổ sung phần còn thiếu, không ghi đè bản ghi DB mới bằng JSON cũ. Những file lỗi được trả trong danh sách `errors` để xử lý; không tự xóa hoặc gán thành nghiên cứu thành công.

`Run` tự nhập một run legacy khi mở mà database chưa có run đó. Backend khởi động có thể gọi migration để thư viện cũ xuất hiện. CLI của dự án cung cấp lệnh chuyển storage qua cùng hàm này; xem `python run.py --help` để biết tên lệnh được hỗ trợ.

Các giới hạn API và `input_hash` được giữ nguyên. Migration không đặt lại bộ đếm, không đổi source/keyword và không gọi lại nguồn.

## So sánh cùng sản phẩm qua các năm

Snapshot có định danh ổn định: Amazon dùng **ASIN**; nguồn khác dùng định danh provider/listing hoặc URL riêng. Mỗi bản ghi giữ `observed_at`, giá, tiền tệ, biến thể, nhà bán, sao và nhãn mua nếu nguồn trả. Có thể truy lại cùng ASIN qua nhiều lần thu thập:

```sql
SELECT run_id, observed_at, asin, price, currency, rating, review_count
FROM product_snapshots
WHERE identity_key = 'amazon:B012345678'
ORDER BY observed_at;
```

Điều này **không tạo ra lịch sử Amazon 2021–2025** nếu trước đây chưa thu thập snapshot ở các năm ấy. Nhiều lần chạy demo cùng một bộ raw/ngày lấy không phải nhiều năm quan sát mới. Khi phân tích lịch sử sản phẩm, phải khử trùng các snapshot phát lại và tách tiền tệ/biến thể/nhà bán; không gộp mọi giá vào một kết luận ổn định.

Google Trends cho phép hồi cứu **mức quan tâm của cùng query**, không tự suy ra giá/lượt bán của cùng ASIN trong năm đó. Báo cáo phải tách phần kiểm chứng xu hướng keyword với độ ổn định sản phẩm đã có snapshot thật. Thiếu lịch sử được ghi rõ, không điền số giả.

## Kiểm tra và sao lưu

Có thể mở file bằng DB Browser for SQLite hoặc Python `sqlite3`. Các câu truy vấn ví dụ chỉ đọc dữ liệu; không chỉnh input/quota bằng tay nếu muốn giữ khả năng đối chiếu.

```sql
SELECT status, COUNT(*) FROM runs GROUP BY status;
SELECT provider, engine, COUNT(*) FROM api_calls GROUP BY provider, engine;
SELECT measurement_query, year, month, value, status
FROM trend_observations ORDER BY measurement_query, year, month;
```

Để sao lưu toàn dự án, giữ database cùng raw/ảnh và outputs liên quan. Dừng server trước khi copy file database bằng tay; khi ứng dụng đang chạy có thể có file `-wal`/`-shm`, vì vậy không lấy riêng một file `.sqlite3` trong lúc đang ghi rồi coi đó là bản backup hoàn chỉnh.

Schema hiện tại có phiên bản trong `PRAGMA user_version`. Code từ chối mở schema mới hơn phiên bản nó hiểu để tránh tự hạ cấu trúc và mất dữ liệu.
