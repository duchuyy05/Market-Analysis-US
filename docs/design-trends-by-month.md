# Sàng lọc mẫu sản phẩm theo tháng

Cập nhật 02/11/2026. Workflow live khám phá **mẫu sản phẩm cụ thể trong phạm vi công ty có thể gia công, in khắc hoặc nhập phôi/decor để hoàn thiện**. Các chiều khám phá gồm hình dáng, kiểu mẫu, cấu trúc, vật liệu, phong cách, công năng thụ động, cách hoàn thiện và hình in/họa tiết. Quần áo, lịch, giấy gói, móc khóa và decor là các nhóm ví dụ; một ví dụ nghệ sĩ hay nhân vật không tự đóng phạm vi còn lại. Các ý tưởng LLM là ứng viên; mức quan tâm và mẫu đối chiếu cần nguồn thật.

| Yêu cầu | Hướng khám phá mẫu |
| --- | --- |
| Khám phá rộng cho công ty | Nhiều nhóm hàng được phép; mỗi nhóm có các mẫu/kiểu để đo, không bắt buộc tất cả phải có hình nhân vật |
| Móc khóa | Hình cắt, cấu trúc shaker/ghép lớp, kiểu treo, vật liệu, kiểu in/khắc, hình minh họa |
| Lịch | Lịch bàn/treo/tờ rời, đóng gáy, bố cục, kiểu giá đỡ, vật liệu/phôi và phong cách thiết kế |
| Decor hoặc phôi nhập để in | Dạng vật thể, kiểu trưng bày/treo, bề mặt in, cấu trúc và cách hoàn thiện |
| Quần áo/đồ vải/giấy gói | Kiểu sản phẩm, cấu trúc, chất liệu, phong cách, hình in hoặc họa tiết |
| Chỉ hỏi hình in/nhân vật/họa tiết | So đúng chủ đề cụ thể trong sản phẩm người dùng đã chọn |

Hồ sơ công ty loại hàng tiêu dùng thực phẩm, mỹ phẩm, dược phẩm, thiết bị công nghệ dùng điện và máy móc. Phụ kiện/phôi thụ động hoặc hình minh họa trên hàng in được xét theo sản phẩm thật; áo in hình máy ảnh không phải máy ảnh, phôi ép nhiệt không phải máy ép.

## Chọn kỳ phân tích

1. Nhập mô tả, ví dụ: “Tìm mẫu sản phẩm được quan tâm tại Mỹ tháng 11 cho công ty gia công/in ấn hoặc nhập phôi để in. Khám phá linh hoạt móc khóa, lịch, giấy gói, quần áo và decor; so hình dáng, kiểu mẫu, cấu trúc và thiết kế; tìm mẫu thật để đối chiếu”. Có thể giới hạn một sản phẩm hoặc một chi tiết khi cần.
2. Chọn **Sàng lọc mẫu trong các tháng đã chọn**, chỉ chọn tháng `11`.
3. Nhập **Năm phân tích mẫu / xu hướng**, ví dụ `2025` để đo tháng 11/2025. Để trống sẽ dùng năm của ngày chốt nếu tất cả các tháng đã chọn đã bắt đầu; nếu chưa, dùng năm liền trước.
4. Năm lịch sử đối chiếu và năm dự báo là lựa chọn riêng. Chúng không ép một mẫu mới phải tồn tại đủ hai năm mới được sàng lọc.

Tháng đang diễn ra được cắt tại ngày chốt và ghi dữ liệu chưa đầy đủ. Năm nhập rõ không bị thay bằng năm khác. Kỳ chưa bắt đầu hoặc không có dữ liệu sẽ chờ xử lý khi Trends bắt buộc; không tự gán mẫu LLM là xu hướng đã đo.

## Luồng xử lý

Mô tả + phạm vi công ty → khám phá nhóm hàng và mẫu/kiểu dáng phù hợp → tìm trang công khai và Related đúng kỳ → mở rộng các mẫu còn thiếu trong trần LLM → đo nguyên keyword trong tháng/năm đã chọn → chọn Top N có phép đo → tìm đúng mẫu Amazon/Shopping → đối chiếu lịch sử, phản hồi và xuất báo cáo.

- `Taylor Swift t shirt` và `Sabrina Carpenter t shirt` là hai ứng viên riêng. Chương trình không đổi cả hai thành `t shirt`, cũng không dùng chuỗi áo nói chung để xác minh một nghệ sĩ cụ thể.
- Khi mô tả hỏi mẫu/kiểu/hình in cụ thể, tên họ sản phẩm chung chỉ dùng dò nguồn và được ghi lý do rõ ràng. Các kiểu dáng, cấu trúc, vật liệu, cách hoàn thiện và phôi cụ thể đều có thể là mẫu hợp lệ; không bắt buộc có tên nghệ sĩ hoặc nhân vật. Nghiên cứu loại sản phẩm tổng quát vẫn giữ keyword chung.
- Sàng lọc đánh giá riêng từng tháng. Mẫu đủ tín hiệu tháng 12 vẫn được chọn khi tháng 10–11 bằng 0; các tháng không đạt hoặc thiếu giữ nguyên trạng thái riêng. Xếp hạng trong từng tháng; ưu tiên tổng hợp theo tháng đủ tín hiệu mạnh nhất và ghi rõ tháng đó. Không trộn với mức phù hợp mùa nhiều năm.
- Một tháng đầy đủ cần nhiều mốc dương độc lập: ít nhất 3 mốc ngày hoặc 2 mốc tuần; nguồn gốc theo tháng cần 1 mốc tháng. Một đỉnh đơn lẻ không được nâng thành trend. Tháng đang diễn ra có ít hơn 3 ngày cần tín hiệu ở đủ số ngày đã quan sát và vẫn ghi kỳ chưa đầy đủ.
- Một kỳ quan sát đủ để so mức quan tâm của một mẫu mới. Dự báo và tính lặp lại mùa vụ vẫn kiểm tra đủ lịch sử riêng; thiếu lịch sử không xóa kết quả quan sát mẫu trong tháng.
- Listing áo trơn không khớp keyword áo có tên ca sĩ; poster cùng ca sĩ cũng không được tính là mẫu áo. Khớp tên vẫn là đối chiếu sơ bộ quy cách/biến thể.
- Trends là tín hiệu tìm kiếm. Nhãn mua và giá Amazon chỉ phản ánh thời điểm listing được thu; chúng không chứng minh doanh số tháng lịch sử được chọn.

## Ngân sách và chạy tiếp

Sàng lọc gọi kỳ phân tích trước. Lịch sử nhiều năm dùng lại checkpoint từng keyword/cửa sổ khi trùng kỳ, không gọi lại chỉ vì sang bước khác. Biểu mẫu dự trù cả sàng lọc và lịch sử, trừ kỳ trùng. Các trần API hiện có giữ nguyên; không tự nâng quota. Preset tiết kiệm dùng 12 ứng viên sàng lọc, tối đa 10 keyword đối chiếu lịch sử và 5 keyword tìm mẫu.

Run cũ có checkpoint `selected_season_history_only` sẽ chạy lại bước sàng lọc khi người dùng bấm chạy tiếp; giữ input, nguồn lịch sử và bộ đếm đã dùng. Muốn đổi tháng/năm/ngân sách, tạo lượt mới. Việc đọc hoặc xuất lại báo cáo không gọi nguồn.

Ví dụ cấu hình cho kỳ đã hoàn tất:

```yaml
brief: "Tìm mẫu móc khóa, lịch và decor phù hợp gia công hoặc nhập phôi để in cho thị trường Mỹ tháng 11"
selling_months: [11]
history_years: [2023, 2024, 2025]
target_year: 2026
trends:
  provider: auto
  required: true
  history_scope: seasonal
  history_months: [11]
  analysis_year: 2025
```

Khi không có mẫu đủ tín hiệu, giao diện hiển thị số đã đo/ít tín hiệu/chưa đo và trần Trends riêng. Có chẩn đoán HTML/JSON từ dữ liệu đã lưu. Nút chuẩn bị lượt mới giữ phạm vi và ngân sách cũ để người dùng chỉnh, không tự tạo lượt mới hoặc gọi API. Hết trần Trends trả phí thì thử lại phần chưa đo chỉ có thể dùng nguồn miễn phí còn lại; không reset bộ đếm.

Sau khi cập nhật, khởi động lại `python run.py`, làm mới trang bằng Ctrl+F5. Frontend kiểm tra các capability `design_month_screening` và `manufacturing_models` để phát hiện backend cũ.
