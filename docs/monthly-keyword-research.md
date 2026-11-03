# Nghiên cứu nhiều keyword và xếp hạng theo tháng

Cập nhật 02/11/2026. Tài liệu này mô tả luồng mở rộng ứng viên, lịch sử theo tháng, ảnh sản phẩm và cách đọc bằng chứng. Đổi cấu hình chỉ có hiệu lực với lượt mới; không tự làm tăng quota của tài khoản API. Sàng lọc mẫu trong một tháng/năm quan sát là phần riêng với dự báo nhiều năm: xem [mẫu thiết kế theo tháng](design-trends-by-month.md).

## 1. Phân biệt ba số lượng

| Số lượng | Ý nghĩa |
| --- | --- |
| Ứng viên khám phá, mặc định 64 | Các loại hàng có thể phù hợp để đưa đi kiểm chứng; gồm đề xuất LLM và keyword có nguồn web/Related |
| Keyword có dữ liệu theo tháng | Phần ứng viên thật sự lấy được chuỗi và đủ năm/tín hiệu để phân tích; có thể ít hơn 64 |
| Top keyword tìm sản phẩm, mặc định 10 | Các truy vấn đưa sang Amazon/Shopping; không phải tổng số ứng viên hoặc số sản phẩm cuối cùng |

64 ứng viên không có nghĩa là 64 keyword đang hot. Báo cáo ghi số ứng viên, số loại hàng khác nhau, phần có nguồn và phần còn là giả thuyết. Không thêm từ trùng, biến thể màu/cá nhân hóa hoặc keyword ngoài phạm vi chỉ để vượt mốc 50.

Sau seed, khám phá web và Related, nếu còn thiếu ứng viên, chương trình thử tối đa **hai vòng mở rộng LLM**, kể cả tập ứng viên nhỏ. Mỗi đề xuất cần niche hợp lệ, keyword sản phẩm/mẫu thiết kế tiếng Anh và lý do giả thuyết phù hợp. Hình in, nhân vật hoặc họa tiết khác nhau được giữ riêng; chỉ khử trùng cùng truy vấn. Mỗi vòng vẫn có thể có thử lại model theo cơ chế chung và trần OpenRouter; hai vòng không có nghĩa luôn đúng hai HTTP request. Không tự nâng trần hoặc bịa nguồn. Kết quả mở rộng có checkpoint riêng để chạy tiếp không mất keyword đã có khi quota LLM hết.

## 2. Cách chọn trên dashboard

1. Dừng server cũ bằng Ctrl+C, chạy `python run.py`, tải lại trang bằng Ctrl+F5.
2. Nhập brief, người nhận, thời gian bán và khoảng giá nếu đó là điều kiện bắt buộc.
3. Chọn 64 ứng viên hoặc số phù hợp trong giới hạn 1–100. Bật **xếp hạng keyword theo tháng**; dashboard mới chọn sẵn tùy chọn này. Lịch sử keyword tối đa là 64, số dòng mỗi bảng tháng mặc định 10.
4. Chọn tháng/năm phân tích mẫu riêng, ví dụ tháng 11/2025; chọn thêm năm lịch sử, ví dụ 2021–2025, và năm đích 2026 để đối chiếu/dự báo. Phạm vi theo tháng chỉ thu đúng các tháng đó; phạm vi cả năm lấy chuỗi đầy đủ. Mẫu mới có một kỳ quan sát vẫn được sàng lọc, không bắt buộc đã tồn tại đủ hai năm.
5. Muốn dùng cấu hình rộng đã cân đối, bấm nút preset nghiên cứu rộng/theo tháng rồi xem lại các trần trước khi bắt đầu.

Backend giữ `trends.monthly_rankings: false` khi một file cấu hình cũ không có trường này, để không tự phát sinh nhánh gọi lịch sử ứng viên cho run cũ. Dashboard mới gửi rõ `true` khi ô được chọn. Với CLI/YAML, phải bật trường này nếu muốn chạy nhánh theo tháng.

### Preset rộng trên giao diện

| Thiết lập | Giá trị preset |
| --- | ---: |
| Ứng viên | 64 |
| Top keyword tìm sản phẩm | 10 |
| Keyword lấy lịch sử tháng tối đa | 64 |
| Dòng hiển thị mỗi tháng | 10 |
| Tổng SerpApi | 50 |
| SerpApi dành cho Trends, nằm trong tổng | 34 |
| Phần giữ cho mẫu hàng | 14 |
| Chi tiết Amazon | 3 |
| Shopping | Bật, tối đa 2 keyword |
| Tavily | 6 |
| OpenRouter | 20 |

Preset chỉ đổi các ô khi người dùng bấm. **Mặc định trần trả phí của dự án vẫn là tổng 20 và Trends 8**, không tự chuyển thành 50/34 khi mở dashboard. Với 64 ứng viên và phân tích tháng, trần cũ có thể không đủ; phần dự trù sẽ báo điều đó.

Ước tính khi không dùng được Trends miễn phí và có đủ 64 truy vấn khác nhau:

```text
16 sàng lọc (4 keyword + anchor / yêu cầu)
+16 lịch sử tháng (4 keyword + anchor / yêu cầu)
+10 Amazon + 2 Shopping + 3 chi tiết
=47 lượt SerpApi
```

Trần 50 còn khoảng ba lượt tổng, trần Trends 34 còn khoảng hai lượt Trends để xử lý thêm. Cache, keyword trùng và ít kết quả có thể làm số gọi thấp hơn; retry/phục hồi có thể dùng thêm nhưng vẫn bị trần chặn. Chương trình không cố tiêu hết ngân sách, không tự đồng bộ quota còn lại trong tài khoản và không bảo đảm nguồn trả đủ 64 chuỗi.

### Cấu hình tương đương khi chạy bằng file

Thêm vào file JSON/YAML của nghiên cứu, giữ brief và các điều kiện của bạn:

```yaml
history_years: [2021, 2022, 2023, 2024, 2025]
target_year: 2026
selling_months: [11, 12]
trends:
  provider: auto
  monthly_rankings: true
sources:
  trends: true
  amazon: true
  shopping: true
  web: true
limits:
  candidate_keywords: 64
  top_keywords: 10
  monthly_keywords: 64
  monthly_rows: 10
  serpapi_requests: 50
  trends_serpapi_requests: 34
  serpapi_product_reserve: 14
  product_details: 3
  shopping_keywords: 2
  tavily_requests: 6
  llm_requests: 20
```

Kiểm tra bằng `python run.py validate-config --config configs/my-research.yaml`, rồi chạy `python run.py run --config configs/my-research.yaml`. Không đặt API key trong file nghiên cứu; key vẫn nằm trong `.env`.

## 3. Luồng xử lý

```text
Hiểu mô tả
→ seed + mở rộng LLM + web/Related
→ sàng lọc Trends gần đây
→ lịch sử và xếp hạng keyword theo 12 tháng
→ gom nhóm, chọn Top N phù hợp tháng bán
→ mẫu Amazon/Shopping, chi tiết/phản hồi
→ dùng lại lịch sử đã có cho hướng đã chọn
→ đánh giá, ý tưởng, xếp hạng, báo cáo
```

Bước `monthly` ở trước chọn keyword tìm sản phẩm. Nó lấy lịch sử cho tập ứng viên trong `monthly_keywords`, không chỉ cho Top 10 đã chọn. Mỗi yêu cầu dùng tối đa bốn keyword và một anchor chung `gift basket`. Đo tất cả trên cùng cửa sổ năm/thị trường giúp so mức tương đối giữa các batch bằng tỷ lệ so anchor. Bước `history` sau tìm mẫu dùng lại checkpoint phù hợp, không mặc định gọi lại toàn bộ Top 10.

Các trần chung, trần Trends, phần giữ cho lịch sử và phần giữ cho mẫu hàng vẫn được kiểm tra trước request mới. Thiếu quota hoặc dữ liệu thì từng keyword/tháng giữ trạng thái thiếu và log nguyên nhân. Không lấy số 0 thay cho tháng chưa thu được.

## 4. Đọc hạng theo tháng

| Chỉ tiêu | Cách hiểu |
| --- | --- |
| Hạng phù hợp mùa/tháng | So mức của một keyword trong tháng đó với đỉnh riêng của chính keyword ở các năm đủ tín hiệu; không phải hạng lượng tìm kiếm |
| Hạng nhu cầu tương đối | So tỷ lệ keyword/anchor trong nhóm có cùng anchor, thị trường và cửa sổ; nếu chỉ chung một batch thì chỉ so trong batch đó |
| Số năm đủ dùng, CV tháng, thay đổi cùng kỳ | Bằng chứng về độ phủ và mức duy trì của đúng tháng qua các năm; thiếu dữ liệu vẫn ghi thiếu |
| Ưu tiên tìm mẫu cho tháng bán | Khi đủ lịch sử trên cùng anchor: 70% phân vị nhu cầu tương đối + 30% phân vị phù hợp mùa trong tập đang nghiên cứu |

Ví dụ một món bán quanh năm có nhu cầu lớn vẫn có thể xếp thấp hơn về **tính mùa vụ** so với một món chỉ đạt đỉnh tháng 12. Vì vậy không dùng hạng phù hợp mùa để nói món đó có nhiều người tìm hơn. Điểm Google Trends chuẩn hóa riêng giữa các yêu cầu không được đem so trực tiếp; bảng ghi nhóm so sánh và lý do khi chưa xếp hạng được.

Ưu tiên tìm mẫu tháng 11–12 dùng bằng chứng của cả hai tháng khi đủ dữ liệu trên một nhóm anchor. Chưa đủ thì chương trình có thể dùng phép đo gần đây làm nhánh dự phòng và ghi rõ phương pháp; không gọi đó là kiểm chứng nhu cầu Giáng sinh hoặc dự báo doanh số. Hồi cứu chỉ dùng năm trước năm đích; tháng tương lai chưa phải quan sát thật.

## 5. Ảnh, mẫu hàng và ý tưởng

Ảnh phải đến từ listing/detail đã thu thập, không dùng ảnh AI để thay bằng chứng. Luồng xuất báo cáo tải ảnh nguồn qua HTTPS và cache với tối đa bốn tác vụ đồng thời, tái sử dụng ảnh đã lưu rồi nhúng vào PDF. Tải ảnh là HTTP tới máy chủ ảnh, không phải lượt SerpApi/Tavily/OpenRouter. Nếu URL không hợp lệ, nguồn chặn hoặc tải thất bại, báo cáo giữ trạng thái và nguyên nhân trong `image-status.json`; không âm thầm bỏ ảnh mà coi như đầy đủ.

Mẫu đối chiếu giữ URL, giá/tiền tệ, ASIN hoặc ID nguồn, ngày lấy, nhãn mua/sao và phản hồi của đúng sản phẩm. Review lấy được ở một mẫu không chứng minh sở thích của toàn thị trường. Link TikTok/Facebook là ngữ cảnh từ trang công khai được tìm thấy, không phải bằng chứng số đơn tại Mỹ.

Mỗi ý tưởng giải thích bán gì/cho ai, lý do theo kỳ bán, mẫu chính và mẫu thay thế khi có, mức bằng chứng và giả thuyết khác biệt cần thử. Không nhân bản cùng món thành nhiều idea để đủ số; không tự coi giá listing là giá vốn/lợi nhuận. Mục tiêu 2–3 idea/niche còn phụ thuộc mẫu và dữ liệu phù hợp.

## 6. Output và dữ liệu lưu ở đâu

| File/bảng | Nội dung |
| --- | --- |
| `outputs/<run_id>/report.html`, `.md`, `.pdf` | Báo cáo chính sáu phần, phần keyword thể hiện độ phủ và tóm tắt tháng |
| `keyword-monthly.html`, `keyword-monthly.md` | Danh sách ứng viên đầy đủ và các bảng tháng, không giới hạn vào vài dòng trong PDF chính |
| `tables/keyword_monthly.csv` | Các dòng keyword × tháng, hạng/điểm, năm và bằng chứng |
| `tables/keyword_history_observations.csv` | Chuỗi tháng thực tế cho tập keyword ứng viên, gồm trạng thái thiếu |
| `catalog.html`, `tables/products.csv`, `tables/ideas.csv` | Toàn bộ mẫu và ý tưởng thu được |
| `image-status.json` | Kết quả kiểm tra/tải/cache ảnh và nguyên nhân ảnh còn thiếu |
| `data/market_research.sqlite3` | Nơi lưu chính: toàn bộ dataset gồm `keyword_histories`, `keyword_monthly`; chuỗi ứng viên cũng được chiếu vào các bảng Trends/backtest/forecast |

Chuỗi ứng viên không phải hướng được chọn tìm sản phẩm vẫn được giữ. Khi hai nhánh có cùng ID hướng, bản lịch sử của hướng được chọn được ưu tiên trong bảng chuẩn hóa, không tạo hai quan sát trùng cùng tháng. Không phải đổi sang CSV mới có dữ liệu; CSV là bản xuất để đọc/lọc/chia sẻ.

## 7. Run đã chạy không tự có thêm keyword

Lượt `run-20261030T040036-2238b6` có **32 ứng viên và lịch sử của 10 hướng** đã lưu. Dựng lại báo cáo có thể sửa ảnh, trình bày độ phủ và tính bảng tháng từ dữ liệu đó; không thể tự biến thành 64 ứng viên hoặc 50 keyword đã kiểm chứng.

Muốn thu tập rộng hơn phải tạo **nghiên cứu mới** với cấu hình mới. `report` chỉ dựng lại từ dữ liệu có sẵn và có thể tải ảnh chưa cache; không gọi API nghiên cứu. `resume` giữ trần/input của run cũ, không được dùng để tăng quota hoặc đổi phạm vi âm thầm.

```powershell
python run.py report --run-id run-20261030T040036-2238b6
```

Các con số vượt 50 cho biết độ rộng tập khảo sát. Độ thuyết phục đến từ truy vấn, nguồn, lịch sử cùng kỳ, sai số và mẫu hàng có thể kiểm tra, được hiển thị cùng độ phủ thực tế.
