# Chọn lịch sử, đọc sai số và kiểm tra độ ổn định

## Chạy trên dashboard

Chạy `python run.py`, mở ứng dụng rồi mở **Thiết lập nghiên cứu**.

1. Đặt ngày chốt dữ liệu (ví dụ 29/10/2026), tháng bán (ví dụ `11,12`).
2. Ở **Năm lịch sử và kiểm chứng dự báo**, chọn **Từ năm 2021**, **Đến năm 2025**, **Năm cần dự báo 2026**. Nút **2021–2025 → 2026** điền nhanh các giá trị này.
3. Bấm **Q4 các năm đã chọn** nếu muốn bảng riêng tháng 10–12 của từng năm; hoặc thêm từng khoảng tháng độc lập. Khoảng so sánh không thay thế chuỗi cả năm dùng kiểm tra mùa vụ.
4. Chọn ngân sách API và bắt đầu. Trong kết quả, mở **Chất lượng lịch sử & kiểm chứng dự báo** hoặc ô tiến trình **Lịch sử và dự báo** để xem độ phủ, năm đủ dữ liệu, sai số, mốc cơ sở và giới hạn.

Hỗ trợ 2–6 năm hoàn tất trong mỗi lượt, từ năm 2004. Năm lịch sử cuối phải trước năm của ngày chốt; năm dự báo phải sau mọi năm lịch sử. Ví dụ ngày chốt năm 2026 thì năm 2026 chưa được dùng làm một năm lịch sử hoàn tất. Dữ liệu năm 2026 đã quan sát được hiển thị riêng để đối chiếu, không học lại mô hình 2026.

Đổi năm lựa chọn cần tạo lượt nghiên cứu mới để tải đúng khoảng. Xuất lại báo cáo cũ chỉ tính lại các phép đo trên dữ liệu đã lưu, không tạo thêm dữ liệu 2021/2022 chưa từng thu thập. Nguồn có thể trả thiếu dữ liệu và API vẫn chịu các trần đã đặt.

## Kiểm chứng dự báo trên năm đã biết

Mô hình cơ sở của dự án dự báo từng tháng bằng trung vị của cùng tháng ở các năm lịch sử đủ dữ liệu. Với 2021–2025, kiểm chứng lần lượt:

| Năm thử | Năm dùng học | Mốc cơ sở đối chiếu |
|---|---|---|
| 2023 | 2021, 2022 | Cùng tháng 2022 |
| 2024 | 2021, 2022, 2023 | Cùng tháng 2023 |
| 2025 | 2021, 2022, 2023, 2024 | Cùng tháng 2024 |

Mỗi lần thử chỉ dùng năm trước năm thử. Năm 2026 không tham gia huấn luyện hay tính sai số kiểm chứng. Với ba năm 2023–2025 chỉ có một năm thử độc lập (2025); hai năm thì chưa đủ hai chu kỳ huấn luyện cho một phép kiểm chứng mới. Các trường `backtest` cũ được giữ để tương thích; báo cáo mới dùng `validation` với nhiều năm thử.

- **MAE:** trung bình sai lệch tuyệt đối, đơn vị điểm Trends. Thấp hơn là tốt hơn.
- **RMSE:** căn trung bình bình phương sai lệch; nhạy hơn với lỗi lớn.
- **WAPE:** tổng sai lệch tuyệt đối chia tổng chỉ số thực tế, nhân 100. Không tính khi mẫu thực tế toàn số 0. Đây là tỷ lệ sai số chỉ số, không phải tỷ lệ dự báo đúng hay sai số doanh thu.
- **sMAPE:** trung bình `2 × |dự báo − thực tế| / (|dự báo| + |thực tế|)`, nhân 100; cặp cùng bằng 0 đóng góp 0.
- **Skill:** phần trăm MAE giảm so với mốc cùng tháng năm liền trước. Âm nghĩa là mô hình đang kém mốc cơ sở. Chỉ tính khi hai cách có cùng mẫu kiểm chứng. Nếu mốc cơ sở đã có sai số 0, không tuyên bố phần trăm cải thiện vô hạn.

Có sai số toàn năm và riêng các tháng bán. Nếu một năm bị thiếu, không thay bằng 0. Mốc cơ sở là năm lịch liền trước, không tự thay bằng năm gần nhất có dữ liệu. Đây là kiểm chứng hồi cứu trên dữ liệu hiện tải về và bộ keyword đang chọn; không chứng minh hệ thống đã khám phá đúng cơ hội tại thời điểm quá khứ.

## Độ phủ, mức bằng chứng và độ ổn định

Độ phủ = ngày có quan sát hợp lệ / ngày lịch của các năm đã chọn. Một năm dùng dự báo cần đủ 12 tháng, peak ít nhất 5 điểm, và tín hiệu ở ít nhất hai tháng. Với dữ liệu tuần/ngày còn cần ít nhất 8 điểm nguồn dương. Google có thể trả độ phân giải tháng khi lấy lịch sử dài; trường hợp này không áp nhầm ngưỡng 8 điểm tuần vào chỉ hai tháng mùa vụ. Một spike duy nhất không được coi là ổn định nhiều mùa.

Mức bằng chứng **chưa đủ / hạn chế / vừa / nhiều bằng chứng** là nhãn theo quy tắc, không phải xác suất chính xác:

- Chưa đủ khi không có năm kiểm chứng hợp lệ.
- Hạn chế khi có ít năm thử, thiếu lịch sử hoặc sai số kém mốc cơ sở.
- Vừa khi ít nhất 2 năm thử, độ phủ ≥95%, WAPE ≤35% và MAE không kém mốc cơ sở.
- Nhiều bằng chứng khi ít nhất 3 năm thử, đủ mọi năm đã chọn, độ phủ ≥95%, WAPE ≤20% và MAE tốt hơn mốc cơ sở.

Các ngưỡng này là quy tắc đánh giá công khai của ứng dụng, cần hiệu chỉnh khi tích lũy thêm kết quả thực tế. Không phải chuẩn thống kê chứng minh xác suất.

Bảng `same_period` so sánh đúng tháng bán ở từng năm, ghi trung bình chỉ số, độ phủ, tăng/giảm so năm lịch liền trước và tháng đỉnh. `seasonal_stability` dùng hệ số biến thiên trung bình năm (CV), tương quan hình dạng 12 tháng giữa các năm liền kề đủ dữ liệu, và tỷ lệ đỉnh trùng tháng. Nhãn ổn định cần ít nhất hai năm, CV ≤0,25 và tương quan ≥0,6. Giá trị 0,25/0,6 được xuất cùng kết quả để người đọc kiểm tra.

## Phân biệt xu hướng keyword và lịch sử sản phẩm

Google Trends đo mức quan tâm tìm kiếm tương đối tại Mỹ trên cùng truy vấn và thang đo. Truy vấn được lưu tại `measurement_query`; nếu nguồn dùng từ khóa loại hàng thay cho keyword quá cụ thể, báo cáo phải ghi phạm vi đó. Không so trực tiếp các con số 0–100 của những chuỗi tải độc lập như thể đó là lượng tìm kiếm tuyệt đối.

Lịch sử giá, sao, số review hay tín hiệu mua của cùng ASIN/chứng cứ mẫu hàng chỉ có khi dự án đã lưu ảnh chụp dữ liệu thực tế của sản phẩm đó ở nhiều thời điểm. Không thể suy ngược doanh số/giá Amazon năm 2021 từ Trends. Bảng sản phẩm thiếu năm trước phải ghi thiếu; database sẽ tích lũy các lần quan sát sau này.

## Dữ liệu kỹ thuật

Kết quả `histories[]` giữ trường cũ và thêm `validation`, `same_period`, `seasonal_stability`. `validation.folds[]` chứa năm học, năm thử, từng dự báo/giá trị thực/mốc cơ sở cùng sai số; không cần LLM để tạo số liệu. Backend và dashboard đọc SQLite trước; JSON/CSV là bản xuất và tương thích lịch sử. Báo cáo được dựng lại từ dữ liệu lưu, không gọi API khi chỉ tính lại sai số.
