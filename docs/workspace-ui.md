# Giao diện không gian nghiên cứu

Cập nhật 29/10/2026: thêm tự động dự phòng Trends có ngân sách, trạng thái chờ khi chưa đo được và chi tiết mở được ở từng ô tiến trình.

## Mở ứng dụng sau khi cập nhật

Dừng server cũ bằng Ctrl+C, chạy `python run.py`, mở http://127.0.0.1:8765 rồi nhấn Ctrl+F5. Không cần cài thêm thư viện cho giao diện. Chỉ bấm bắt đầu nguồn thật mới tiêu thụ API; chuyển màn hình, lưu mục, biên tập và xuất CSV không gọi nhà cung cấp.

## Thanh điều hướng

- **＋ Nghiên cứu mới:** mở ô nhập mô tả mới. Lượt đang chạy vẫn hiển thị ở thanh tiến trình chung.
- **Lịch sử nghiên cứu:** tìm theo chủ đề/mã nghiên cứu, lọc trạng thái, mở lại hoặc chạy tiếp.
- **Thư viện sản phẩm:** xem mẫu từ các nghiên cứu, gồm dữ liệu ở checkpoint tìm mẫu/lấy chi tiết khi chưa có dataset cuối.
- **Báo cáo:** mở báo cáo gốc, catalog và bản biên tập.
- **Đã lưu:** nghiên cứu được đánh dấu sao, kèm nút mở riêng các mẫu sản phẩm đã lưu.

Mục đang chọn có trạng thái màu, icon và thẻ có chuyển động khi tương tác. Giao diện tự giảm chuyển động nếu hệ điều hành yêu cầu reduced motion. Trên màn hình nhỏ, thanh điều hướng chuyển thành hàng ngang.

Khi xem chi tiết/báo cáo, nút **× Đóng** nằm ở thanh trên cùng và bám theo khi cuộn. Bấm để quay lại danh sách vừa mở (Báo cáo, Lịch sử, Đã lưu hoặc Thư viện sản phẩm), rồi chọn mục khác. Đóng chỉ rời phần xem; không xóa kết quả và không dừng lượt nghiên cứu đang chạy.

## Chọn ngân sách API

Ngay dưới mô tả có ba ô chọn riêng **SerpApi**, **Tavily**, **OpenRouter**. Chọn số lượt có sẵn hoặc **Tùy chỉnh…** để nhập số nguyên 0–1000. Nút **Dùng mặc định** tải lại giá trị mặc định đã nhận từ server.

Mặc định lấy từ `DEFAULT_LIMITS` trong `src/market_research/config.py`: SerpApi 20, Tavily 3, OpenRouter 8. Chọn 0 sẽ không gọi nhà cung cấp đó. Nếu OpenRouter bằng 0, phải nhập keyword tiếng Anh trong phần thiết lập để code có seed rõ ràng mà không nhờ LLM diễn giải.

Phần thiết lập cho chọn số hướng sản phẩm mỗi niche. Trends có hai giới hạn riêng: **SerpApi tối đa cho Trends** (mặc định 8) và **Dành tối thiểu SerpApi cho mẫu hàng** (mặc định 10). Trần thực tế của Trends là `min(trần Trends, max(0, trần tổng − phần dành mẫu hàng))`, gồm retry. Ví dụ tổng 20 / Trends 8 / dành mẫu 10 thì Trends tối đa 8, còn ít nhất 12 lượt ban đầu cho mẫu; đây không phải chia đôi ngân sách. Nếu tổng không lớn hơn phần dành mẫu, dự phòng trả phí không có lượt. Mọi lượt vẫn nằm trong trần tổng.

Nguồn Trends mặc định **Tự động: miễn phí → SerpApi dự phòng**. Chế độ **Chỉ miễn phí** không chuyển sang SerpApi; **Chỉ SerpApi** vẫn chịu trần con và phần dành mẫu hàng. Trần Trends SerpApi bằng 0 cũng ngăn dự phòng trả phí. Checkbox **Shopping** bổ sung các nhà bán/sản phẩm ngoài Amazon; ô số keyword Shopping mặc định 2, nên Top 10 thường là khoảng 10 tìm Amazon + 2 Shopping khi bật, chưa gồm chi tiết/retry.

Trong màn hình tiến trình có bộ đếm **đã dùng / trần** cho từng provider. Đây là số lần thử gửi request, gồm lỗi và retry, không đồng nghĩa credit thực tế nhà cung cấp đã trừ. Cache không tính lượt mới. Ứng dụng chưa đồng bộ quota tài khoản. Resume dùng lại trần đã khóa của run cũ.

## Chọn Top keyword tìm sản phẩm

Ngay dưới ngân sách API có ô **Top keyword đưa sang tìm sản phẩm**: Top 3/5/10/15/20/30/50 hoặc **Tùy chỉnh…** từ 1–100. Mặc định 10 từ `DEFAULT_LIMITS["top_keywords"]` trong `src/market_research/config.py`; CLI có thể ghi đè bằng `limits.top_keywords`. Chọn trước khi bắt đầu; demo Q4 cũng dùng số này.

Luồng live mới hiểu mô tả → khám phá seed/web/related → **sàng lọc Trends US theo batch chung anchor** → gắn nhãn nhóm → **chọn Top N** → Amazon → chi tiết → lịch sử → báo cáo. Điểm/hạng do Python tính trong tập ứng viên có phép đo; khi yêu cầu Trends bật, chỉ chọn keyword đo hợp lệ và có thể ít hơn Top N. Nếu không có phép đo hợp lệ sau các nguồn dự phòng, lượt chuyển **Chờ dữ liệu Trends**, chưa tìm sản phẩm hoặc xuất báo cáo như đã phân tích xu hướng. Xem [công thức, nguồn và giới hạn](workflow-discovery.md).

Các truy vấn giống nhau được tính là một keyword, vẫn giữ các hướng/niche cùng dùng truy vấn. Nếu thiếu ứng viên thì dùng số hiện có. Live mới giữ từng keyword đã chọn, tránh bị LLM gom nhóm làm mất; số hướng/niche dùng cho nhãn nhóm. Demo/run cũ vẫn chọn đại diện theo luân phiên niche. Một keyword có thể gọi nhiều nguồn/lấy chi tiết, nên **Top 10 không đồng nghĩa 10 lượt API**; trần kiểm tra riêng.

Kết quả có `selection` và `keyword_selection` trong dataset, cùng `tables/keyword_selection.csv`/`.json` ghi keyword được chọn, thứ tự tìm và lý do loại do trần. Tiến trình sau khi hoàn tất hiện riêng số **Từ khóa khám phá** và **Keyword tìm mẫu**. Muốn đổi Top, tạo run mới; resume giữ input/checkpoint của run cũ.

## Mở từng ô tiến trình để xem dữ liệu và log

Mỗi ô như **Hiểu mô tả**, **Khám phá từ khóa đa nguồn**, **Sàng lọc Trends US** là một nút, dùng được bằng chuột hoặc bàn phím. Nhấn để mở khung chi tiết ngay dưới danh sách; nhấn lại ô đó hoặc **×** để đóng. Chỉ bước đang mở được tải thêm chi tiết khi màn hình cập nhật, không gọi nhà cung cấp API.

- **Kết quả / keyword:** chủ đề, nhóm và seed LLM trả về; keyword khám phá kèm nguồn gốc; chỉ số/hạng Trends; lựa chọn Top N; mẫu và trạng thái nguồn; lịch sử và phần thiếu tương ứng.
- **Nhật ký xử lý và lỗi:** thời điểm, lần bắt đầu/kết thúc, request/cache, nguồn dự phòng, phản hồi LLM đã giới hạn, warning/error và lựa chọn đã thực hiện. Mở **Dữ liệu xử lý / phản hồi** của từng sự kiện để xem nội dung chi tiết.
- Với run cũ chưa ghi event, vẫn xem được kết quả checkpoint và warning/error sẵn có; không tạo log giả cho thời điểm trước.
- Endpoint `/api/runs/<run_id>/stages/<stage>` chỉ chấp nhận bước workflow đã biết, giới hạn dữ liệu/log trả về, che API key và bỏ reasoning/trace. Nó không cho đọc tùy ý đường dẫn hay `.env`. Khung dùng văn bản thuần, không thực thi HTML/script từ nguồn.

Màu luôn đi cùng nhãn chữ: xanh **Hoàn tất**, tím **Đang chạy**, vàng **Có phần thiếu**, đỏ **Cần xử lý lỗi**, vàng đậm **Chờ xử lý**, xám **Chưa chạy**. Khi **Chờ dữ liệu Trends**, mở ô sàng lọc để xem nguồn đã thử; dùng **Thử lại bước Trends** khi lỗi tạm thời đã hết. Nếu phải đổi nguồn/ngân sách, nút **Điều chỉnh ngân sách trong lượt mới** đưa về biểu mẫu; run cũ vẫn khóa input và bộ đếm.

## Dừng và chạy tiếp

Bấm **Dừng nghiên cứu** trong tiến trình hoặc **Dừng chạy** trên thanh thông báo chung. Giao diện chuyển sang **Đang dừng…**, sau đó **Đã dừng**.

Yêu cầu HTTP đã gửi không thể thu hồi quota. Ứng dụng đợi yêu cầu hiện tại hoàn tất hoặc timeout, lưu phản hồi/raw và ngăn yêu cầu tiếp theo, kể cả retry. Các checkpoint trước đó được giữ. Nếu dừng giữa một stage, stage đó có thể cần chạy lại, nhưng phản hồi thành công đã lưu được đọc từ cache.

Bấm **Chạy tiếp phần thiếu** để tiếp tục cùng run. Muốn đổi input hoặc ngân sách, tạo nghiên cứu mới. Khi tắt server bằng Ctrl+C, các worker trong server cũng nhận tín hiệu dừng. Nút dừng chỉ điều khiển worker thuộc server hiện tại; không kết thúc một CLI/process khác đang chạy riêng.

## Bảng sản phẩm và CSV

- Lọc theo nghiên cứu, nguồn, mẫu đã lưu, tên/ASIN/nhà bán và khoảng giá USD. Nhấn **Áp dụng** hoặc Enter ở ô tìm kiếm.
- Nhấn tiêu đề **Sản phẩm**, **Giá**, **Điểm sao**, **Đánh giá**, **Ngày quan sát** để sắp xếp riêng một cột và đổi tăng/giảm. Giá và lượt đánh giá sắp xếp theo số; khi chỉ sắp xếp giá thì giá chưa biết nằm cuối. Giá khác tiền tệ giữ nhóm riêng.
- Khung **Sắp xếp nhiều tiêu chí** nằm ngay trên bảng: chọn cột và chiều sắp xếp cho từng mức, **＋ Thêm cột** (tối đa 5), dùng **↑ ↓** đổi ưu tiên hoặc **×** bỏ tiêu chí, rồi **Áp dụng sắp xếp**. Mỗi cột chỉ chọn một lần. Có hai lựa chọn nhanh **Sao cao → Giá rẻ** và **Giá rẻ → Sao cao**.
- Các tiêu chí áp dụng từ trên xuống: ví dụ sao giảm dần rồi giá tăng dần sẽ ưu tiên nhiều sao, cùng điểm sao mới so giá. Có thể thêm lượt đánh giá giảm dần làm tiêu chí thứ ba. Ô thiếu ở cuối trong nhóm đồng hạng của các tiêu chí trước. CSV dùng chính thứ tự nhiều cột này.
- Bảng chia trang 40 dòng. Nút **Xuất CSV** xuất **toàn bộ dòng phù hợp bộ lọc**, theo đúng thứ tự hiện tại, không chỉ trang đang xem.
- CSV có BOM UTF-8, tiêu đề tiếng Việt, ngày quan sát, nguồn/link và mã bằng chứng. Ô thiếu để trống, số 0 vẫn là số 0. Văn bản có thể bị Excel hiểu thành công thức được thêm dấu nháy đơn.
- CSV là dữ liệu thuần, không lưu màu/kiểu chữ. Bảng trên giao diện có định dạng dễ đọc và sắp xếp tương tác; CSV mở được bằng Excel để xử lý tiếp.

Mẫu trùng giữa các nghiên cứu giữ thành các quan sát riêng, với cột nghiên cứu và ngày để đối chiếu. Sao lưu gắn với mẫu trong đúng run đó, không tự gộp số liệu nhiều thời điểm.

## Biên tập và lưu báo cáo

Chọn **Biên tập** ở thẻ báo cáo hoặc **Biên tập báo cáo** trong tiến trình. Sửa tiêu đề/nội dung Markdown rồi bấm **Lưu bản biên tập**. Khi rời bản đang sửa chưa lưu, trình duyệt hỏi trước.

Các file được tạo:

| Vị trí | Nội dung |
|---|---|
| `outputs/<run_id>/report.md`, `report.html` | Báo cáo Python gốc, giữ riêng |
| `outputs/<run_id>/report-edited.md`, `report-edited.html` | Bản biên tập gần nhất, tải/mở được ngay |
| `data/runs/<run_id>/edits/*.json` | Từng lần lưu tiêu đề/nội dung và thời gian |
| `data/workspace/state.json` | Mục đã lưu và metadata tiêu đề biên tập |

Lưu bản biên tập tự đánh dấu nghiên cứu vào mục đã lưu. Bản HTML biên tập hỗ trợ tiêu đề, đoạn văn, bảng và link an toàn; không chạy HTML/script được nhập. Đây là bản trình bày do người dùng sửa, không chỉnh dataset/evidence và không chạy lại kiểm chứng số liệu. Biểu đồ của bản Python gốc vẫn nằm trong báo cáo gốc; bản biên tập không tự dựng lại biểu đồ từ Markdown.

## Các phần code mới

- `control.py`: tín hiệu dừng và exception riêng, không xem thao tác dừng là lỗi nguồn.
- `providers/client.py`: kiểm tra tín hiệu trước request/retry và sau khi lưu phản hồi.
- `pipeline.py`: giữ checkpoint, ghi trạng thái cancelled và hỗ trợ resume.
- `ui/server.py`: API ngân sách, bộ đếm, dừng, lưu mục, bảng sản phẩm và biên tập.
- `ui/workspace.py`: dữ liệu mục đã lưu, lọc/sắp xếp, xuất CSV và lưu bản báo cáo biên tập.
- `ui/assets/`: điều hướng, animation, biểu mẫu, tiến trình và bảng dữ liệu.
