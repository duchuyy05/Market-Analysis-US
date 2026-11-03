# Bộ kiểm thử dùng khi bảo trì dự án

Thư mục này nên được giữ lại để dùng sau mỗi lần sửa code. Dashboard và workflow nghiên cứu không tự chạy các test khi dùng `python run.py`.

Các tên `test_v2_*`, `test_v3_*`, `test_v4_*` ghi mốc bổ sung kiểm thử. Chúng vẫn kiểm tra code hiện tại trong `src/market_research/`, không phải những bản ứng dụng cũ cần chạy riêng.

| Nhóm | Kiểm tra điều gì |
|---|---|
| Database, storage, product history | Lưu SQLite, chuyển dữ liệu cũ, checkpoint và snapshot sản phẩm thật |
| Forecasting, historical validation, comparison periods | So cùng kỳ, công thức sai số, dữ liệu thiếu và không dùng năm đích để huấn luyện |
| Sources, discovery, Trends recovery, workflow | Khám phá keyword, lỗi nguồn, cache và chuyển nguồn Trends trong ngân sách |
| Control, selection | Dừng/chạy tiếp, số keyword và trần API |
| Report, rankings, collection quality | Sáu phần báo cáo, link PDF, ảnh nguồn, gắn đúng review và dữ liệu thiếu |
| HTTP, workspace, check_ui.mjs | Dashboard, tải file, lọc/sắp xếp sản phẩm và biên tập báo cáo |

Test dùng phản hồi nguồn được kiểm soát hoặc dữ liệu demo đã lưu, không cần gọi SerpApi/Tavily/OpenRouter thật. Một số kiểm tra PDF/JavaScript cần thư viện PDF hoặc Node đã cài.

Từ thư mục gốc dự án, khi cần kiểm tra sau sửa code:

```powershell
python -B -m pytest -q -p no:cacheprovider
```

Chỉ kiểm tra phần lịch sử và database:

```powershell
python -B -m pytest -q -p no:cacheprovider tests/test_historical_validation.py tests/test_comparison_periods.py tests/test_database.py tests/test_product_history.py
```

`-B` hạn chế tạo bytecode và `-p no:cacheprovider` không tạo `.pytest_cache`. Kết quả chạy thử là dữ liệu tạm; không cần giữ `.tmp-*`, `.pytest_cache`, `tmp/` hoặc `__pycache__/` để sử dụng ứng dụng. Giữ database/raw trong `data/` và báo cáo trong `outputs/` khi cần lịch sử nghiên cứu.
