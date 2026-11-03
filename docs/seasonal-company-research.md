# Nghiên cứu theo mùa cho công ty gia công, thiết kế và in ấn

Cập nhật 30/10/2026. Luồng nghiên cứu mới có thể chỉ thu các tháng đã chọn của từng năm lịch sử và giới hạn sản phẩm trong domain công ty. Các thay đổi cấu hình áp dụng cho nghiên cứu mới; resume không đổi input hoặc đặt lại quota của run đã khóa.

## 1. Đặt phạm vi trên dashboard

1. Dừng server cũ bằng Ctrl+C, chạy `python run.py`, tải lại trang bằng Ctrl+F5.
2. Giữ hồ sơ công ty **gia công / thiết kế / in ấn** và chọn những nhóm hàng thực sự muốn nghiên cứu.
3. Ngay **mục 04**, chọn năm bằng **Khoảng năm liên tiếp** hoặc **Chọn từng năm riêng** rồi nhập, ví dụ `2021,2023,2025`. Được chọn 2–6 năm khác nhau từ 2004, đã hoàn tất trước năm của ngày chốt. Năm dự báo phải sau tất cả các năm lịch sử. Không cần mở phần thiết lập thu gọn để chọn năm.
4. Chọn phạm vi thu thập Trends **chỉ các tháng đã chọn**, rồi tích các ô **Tháng 1–12** hoặc sửa ô danh sách tháng. Hai cách nhập đồng bộ; nút **Chọn tháng 10–12** và **Chọn đủ 12 tháng** giúp chọn nhanh. Cùng bộ tháng được áp dụng cho mỗi năm lịch sử đã chọn. `2023–2025` và `10,11,12` chỉ là mặc định. Với Giáng sinh, nhập tháng bán `11,12`; nếu nghiên cứu cả Q4 thì nhập `10,11,12`.
5. Chọn preset tiết kiệm hoặc preset rộng, kiểm tra dự trù trên form và quota còn lại của tài khoản trước khi bắt đầu.

**Tháng thu thập** và **tháng bán** có vai trò khác nhau. Thu tháng 10–12 cho phép so đầu mùa với cao điểm; tháng bán 11–12 quyết định phần lịch sử được ưu tiên khi chọn hướng sản phẩm. Không cần lấy tháng 1–9 trong chế độ này.

Các khoảng `Từ tháng / Đến tháng` trong phần so sánh vẫn là khoảng tổng hợp báo cáo. Chúng không tự thêm tháng hoặc năm vào phạm vi nguồn của chế độ theo mùa. Nhập một khoảng vượt năm/tháng được phép thu sẽ bị form/cấu hình từ chối; cần sửa khoảng so sánh hoặc chủ động mở rộng phạm vi nguồn. Một khoảng hợp lệ nhưng nguồn trả thiếu vẫn được ghi thiếu trong báo cáo.

**Nếu gặp “Thiết lập Trends không hợp lệ” sau khi cập nhật:** có thể server Python cũ vẫn chạy, trong khi HTML/JavaScript đã đọc từ file mới. Server cũ chưa biết các trường `history_scope` và `history_months`. Dừng server cũ bằng Ctrl+C, chạy lại `python run.py`, rồi nhấn Ctrl+F5. Chỉ tải lại trang chưa đủ để nạp code Python mới. Giao diện hiện kiểm tra khả năng backend ngay khi mở và thông báo rõ nếu server chưa hỗ trợ. Cấu hình sai thật sẽ chỉ ra trường không hỗ trợ hoặc giá trị cụ thể cần sửa.

**Nếu nút bắt đầu bị mờ:** xem trạng thái ngay cạnh nút. Giao diện phân biệt đang kết nối, backend cũ, lỗi kết nối và đang có nghiên cứu chạy. Khi server đã sẵn sàng, bấm **Kiểm tra kết nối lại** để mở khóa; thao tác này chỉ đọc cấu hình và danh sách nghiên cứu, giữ nguyên mô tả, năm/tháng và ngân sách đã nhập. Nó không tạo nghiên cứu hay gọi API nguồn. Tải danh sách lịch sử không thể bỏ qua kiểm tra tương thích. Khi một nghiên cứu còn chạy, cần theo dõi hoặc dừng lượt đó trước.

Dashboard mới khóa độc quyền cổng trên Windows để hai tiến trình không cùng nghe `127.0.0.1:8765` và khiến trang nhận nhầm backend cũ. Chỉ chạy một server; mở thêm terminal chạy cùng cổng sẽ bị từ chối bind. Nếu đang dùng những tiến trình cũ đã mở trước bản sửa, cần đóng đúng tiến trình cũ rồi kiểm tra kết nối lại.

## 2. Nguồn sẽ được gọi ở những ngày nào?

Với lịch sử 2023–2025 và tháng thu thập `10,11,12`, hệ thống tạo đúng ba cửa sổ:

| Năm | Cửa sổ nguồn |
| --- | --- |
| 2023 | 01/10/2023–31/12/2023 |
| 2024 | 01/10/2024–31/12/2024 |
| 2025 | 01/10/2025–31/12/2025 |

Không gọi chuỗi liên tục từ tháng 1/2023 đến ngày chốt hoặc lấy tháng ngoài phạm vi. Từ 02/11/2026, chế độ theo mùa **vẫn sàng lọc mẫu/keyword trong đúng tháng và năm phân tích**, đồng thời Related khám phá trong cùng kỳ khi có ngân sách. Năm phân tích có thể khác các năm lịch sử dùng dự báo. Chọn Top N bằng quan sát mẫu trong kỳ; lịch sử nhiều năm được đánh giá riêng. Xem [workflow mẫu thiết kế theo tháng](design-trends-by-month.md).

Các tháng liền nhau được gom trong một cửa sổ của từng năm. Chọn `11,12` vẫn là một cửa sổ/năm, tương tự `10,11,12`. Chọn `10,12` tạo **hai** cửa sổ/năm; với ba năm là sáu cửa sổ, nên có thể cần nhiều request hơn. Các số tháng áp dụng trong cùng năm lịch sử, không tự biến `[12,1]` thành một mùa vắt qua hai năm.

Chọn năm riêng `2021,2023,2025` và tháng `10,12` tạo đúng sáu cửa sổ tháng 10/tháng 12 của ba năm đó, không thu năm 2022 hoặc 2024 trong chế độ theo mùa. Năm không liên tiếp có thể thiếu mốc so cùng kỳ năm liền trước; hệ thống ghi thiếu, không dùng năm được chọn gần nhất để thay thế mốc đó.

Đổi sang **cả năm** giữ luồng phân tích đủ 12 tháng: lấy chuỗi nhiều năm liên tục, sàng lọc gần đây và đánh giá mùa vụ cả năm như trước. Chuỗi nguồn bao gồm cả các năm xen giữa từ năm đầu đến ngày chốt, dù chọn năm đối chiếu không liên tiếp. Các ô tháng tạm khóa, hiện đủ 12 tháng; chuyển lại theo mùa sẽ khôi phục bộ tháng đã chọn. Cả hai chế độ đều giữ trần request, cache và checkpoint.

## 3. Chọn ít tháng không tự giảm số lượt API

SerpApi tính theo yêu cầu tìm kiếm, không tính một lượt cho mỗi tháng. Một chuỗi nhiều năm liên tục có thể nằm trong một yêu cầu; chỉ Q4 của ba năm cần các cửa sổ riêng. Vì vậy, không khẳng định chỉ lấy ba tháng sẽ tiết kiệm 75% API.

Để so giữa các cửa sổ khác nhau, mỗi yêu cầu lịch sử gồm tối đa **4 keyword + 1 anchor**. Dự trù nhánh theo mùa:

```text
Số lượt lịch sử ≈ ceil(keyword lấy lịch sử / 4) × số cửa sổ nguồn
Tổng SerpApi ≈ lịch sử + Amazon + Shopping + chi tiết
```

Cache hợp lệ có thể giảm request mới. Retry, lỗi nguồn hoặc bổ sung phần thiếu có thể dùng thêm, luôn trong trần. Một lần lấy lịch sử có thể phục vụ cả bảng tháng, chọn hướng, kiểm chứng và dự báo; bước sau dùng lại checkpoint phù hợp.

### Hai cấu hình cho Q4 ba năm 2023–2025

| Thiết lập | Tiết kiệm | Rộng |
| --- | ---: | ---: |
| Ứng viên khám phá | 64 | 64 |
| Keyword lấy lịch sử mùa | 10 | 64 |
| Top keyword tìm mẫu | 5 | 10 |
| Chi tiết Amazon | 2 | 3 |
| Shopping | Bật, 1 keyword | Bật, 2 keyword |
| Tavily | 4 | 6 |
| OpenRouter | 15 | 20 |
| SerpApi tổng | 20 | 70 |
| SerpApi Trends, nằm trong tổng | 11 | 54 |
| Phần giữ cho mẫu hàng | 8 | 14 |
| Dự trù lịch sử | `ceil(10/4) × 3 = 9` | `ceil(64/4) × 3 = 48` |
| Dự trù cả lượt | `9 + 5 + 1 + 2 = 17` | `48 + 10 + 2 + 3 = 63` |

Các con số chưa gồm retry/phục hồi. Preset trên dashboard tính lại theo số năm và các nhóm tháng liền nhau; chọn năm/tháng khác sẽ thay dự trù. Chỉ bấm preset mới áp các trần tương ứng, không có quota mới được cộng vào tài khoản.

**Cấu hình tiết kiệm có 64 giả thuyết nhưng chỉ tối đa 10 keyword được lấy lịch sử mùa**; không có nghĩa 64 keyword đã được kiểm chứng. Phần chưa thu vẫn có trong danh sách ứng viên và ghi thiếu, không tự điền hạng. Nếu muốn hơn 50 keyword có cơ hội được kiểm chứng theo mùa, phải chọn trần lịch sử lớn hơn và ngân sách đủ; nguồn vẫn có thể không đủ tín hiệu cho mọi keyword.

Ở chế độ cả năm, preset rộng trước đó vẫn có dự trù khoảng **47 lượt** cho 64 ứng viên: 16 sàng lọc + 16 lịch sử + 10 Amazon + 2 Shopping + 3 chi tiết, với trần 50/34. Số 47 không áp cho Q4 ba cửa sổ.

## 4. Domain sản phẩm của công ty

Hồ sơ `custom_manufacturing` tổ chức nghiên cứu theo các nhóm có thể gia công, in, thêu, khắc hoặc cá nhân hóa:

| ID cấu hình | Nhóm hàng |
| --- | --- |
| `apparel` | Áo thun, quần áo, phụ kiện vải có thể thiết kế/in/thêu |
| `bags_textiles` | Túi tote, túi/pouch và đồ vải gia dụng |
| `printed_paper` | Lịch, sách/sổ, thiệp, giấy gói và sản phẩm giấy in |
| `keychains` | Móc khóa, thẻ tên và phụ kiện in/khắc |
| `phone_accessories` | Ốp, dây, giá đỡ và phụ kiện điện thoại không cấp điện |
| `home_decor` | Decor nhà cửa, đồ treo, đồ trang trí có thể gia công |
| `gift_accessories` | Phụ kiện gói quà, quà cá nhân hóa và vật dụng in/khắc đơn giản |

Thực phẩm/đồ uống, mỹ phẩm/chăm sóc sức khỏe, máy móc, thiết bị điện/điện tử phức tạp và thiết bị y tế nằm ngoài hồ sơ này. Ví dụ:

| Có thể nghiên cứu | Ngoài domain công ty |
| --- | --- |
| Túi đựng mỹ phẩm | Kem dưỡng, son, nước hoa |
| Cốc in hình cà phê | Cà phê hạt, hộp trà hoặc bánh kẹo |
| Ốp điện thoại, dây đeo, giá đỡ không cấp điện | Sạc, pin dự phòng, tai nghe, loa Bluetooth |
| Áo in hình món ăn, giấy gói quà | Thực phẩm thật hoặc máy móc được nhắc tới trong hình |
| Đồ treo Noel, decor in/khắc đơn giản | Đèn/đồ trang trí điện tử hoặc thiết bị phức tạp |

Bộ lọc áp dụng ở kế hoạch/seed, mở rộng keyword, kết quả listing và điều kiện tạo idea; từ/mẫu bị loại được ghi lý do. Từ có nội dung gợi ý chưa rõ loại hàng giữ trạng thái cần xác minh, không mặc định thành năng lực sản xuất đã được công ty xác nhận. Việc loại trừ dựa trên loại sản phẩm, không loại một túi đựng mỹ phẩm chỉ vì có chữ “cosmetic”.

Một kế hoạch AI có lẫn seed lệch ngành vẫn dùng được những seed phù hợp và ghi riêng phần bị loại, không gọi sửa kế hoạch chỉ vì một từ lệch. Nếu một niche không còn seed hợp lệ, bước hiểu mô tả sẽ yêu cầu sửa kế hoạch trong giới hạn gọi LLM đã đặt; không tự đưa hàng ngoài domain vào nghiên cứu.

Lượt live mới mặc định dùng hồ sơ công ty. Demo offline giữ hồ sơ chung để phát lại đúng dữ liệu cũ; run đã khóa thiếu cấu hình business tiếp tục hồ sơ chung thay vì tự thay đổi phạm vi. Có thể chọn `general` khi chủ động nghiên cứu ngoài domain công ty.

## 5. Cách đọc số liệu mùa

Google Trends chuẩn hóa riêng từng cửa sổ nguồn. Chương trình giữ giá trị gốc và đưa chuỗi phân tích về tỷ lệ:

```text
Chỉ số so anchor = trung bình keyword trong tháng / trung bình anchor cùng tháng × 100
```

Thang **anchor = 100 có thể vượt 100**, khác chỉ số Google Trends gốc 0–100. Các cửa sổ chỉ được ghép khi cùng keyword/anchor/thị trường và phạm vi nguồn phù hợp; anchor thiếu hoặc quá thấp làm phép đo không đủ dữ liệu. Đây là mức quan tâm tương đối với anchor, không phải lượng tìm kiếm tuyệt đối hoặc doanh số.

Với Q4:

- Tháng 1–9 là **không thu thập**, không được thay bằng 0, nội suy hoặc xếp hạng.
- Đỉnh, CV, độ ổn định và tăng trưởng chỉ nói về **kỳ đã chọn**. Không kết luận tháng 12 là đỉnh cả năm khi chỉ thu tháng 10–12.
- Cần ít nhất hai kỳ lịch sử đủ tháng/tín hiệu để tạo dự báo cùng tháng.
- Kiểm chứng hồi cứu cần ít nhất hai kỳ trước để dự đoán một kỳ đã biết. Với 2023–2025, có thể dự đoán thử Q4/2025 từ 2023–2024; chỉ chấm ba tháng đó và so với cùng tháng 2024.
- MAE/WAPE và độ phủ tính trong phạm vi tháng đã chọn. Năm thiếu, mốc cơ sở thiếu, zero-demand hoặc tín hiệu yếu được giữ rõ.
- Chỉ có hai năm có thể đủ dự báo nhưng chưa có một năm giữ lại để kiểm chứng độc lập theo mô hình này. Forecast có số không đồng nghĩa đã được kiểm chứng.

## 6. Cấu hình YAML mẫu: Giáng sinh, phạm vi Q4, tiết kiệm

```yaml
mode: live
brief: >-
  Nghiên cứu quà Giáng sinh tháng 11–12/2026 tại Mỹ cho người yêu và bố mẹ.
  Ưu tiên các sản phẩm công ty có thể in, thiết kế hoặc gia công:
  áo thun, túi tote, lịch/sổ, móc khóa, phụ kiện điện thoại đơn giản và decor.
history_years: [2023, 2024, 2025]
target_year: 2026
selling_months: [11, 12]
business:
  profile: custom_manufacturing
  categories:
    - apparel
    - bags_textiles
    - printed_paper
    - keychains
    - phone_accessories
    - home_decor
    - gift_accessories
trends:
  provider: auto
  required: true
  monthly_rankings: true
  history_scope: seasonal
  history_months: [10, 11, 12]
sources:
  trends: true
  amazon: true
  shopping: true
  web: true
limits:
  candidate_keywords: 64
  monthly_keywords: 10
  top_keywords: 5
  product_details: 2
  shopping_keywords: 1
  serpapi_requests: 20
  trends_serpapi_requests: 11
  serpapi_product_reserve: 8
  tavily_requests: 4
  llm_requests: 15
```

Giá USD chỉ là điều kiện cứng khi được nhập rõ. Nếu mục tiêu là 10–30 USD/món, thêm `price_range: [10, 30]`; không suy ra một mức giá bắt buộc chỉ từ chữ “sinh viên”.

## 7. Code nằm ở đâu?

| File | Trách nhiệm |
| --- | --- |
| `config.py` | Kiểm profile/categories, scope và các tháng được chọn |
| `business/domain.py` | Nhận diện nhóm hàng, loại trừ domain và ngữ cảnh truyền cho LLM |
| `workflow/understand.py`, `keyword_expansion.py`, `broad.py` | Lập kế hoạch và mở rộng keyword trong domain |
| `workflow/planning.py`: `seasonal_windows()` | Gom tháng liền nhau theo năm và dự trù request |
| `workflow/seasonal_history.py` | Chỉ gọi đúng cửa sổ mùa, lưu raw/evidence, chuẩn hóa anchor và checkpoint |
| `forecasting/seasonal.py` | Dự báo và kiểm chứng chỉ các tháng đã thu |
| `analysis/keyword_monthly.py`, `monthly_priority.py` | Độ phủ, hạng trong phạm vi và ưu tiên kỳ bán |
| `workflow/products.py`, `analysis/opportunities.py`, `workflow/ideas.py` | Lọc mẫu ngoài domain và không dùng chúng để tạo idea |
| `ui/assets/index.html`, `app.js` | Scope/tháng, profile/nhóm hàng, preset và dự trù trước khi chạy |

Ảnh vẫn lấy từ cache/CDN công khai và có log riêng; việc dựng lại báo cáo không tự chạy thêm nghiên cứu. Dữ liệu và báo cáo của các run cũ không được thay đổi trong bản bổ sung chế độ này. Xem [keyword theo tháng và ảnh](monthly-keyword-research.md) để biết các bảng xuất và [kiểm chứng lịch sử](history-validation.md) để đọc sai số.
