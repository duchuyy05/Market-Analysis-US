# Bộ nguồn Q4 dùng lại cho offline v2

Thư mục này **còn được code hiện tại sử dụng**, không phải output của workflow cũ được giữ nguyên toàn bộ.

- `providers/archive.py` đọc `dataset.json` để phát lại mẫu sản phẩm và review.
- `workflow/history.py` đọc `collection.json` và các raw Trends để tính lại lịch sử/dự báo.
- Các raw Amazon trong `raw/` và `supplements/*/raw/` giữ làm bằng chứng cho các dòng sản phẩm/review được lưu.

## Phần được giữ

| File/thư mục | Vai trò |
|---|---|
| `dataset.json` | 33 sản phẩm và 1.038 nội dung review/trích đoạn đã thu thập; giá trị các dòng nguồn không bị đổi khi dọn |
| `collection.json` | Chỉ mục gọn cho 12 chuỗi Trends và keyword tương ứng |
| `raw/` | Phản hồi nguồn còn được các dữ liệu giữ lại tham chiếu |
| `supplements/*/raw/` | Phản hồi bổ sung còn được các review/sản phẩm giữ lại tham chiếu |

Snapshot ghi ngày chốt 22/10/2026; từng quan sát giữ ngày nguồn riêng. Bộ này không có Shopping/Related Queries phục vụ phát lại. Offline không phải nghiên cứu mới từ mô tả và không gọi API.

## Phần đã xóa

Đã xóa báo cáo HTML/Markdown, dashboard, CSV xuất từ pipeline cũ, phân tích tháng cũ, kết quả LLM cũ và raw không còn được dữ liệu sử dụng. Các bảng tổng hợp cũ trong dataset và metadata điều phối không dùng cũng đã được bỏ; sản phẩm/review gốc cần cho v2 được giữ.

Báo cáo mới được Python tạo ở `outputs/<run_id>/`; các mẫu để đọc ngay ở `examples/reports/`. Workflow live không đọc bộ này để thay cho nguồn mới.

## Kiểm tra sau khi dọn

Ngày 27/10/2026: còn 87 file gồm dataset, chỉ mục, README và 84 raw được tham chiếu; đã xóa 89 file cũ. Chạy lại `examples/offline-q4.json` cho kết quả giống trước khi dọn ở toàn bộ các bảng dữ liệu: 12 từ khóa, 10 hướng, 29 sản phẩm và 10 ý tưởng. Kiểm tra báo cáo không có lỗi, không gọi API; trạng thái `partial` vẫn do bộ offline thiếu Shopping.
