# Dữ liệu v2

Backend lưu có cấu trúc chính trong `data/market_research.sqlite3`. Input của run được khóa bằng hash; cấu hình, checkpoint, dataset và evidence đọc từ DB trước. `data/runs/<run_id>` giữ raw và bản xuất tương thích `manifest.json`/`normalized_config.json`/`dataset.json`; sửa JSON không ghi đè dữ liệu DB. `outputs/<run_id>` chứa báo cáo và CSV/JSON có thể chia sẻ. Xem [schema và migration](database.md).

| Bảng | Khóa / ý nghĩa |
|---|---|
| keywords | `id`, niche, text, seed, origin, evidence_ids; origin phân biệt user/llm_candidate/provider_related/archive_seed |
| directions | `id`, niche, keyword đại diện, keyword hỗ trợ, truy vấn, giả thuyết khách hàng |
| search_occurrences | Mỗi lần thấy listing qua một truy vấn; giữ position, sponsored true/false/null, query, nguồn và ngày |
| products | `product_id` nội bộ; ASIN gắn amazon.com hoặc định danh listing nguồn; giữ mọi hướng liên quan |
| offers | `offer_id`, product/listing, merchant, giá, tiền tệ, variant, ngày; thiếu unit count thì unit_price=null |
| product_matches | Cùng ASIN hoặc cùng danh tính listing; không gộp chỉ vì ảnh/tên giống nhau |
| reviews | `id`, product_id, text, full/excerpt, sao/ngày/variant khi có, evidence_ids |
| review_themes | Lượt nhắc từ khóa theo review; không phải sentiment hoặc tỷ lệ thị trường |
| histories | Chuỗi tháng, năm đủ tín hiệu, CV, cao điểm, forecast; `validation.folds` kiểm chứng nhiều năm, `same_period` và `seasonal_stability`; scale riêng từng query |
| historical_validation | Direction, năm huấn luyện/thử, quan sát/dự báo/mốc cơ sở, MAE/RMSE/WAPE/sMAPE và skill |
| same_period_years | Cùng các tháng bán theo từng năm, độ phủ và thay đổi so năm liền trước |
| product_capture_history | Các snapshot thực tế của đúng danh tính nguồn/ASIN; năm chưa thu thập không có số giả |
| assessments | Trạng thái hướng, demand/season/purchase/differentiation/business_fit; positive/neutral/negative/unknown |
| product_checks | eligible/excluded/pending_verification; điều kiện cứng thiếu dữ liệu không tự pass |
| ideas | Bán gì, cho ai (giả thuyết), vì sao lúc này, mẫu, quote, việc thử và giới hạn |
| ranking_definitions | Eligibility/phạm vi/cách đồng hạng/version/trạng thái mỗi bảng |
| all_ranked_items | ranking_id, group, entity_id, rank, metric/rubric, evidence_ids; giữ toàn bộ ngoài top K |
| trend_observations | direction, năm/tháng, chỉ số, observed_days, complete/partial/future/unavailable |
| forecasts | target year/month, prediction, historical_min/max, observed, trạng thái và chênh lệch khi tháng hoàn tất |
| sources.json | Registry bằng chứng: ID, loại, URL, raw locator, excerpt, ngày truy cập, ngày đăng nếu có |
| usage.json | Request thực tế gồm thất bại/retry, model trả lời, tokens/cost khi nguồn trả; cache đếm riêng |

`null` không phải `0`. Không cộng nhãn mua hoặc rating giữa nguồn. Một ASIN tìm qua Shopping và Amazon có thể có hai lần phát hiện, vẫn là một listing Amazon, không phải hai bằng chứng mua độc lập.

CSV ghi trường list/dict dưới dạng JSON; UTF-8 BOM giúp Excel đọc tiếng Việt. Chuỗi có đầu `= + - @` được thêm dấu nháy để không chạy công thức. JSON giữ dữ liệu gốc tương ứng.

Raw provider được lưu thành envelope gồm parameters (đã che key), response, retrieved_at, raw_file. Chạy tiếp dùng cùng raw thành công, giữ ngày nguồn gốc. Không coi cache là vừa truy cập nhà cung cấp.

## Phạm vi mùa và domain công ty

- `config.business`: profile `custom_manufacturing` và các nhóm hàng được chọn; `general` dành cho phạm vi tổng hợp hoặc lượt cũ. `products[].business_fit` ghi `allowed`, `excluded` hoặc `pending_verification` cùng lý do. `product_exclusions.csv` giữ các mẫu bị loại; `company_product_fit.csv` ghi kết quả kiểm tra mẫu còn lại.
- `config.trends.history_scope`: `full` lấy chuỗi liên tục; `seasonal` chỉ gọi các cửa sổ tháng/năm đã chọn trong `history_months` và `history_years`. `comparison_periods` chỉ tổng hợp trong phạm vi đó.
- Với mùa vụ, `histories[].monthly` chỉ chứa các tháng được phép thu. `raw_value` và `anchor_raw_value` giữ chỉ số nguồn; `value = raw_value / anchor_raw_value × 100`. `metric_unit: anchor_100` có thể vượt 100. Không đọc trường này như chỉ số Google Trends gốc 0–100, lượng tìm kiếm hay doanh số.
- `analysis_scope: selected_months`, `period_means`, `period_cv`, `peak_scope: selected_months` chỉ mô tả kỳ đã thu. Các alias tương thích `annual_means`/`annual_cv` trong chế độ này cũng có phạm vi kỳ, không phải cả năm.
- `normalization_context.requested_windows` và `source_windows` giữ đúng khoảng nguồn, raw file và bằng chứng. `collection_signature` ngăn tái dùng checkpoint khác phạm vi.
- Bảng xếp hạng tháng có thể giữ dòng trạng thái `not_collected` cho tháng ngoài phạm vi để kiểm toán; đó không phải quan sát nguồn và không được dùng tạo hạng hoặc dự báo. Kiểm chứng chỉ tính ngày/tháng đã chọn, mốc cơ sở là cùng tháng năm liền trước khi có dữ liệu.
