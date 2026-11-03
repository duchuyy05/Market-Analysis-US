# Cải tiến sau khi kiểm tra lượt chạy mẫu 29/10/2026

Đối chiếu chi tiết tại [run-audit-20261029.md](run-audit-20261029.md). Run mẫu có 13/30 lượt SerpApi: 6 sàng lọc + 2 lịch sử + 2 Amazon + 2 Shopping + 1 chi tiết. Trần Trends riêng 8 đã hết, còn 17 tổng không có nghĩa phần Trends được tự tăng trần. Chỉ hai keyword được chọn, cùng một niche; 19 review là **trích đoạn của cùng ASIN B0DHV7W351**, không phải 19 sản phẩm hay 19 review có đủ sao/ngày.

## Chất lượng thu thập đã sửa

- **Keyword đo thực tế:** prompt yêu cầu loại hàng tự nhiên ngắn, tách người nhận/ngân sách khỏi seed. Khi đo, bỏ bớt mô tả cá nhân hóa/người nhận dễ làm query quá hẹp. `measurement_query` và `measurement_scope` ghi rõ phép đo cho loại hàng rộng, không giả rằng thiết kế cá nhân hóa có cùng mức quan tâm. Những biến thể cùng truy vấn đo chia sẻ một chỗ Top N và một truy vấn tìm mẫu; vẫn giữ liên hệ niche.
- **Zero khác thiếu dữ liệu:** đủ ngày nhưng toàn 0 hoặc chỉ một đỉnh được ghi `low_signal`. Không hủy cache hợp lệ như lỗi mạng. Cần ít nhất ba mốc dương với chuỗi ngày, hoặc hai với chuỗi tuần, để nhận tín hiệu; không suy ra sản phẩm không có nhu cầu chỉ vì query hẹp trả 0.
- **Khôi phục một phần:** còn nhóm chưa có phép đo thì có thể thử một lượt cửa sổ 365 ngày trong trần, kể cả một nhóm khác đã có tín hiệu. Chỉ chọn toàn bộ cửa sổ mới khi độ phủ nhóm/keyword tốt hơn, không trộn hai cửa sổ thành một thang so sánh.
- **Chi tiết sản phẩm:** phân bổ luân phiên giữa các niche/hướng có mẫu. Slot không dùng được chuyển sang mẫu còn lại trong `product_details` và `enrich_per_niche`, không chia cứng cho niche trống. Không bắt buộc gọi hết ngân sách nếu không còn mẫu phù hợp hoặc nguồn không trả trường.
- **Web:** loại homepage, recall/chính sách và trang PR không có loại hàng liên quan; giữ lý do trong exclusions/log. Nếu chưa có keyword có dẫn chứng và còn Tavily, thử tối đa ba truy vấn ngắn theo loại hàng, rồi trích lại có câu nguồn. Không tự bịa keyword khi trang chưa đủ thông tin. Nguồn TikTok/Facebook vẫn là trang được lập chỉ mục, chưa phải feed doanh số.
- **LLM:** model cấu hình trả rỗng vì hết token sẽ không được thử lại ở mọi bước trong cùng run; dùng model free dự phòng trong trần. Brief Noel không còn tự mặc định bán cả năm khi người dùng chưa chọn tháng; giữ tháng do người dùng nhập.

Đây là thay đổi cho các lượt phân tích mới, được kiểm tra bằng fixture/offline. Lượt mẫu đã lưu không được âm thầm chạy lại hoặc tiêu quota để tạo thêm dữ liệu. Báo cáo xuất lại giữ dữ liệu nguồn cũ, làm rõ phạm vi và phần thiếu.

## PDF, review và khoảng thời gian

PDF mẫu không giữ link annotation và không trích được text. Bộ xuất mới dựng PDF từ text/bảng với link thật; dashboard có **Tải PDF có liên kết**. Có thể chọn/copy text, nhấn tên mẫu hoặc link nguồn. Thư viện PDF dùng ReportLab; môi trường mới cài bằng:

```powershell
python -m pip install -e ".[pdf]"
```

Máy hiện tại có runtime PDF riêng trong `.artifact-runtime/pdf-deps`, không sửa package toàn cục. Nếu thiếu thư viện/font, HTML/Markdown vẫn xuất và `pdf-status.json` ghi lý do.

Review ghi tên mẫu, ASIN/định danh, loại trích đoạn, nguồn; sao/ngày không có từ nguồn được ghi thiếu, không mượn sao sản phẩm làm sao review. Báo cáo có thêm độ phủ nhóm/sản phẩm và bảng ngân sách để số mẫu không che mất phạm vi còn yếu.

[Chọn các khoảng tháng lịch sử](comparison-periods.md): ví dụ 10–12/2023, 10–12/2024, 10–12/2025. Tổng hợp trên cùng chuỗi Trends để giữ thang nhất quán và không nhân request theo số khoảng; không tạo giá/review Amazon quá khứ.

## Chỉnh ngân sách khi cần nghiên cứu sâu hơn

Tổng SerpApi, trần con Trends, phần giữ cho mẫu, số ứng viên, Top N, số keyword Shopping và số chi tiết là các giới hạn riêng. Tăng tổng 20 lên 30 mà vẫn để Trends 8 không tăng lượt dành cho Trends. Dashboard cho chỉnh từng giới hạn trước run; report/log ghi đã dùng và còn lại. Hãy cân đối theo số nhóm/keyword cần đối chiếu thay vì đặt mục tiêu phải tiêu hết API.

Run cũ khóa input và bộ đếm; sửa ngân sách/khoảng thời gian thì tạo nghiên cứu mới. Chỉ xuất lại báo cáo từ dữ liệu đã lưu bằng:

```powershell
python run.py report --run-id run-20261029T013332-efc9ee
```

Lệnh trên không gọi nguồn hoặc tạo thêm sản phẩm. Dừng server cũ, chạy `python run.py` và Ctrl+F5 để tải đủ giao diện/route mới.
