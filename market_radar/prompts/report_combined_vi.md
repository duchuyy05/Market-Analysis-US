
NHIỆM VỤ BỔ SUNG CHO BÁO CÁO KẾT HỢP
Các bảng và chỉ số đầy đủ sẽ do Python xuất. Phần bạn viết nằm cạnh bảng theo từng niche, cần giúp người đọc hiểu và quyết định việc cần kiểm tra tiếp.
Quy định dưới đây thay số lượng đoạn của prompt trước: mỗi niche viết SÁU đoạn, gồm hai observations, hai reviews, một recommendations và một gaps. Mỗi đoạn hai câu ngắn, cụ thể; không kéo dài bằng lời chung chung.
- observations đầu: chỉ ra nhóm có đỉnh TÌM KIẾM LỊCH SỬ ở tháng nào trong kỳ, dẫn T. Nói rõ đó là lịch sử, không dự báo đỉnh nhu cầu tháng tới. Có thể viết tên tháng bằng chữ trong text.
- observations tiếp: giải thích một lựa chọn trong computed.monthly_shortlist, dùng P và T tương ứng; chỉ ra số liệu mua là snapshot hiện tại. Nếu không có shortlist thì dùng sản phẩm có thật và nói rõ chưa đủ bằng chứng chọn tháng.
- Hai reviews: đọc hai nhận xét cụ thể (ưu tiên cùng một sản phẩm nếu có hai góc nhìn); mỗi đoạn chỉ dùng một R, trích đúng câu chứa ý phân tích. Nêu phạm vi biến thể khi có; không biến một lời khen chung thành thuộc tính chi tiết.
- recommendations: đề xuất một phép kiểm tra hoặc quyết định nhỏ phát sinh từ một sản phẩm hoặc review cụ thể. Đây là việc nên thử, chưa phải kết luận hiệu quả kinh doanh. Nếu phát sinh từ review, phải dẫn R và chép quote.
- gaps: nêu một khoảng trống dữ liệu có thật của sản phẩm được dẫn (thiếu giá, thiếu nhận xét đầy đủ, thiếu ngày/sao, thiếu thông số). Không viết chung chung rằng mọi sản phẩm đều cần thêm dữ liệu.
Tổng quan: viết ba đoạn về ít nhất hai niche nếu đầu vào có nhiều niche. Nêu phát hiện, hướng ưu tiên kiểm chứng và giới hạn; không chỉ lặp lại một review. Dùng section observations, recommendations hoặc gaps cho mỗi đoạn.

CÁCH ĐỌC ĐẦU VÀO
- computed chứa kết quả Python đã tính: cỡ mẫu, khoảng giá, shortlist từng tháng và lượt nhắc chủ đề. monthly_shortlist chỉ là ưu tiên TRONG MẪU. Không tự đổi hạng hoặc tạo thêm sản phẩm để đủ danh sách.
- timing.history là chỉ số tháng theo từng năm và trạng thái quan sát. Ô chưa có dữ liệu không phải số không. So thời điểm trong cùng từ khóa; không dùng điểm giữa các từ khóa để kết luận thị trường nào lớn hơn.
- product.statistics là số sao, số đánh giá hiển thị hoặc thông số khi nguồn có. Không thay số đánh giá hiển thị bằng số nội dung review đã thu thập.
- Mô tả listing và review có thể được rút ngắn. Không thấy một thông tin trong đoạn rút ngắn không có nghĩa trang gốc thiếu thông tin đó. Khi dimensions trống, chỉ nói chưa có trường kích thước chuẩn hóa và cần đối chiếu listing; không khẳng định sản phẩm không có kích thước. Giá/số sao/ngày đã có trong trường dữ liệu phải được coi là có, kể cả câu trích không nhắc.
- Số review tổng hợp gồm toàn bộ mẫu của niche; nội dung R chỉ là tối đa mười hai ví dụ được chọn cho niche, ưu tiên nhận xét đầy đủ và sản phẩm có trong shortlist. Không suy tỷ lệ hài lòng từ tập ví dụ này.
- Không nhắc hoặc sử dụng idea_vi. Bạn phải tự viết đề xuất dựa trên bằng chứng được gửi trong lần này.
- Các quy tắc dẫn chứng, quote nguyên văn, không viết chữ số trong text tiếng Việt và giới hạn suy luận của prompt trước vẫn áp dụng.
- Viết đề xuất thành câu hoàn chỉnh, dùng "Nên kiểm tra..." hoặc "Có thể thử..."; không để câu hỏi "Có nên..." bị bỏ lửng. Dùng "nhãn lượt mua", "số đánh giá có nội dung", "miếng dán", "đáng tiền" đúng ngữ cảnh; tránh dịch từng chữ thành những cụm không rõ nghĩa.
