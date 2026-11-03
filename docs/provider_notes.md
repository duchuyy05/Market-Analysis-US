# Nguồn và giới hạn

Đối chiếu đến 29/10/2026. Bản đa nguồn dùng Trends auto miễn phí → SerpApi dự phòng, cùng tổng trần SerpApi cho mẫu hàng, Tavily trích ứng viên từ trang công khai. Xem [luồng mới và giới hạn thực tế](workflow-discovery.md). Schema có thể thiếu trường; mỗi nguồn xử lý độc lập. Không thêm Apify.

- Google Trends miễn phí: endpoint explore/widgetdata không chính thức; đếm HTTP, lỗi 429 nghỉ nhánh miễn phí 15 phút. Mode auto kiểm tra cache/chất lượng và dùng SerpApi trong trần con 8, tổng 20, reserve sản phẩm 10; mode free không chuyển trả phí. Không có keyword đo được thì chờ Trends trước tìm mẫu. Kiểm tra thật 28/10 từng nhận 429; fallback 29/10 kiểm thử fixture, chưa chi quota thật.

- [Trends](https://serpapi.com/google-trends-api): `engine=google_trends`, `data_type=TIMESERIES`, geo US, một từ khóa/cửa sổ 2023 đến ngày chốt. `RELATED_QUERIES` cung cấp top/rising khi nguồn có. Từ quá hẹp có thể không có related/history.
- [Amazon search](https://serpapi.com/amazon-search-api): `engine=amazon`, `k`, amazon.com. Một truy vấn không có kết quả được thử rút gọn các từ phụ, vẫn kiểm mức liên quan theo keyword gốc. Không lặp vô hạn cùng truy vấn thất bại.
- [Amazon product](https://serpapi.com/amazon-product-api): `engine=amazon_product`, asin. Giá/nhãn ở detail không âm thầm kế thừa search; hai quan sát có ngày và offer riêng. Review summary AI không được coi là review người dùng; các example có link review được giữ nhãn excerpt.
- [Shopping](https://serpapi.com/shopping-results): `engine=google_shopping`, q, gl US. Giữ product_id riêng của Google; không đổi thành ASIN. Có thể chỉ có link Google product; nhà bán/tiền tệ chưa rõ giữ unknown. Vị trí search không phải BSR.
- [Tavily](https://docs.tavily.com/documentation/api-reference/endpoint/search): ba bó domain social/sàn/visual; keyword trích phải có câu nguồn và link. Ưu tiên country US không xác minh khán giả Mỹ; trang được lập chỉ mục không phải feed doanh số. Raw page không tự mở rộng quyền gọi mạng.
- [OpenRouter](https://openrouter.ai/docs/guides/features/structured-outputs): MVP yêu cầu JSON object và kiểm tra lại trong code; không giả định mọi model free hỗ trợ strict schema. Chỉ gọi `:free`/`openrouter/free`. Có fallback free hữu hạn, không tự chuyển trả phí.

Giới hạn request tính cả lỗi và retry, lưu trước khi gửi mạng và giữ khi resume. Retry HTTP tạm thời có giới hạn; lỗi quyền/quota không lặp vô hạn. Khi hết ngân sách, những nguồn còn lại ghi unavailable, báo cáo có thể partial.

Không tuyên bố nghiên cứu đã đủ khi một nguồn bị thiếu. Bộ offline Q4 là các quan sát Amazon/Trends đã lưu 22/10/2026; không có Shopping hay Related Queries, nên báo cáo offline mang nhãn partial.

Live smoke nhỏ đã kết nối LLM free, Trends và Shopping. Amazon có thể trả no-results với truy vấn dài; OpenRouter có thể 429. Kết quả này kiểm tra xử lý thiếu nguồn, không xác nhận độ chính xác toàn bộ thị trường hoặc mọi adapter trong mọi trường hợp.
