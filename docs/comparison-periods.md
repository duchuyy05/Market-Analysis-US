# Chọn khoảng tháng để so sánh lịch sử Trends

Cập nhật 29/10/2026. Trong dashboard, mở **Thiết lập nghiên cứu → Khoảng thời gian so sánh lịch sử Trends**.

Bạn có thể thêm nhiều khoảng độc lập, chẳng hạn:

| Khoảng | Từ | Đến |
|---|---|---|
| 1 | 10/2023 | 12/2023 |
| 2 | 10/2024 | 12/2024 |
| 3 | 10/2025 | 12/2025 |

Nút **Q4 năm 2023–2025** điền ba khoảng trên. Nút **Cả năm / xóa khoảng riêng** trở về phân tích cả năm như trước. Có thể thêm/xóa từng dòng; tối đa 12 khoảng, mỗi khoảng tối đa 120 tháng. Khoảng được chuẩn hóa theo thứ tự thời gian, không nhận khoảng trùng, tháng đảo ngược hoặc tháng sau ngày chốt. Nếu chọn tháng hiện tại chưa kết thúc, bảng ghi độ phủ partial thay vì coi đã đủ tháng.

## Dữ liệu nào chịu bộ chọn này?

Đây là **khoảng so sánh mức quan tâm Google Trends**. Nó không yêu cầu Amazon trả giá/review của năm 2023–2024 và không lọc ngày review sản phẩm. Các quan sát sản phẩm vẫn giữ ngày thu thập và nguồn thật.

Hệ thống lấy **một chuỗi lịch sử nhất quán cho mỗi keyword**, bao phủ các năm huấn luyện và khoảng bạn chọn; các khoảng được tổng hợp từ chuỗi đó ở Python. Không gọi API thêm một lần cho mỗi khoảng. Nếu chọn năm sớm hơn 2023, yêu cầu lịch sử mở rộng về đầu năm sớm nhất đó. Chuỗi đầy đủ vẫn được giữ để kiểm tra mùa vụ và dự báo; các tháng ngoài khoảng chọn không bị giả là đã xóa khỏi nguồn.

## Kết quả

`histories[].comparison_periods` chứa từng khoảng cùng:

- Chỉ số trung bình theo số ngày quan sát, không phải lượng tìm kiếm tuyệt đối hoặc doanh số.
- Số tháng/ngày yêu cầu, số quan sát, phần trăm độ phủ và trạng thái complete/partial/unavailable.
- Thay đổi so với khoảng trước chỉ khi cả hai đủ dữ liệu và mốc trước lớn hơn 0.
- Mã bằng chứng liên kết chuỗi lịch sử gốc.

Không có quan sát được giữ `mean_index: null`, không đổi thành số 0. Báo cáo/bảng xuất hiển thị các khoảng riêng bên cạnh phân tích lịch sử cả năm. Bộ lọc không thay bộ năm huấn luyện forecast, tránh dùng dữ liệu năm đích để fit mô hình.

## Cấu hình JSON/YAML

```yaml
comparison_periods:
  - start: "2023-10"
    end: "2023-12"
  - start: "2024-10"
    end: "2024-12"
```

Danh sách rỗng `comparison_periods: []` giữ cách xem cả năm. Cấu hình được khóa theo run như ngân sách; muốn đổi khoảng sau khi đã chạy thì tạo nghiên cứu mới.

Trong các run có `report.pdf`, dashboard có **Tải PDF có liên kết**. Đây là file được xuất riêng, khác với việc chụp màn hình hoặc dùng máy in ảo có thể làm mất link. Các loại PDF do dịch vụ tạo phụ thuộc cấu hình/thư viện xuất PDF; nếu không có file này, báo cáo HTML/Markdown vẫn xem được.
