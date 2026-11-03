# Báo cáo nghiên cứu gồm sáu phần

`report.html`, `report.md` và `report.pdf` cùng dùng một nội dung do Python dựng. LLM không được điền thêm số liệu, giá hoặc phản hồi còn thiếu. Báo cáo chính dành để đọc và ra quyết định kiểm chứng; các bảng đầy đủ nằm riêng để tra cứu.

| Phần | Người đọc tìm được gì |
| --- | --- |
| 1. Mục tiêu nghiên cứu | Mô tả đầu vào, danh mục/niche, khách hàng giả định, Mỹ, kỳ bán, các năm lịch sử và điều kiện sản phẩm. |
| 2. Keyword và xu hướng | Keyword được chọn, truy vấn thực sự đo, hạng và lý do; đường Trends cùng tháng qua các năm; cùng kỳ tháng bán và các khoảng tự chọn; mức độ lặp mùa. |
| 3. Kiểm chứng và dự báo | Những năm đã dự đoán thử, MAE, WAPE, sai số của mốc cùng kỳ năm trước và mức cải thiện; chỉ số dự báo cho các tháng bán; độ phủ và giới hạn. |
| 4. Sản phẩm và bằng chứng thị trường | Tối đa ba mẫu mỗi niche, chín mẫu toàn báo cáo: ảnh nguồn nếu tải được, link, ASIN/nguồn, giá và tiền tệ, sao listing, nhãn mua, ngày lấy và một phản hồi gắn đúng mẫu. Trang Facebook/TikTok công khai được ghi rõ là nguồn ngữ cảnh. |
| 5. Đề xuất nên cân nhắc bán | Tối đa ba idea có mẫu mỗi niche: bán gì, cho ai, lý do theo thời điểm, quy cách/điểm khác biệt đã có căn cứ, mẫu đối chiếu kèm giá và việc phải thử tiếp. Chỉ có một idea thì ghi một, không tạo giả để đủ hai hoặc ba. |
| 6. Tổng kết ưu tiên | So sánh niche, trạng thái ưu tiên kiểm chứng, độ đủ mẫu/lịch sử, việc tiếp theo, cảnh báo chính và số lượt API. |

Trong PDF, mỗi phần từ 2 đến 6 bắt đầu trang mới. Các bảng giữ nguyên hàng, lặp tiêu đề khi qua trang; link màu xanh là URI thật, không phải ảnh chụp trang. Bản mẫu gần đây có khoảng 9–12 trang tùy số mẫu và kỳ so sánh; không đặt trần trang bằng cách cắt mất bằng chứng. Nội dung nguồn dài được rút gọn ở bản chính và giữ đầy đủ trong phụ lục.

## Đọc thước đo đúng cách

- **MAE**: sai số tuyệt đối trung bình của chỉ số Trends. Ví dụ MAE 4 nghĩa là sai lệch bình quân 4 điểm chỉ số, không phải 4% doanh số.
- **WAPE**: tổng sai số tuyệt đối / tổng quan sát, tính theo phần trăm; không tính khi mẫu nền bằng 0.
- **Mốc cơ sở**: dùng cùng tháng năm liền trước. Mức cải thiện dương nghĩa là sai số mô hình nhỏ hơn mốc; giá trị âm cho biết mô hình còn kém hơn cách đơn giản đó.
- **Kiểm chứng qua nhiều năm**: mỗi năm thử chỉ được dự đoán bằng những năm trước nó; năm đích không dùng để huấn luyện. Năm thiếu dữ liệu không được đổi thành số 0.
- **Độ tin cậy**: mức bằng chứng định tính theo số lần kiểm chứng, độ phủ và sai số; không phải xác suất dự báo chính xác. Chuỗi tải hồi cứu không chứng minh đã phát hiện cơ hội từ thời điểm quá khứ.
- **Ổn định mùa vụ**: xem đồng thời độ dao động mức năm (CV), tương quan nhịp các tháng và khả năng lặp lại tháng đỉnh. Bảng lịch sử đối chiếu cùng một truy vấn, cùng thang chuẩn hóa, không so raw index của hai chuỗi tải riêng.

Trends phản ánh **loại sản phẩm/keyword**, không phải doanh số hay lịch sử của đúng ASIN. `product_history` chỉ dùng các quan sát sản phẩm thực sự đã lưu trong database. Nếu chỉ mới có snapshot 2026 thì báo cáo ghi rõ chưa có dữ liệu mẫu đó ở 2021–2025. Chọn thêm năm trên dashboard không làm xuất hiện lịch sử sản phẩm chưa từng thu thập.

## Tệp dùng để tra cứu

Trong `outputs/<run_id>/`:

- `report.pdf`, `report.html`, `report.md`: bản chính sáu phần.
- `report-details.html`, `report-details.md`: toàn bộ nguồn, phản hồi, xếp hạng, diễn giải bổ sung và biểu đồ dự báo 12 tháng.
- `niches/`: báo cáo đầy đủ riêng từng niche.
- `catalog.html`: toàn bộ mẫu, link và ảnh trực tiếp từ nguồn nếu có.
- `tables/`: các bảng xuất đầy đủ, gồm chuỗi tháng, kỳ tự chọn, kiểm chứng từng năm, dự báo và mẫu hàng. CSV là bản trao đổi/xuất báo cáo; database lưu dữ liệu phục vụ ứng dụng.
- `assets/`: bản sao nhỏ của ảnh nguồn đã cache để PDF nhúng ảnh và HTML có thể xem qua dashboard.
- `dataset.json`, `sources.json`, `usage.json`, `validation.json`, `pdf-status.json`: dữ liệu xuất, nguồn, chi phí/độ đủ dữ liệu và trạng thái khả năng tạo PDF.

Ảnh chỉ lấy từ HTTPS trên các CDN ảnh được hỗ trợ (Amazon, Walmart, Etsy, eBay, Google); từ chối địa chỉ IP riêng, URL chứa thông tin đăng nhập và chuyển hướng ra ngoài danh sách. Mỗi lần dựng báo cáo chỉ xét tối đa chín ảnh, timeout bốn giây/ảnh, giới hạn 3 MB và 20 triệu pixel. Cache dùng lại ở `data/report-images/`. Tải ảnh không gọi SerpApi, Tavily hoặc OpenRouter. Ảnh thiếu/lỗi chỉ tạo nhãn thiếu và link mẫu; không làm hỏng toàn báo cáo. Chạy offline hoặc kiểm thử không tải ảnh mới.

Để dựng lại báo cáo của một lượt đã lưu, chạy `python run.py report --run-id <run_id>`. Lệnh dùng dữ liệu đã lưu, không tự thu thập thêm lịch sử/keyword/sản phẩm. Muốn có năm lịch sử mới cần chạy nghiên cứu mới hoặc chạy tiếp nhánh thu thập với cấu hình phù hợp. Báo cáo HTML/PDF phải mở bằng nút trong dashboard hoặc trình đọc PDF có hỗ trợ link.
