# Sửa lỗi LLM ở bước hiểu mô tả

## Lượt 02/11/2026: một seed chưa phù hợp không làm hỏng cả kế hoạch

Run `run-20261102T032547-c8a873` có hai nguồn trả 429 rồi nhận một kế hoạch với nhiều seed hợp lệ, nhưng một seed `acrylic keychain custom shape` bị bộ kiểm tra chất lượng coi là mô tả catalog. Bộ kiểm tra cũ ném lỗi cho cả bước. Nay cấu trúc JSON, loại dữ liệu, phạm vi công ty và niche rỗng vẫn được kiểm tra chặt; riêng seed AI kém chất lượng được loại riêng khi niche còn seed hợp lệ. `seed_quality_adjustments` lưu nguyên cụm bị loại và lý do, không tự đổi cụm hoặc coi các giả thuyết còn lại là trend đã xác minh.

Phản hồi đã lưu được tái kiểm tra đúng payload để dùng lại mà không gọi catalog/inference mới. Hàm `pipeline.recover_understanding()` chỉ khôi phục checkpoint hiểu mô tả đang lỗi, không chạy các nguồn tiếp theo; giữ input, input hash, raw và usage, đưa lượt về trạng thái chờ người dùng chạy tiếp. Lượt trên đã khôi phục 5 niche/49 seed; OpenRouter giữ 3/8. Các câu AI lặp lại phạm vi công ty được kiểm tra bằng bộ lọc domain thay vì bắt câu đó phải xuất hiện nguyên văn trên listing; điều kiện thật do người dùng nhập vẫn giữ nguyên.

## Lượt 30/10/2026: JSON đúng cú pháp nhưng model trả 10 niche

Run `run-20261030T084751-aea96a` dùng mô tả về quà Giáng sinh, móc khóa, decor và giấy gói quà. Xing4.0 và Gemma trả HTTP 429. Dots trả JSON có 10 niche, 1.242 completion token, `finish_reason: stop` và 0 reasoning token. Validator yêu cầu 1–5 niche nên lượt khôi phục cuối bị từ chối. Đây không phải lỗi API key hoặc hết trần token. Ba request đã thử vẫn nằm trong bộ đếm 3/8 của ứng dụng.

Bản sửa giữ tối đa 5 nhóm đầu theo thứ tự phản hồi khi model đề xuất 6–20 nhóm. `plan_adjustments` ghi số nhóm gốc, cách giới hạn và toàn bộ `deferred_niches`; raw giữ nguyên. Thứ tự đó không phải xếp hạng thị trường. Niche người dùng chọn rõ vẫn được giữ đúng phạm vi; thiếu seed, seed sai, điều kiện sai hoặc hơn 20 nhóm không được tự chấp nhận. Prompt cũng nhấn mạnh danh sách năng lực công ty không phải yêu cầu tạo một niche cho mỗi danh mục.

Khi resume, nhánh `llm/saved_plan.py` chỉ xem lại phản hồi lỗi niche của chính run. Payload phải khớp input hiện tại, phản hồi phải vượt toàn bộ kiểm tra hiện tại và có điều chỉnh số niche hợp lệ. Trường hợp đạt được dùng lại mà không tải catalog/gọi inference hoặc tăng bộ đếm API; raw và usage cũ giữ nguyên. Đổi input hoặc phản hồi còn sai thì không dùng đường này. Log ghi `llm_saved_plan_revalidated` và `plan_normalized`.

Chạy tiếp bằng tiến trình CLI mới để nạp code đã sửa:

```powershell
python run.py resume --run-id run-20261030T084751-aea96a
```

Nếu chạy tiếp qua dashboard, cần khởi động lại server sau cập nhật code Python. Riêng bước understand của mẫu này đã được kiểm tra lại từ raw mà không gọi API; pipeline thực tế vẫn chưa được chạy tiếp trong lượt sửa. Các bước sau khi resume có thể gọi nguồn trong ngân sách đã khóa. Kiểm thử liên quan đạt 133 bài bằng fixture/transport giả, không dùng quota nghiên cứu thật.

Đối chiếu run `run-20261029T105559-37467a` ngày 29/10/2026: hai request OpenRouter đều nhận phản hồi, nhưng cả hai có `finish_reason: length` và `message.content: null`. Model cấu hình là `recursive/flint-v1.0:free`; router dự phòng đã chọn `nvidia/nemotron-3.5-lightning:free`. Token đã được dùng cho reasoning mà chưa có JSON hiển thị. Đây không phải bằng chứng API key sai.

Code cũ coi HTTP thành công là cache có thể dùng lại, không sửa phản hồi `null`, và kiểm tra thiếu các trường kế hoạch trước khi chấp nhận JSON. Vì vậy resume có thể dùng lại chính phản hồi rỗng cũ.

## Luồng đã sửa

1. Đọc metadata model công khai từ `https://openrouter.ai/api/v1/models`, cache sáu giờ. Chỉ chọn biến thể `:free`, trả text, hỗ trợ JSON, mức giá ghi nhận bằng 0, không bắt buộc reasoning và phù hợp trần token.
2. Giữ ưu tiên model người dùng cấu hình khi phù hợp. Nếu model bắt buộc reasoning hoặc đã trả nội dung rỗng/hết token trong run thì tránh cho tác vụ này. Khi cần lựa chọn thứ hai, ưu tiên model từ vendor khác để giảm lệ thuộc một nguồn đang giới hạn.
3. Gửi `reasoning.enabled: false` khi model hỗ trợ; `exclude: true` chỉ có nghĩa ẩn reasoning, không phải tắt tiêu thụ token. Vẫn giữ trần `max_output_tokens` đã cấu hình, không tự nâng vô hạn.
4. Kiểm tra nội dung và kết thúc trước khi parse JSON. Có phân loại `token_limit`, `empty_content`, `empty_choices`, `refusal`, `invalid_json`, `invalid_schema`.
5. Kế hoạch phải có category, 1–5 niche, seed tiếng Anh hợp lệ, tháng/giá/điều kiện đúng kiểu. Các giá trị người dùng nhập rõ được ưu tiên; chỉ chuẩn hóa dấu câu/khoảng trắng, không tự dịch hoặc bịa keyword khi thiếu.
6. Mỗi tác vụ có tối đa hai lựa chọn đầu và một lượt khôi phục cuối. Nếu đã nhận được JSON sai dữ liệu, ưu tiên sửa bằng chính model đã trả JSON, tránh model vừa lỗi 429. Nếu cả hai nguồn đầu bị 429, lượt cuối có thể thử một vendor khác đã được xác nhận tương thích; không phát sinh lượt thứ tư. HTTP retry khác vẫn do Client quản lý và đều tính trong trần request tổng của run. OpenRouter 429 không được thử lại tức thì cùng model trước khi chuyển nhánh.
7. Phản hồi không dùng được bị đánh dấu cache lỗi. Bản lỗi được giữ riêng trong `raw/openrouter/*.invalid-*.json`, tránh bị lần gửi mới ghi đè mất bằng chứng. Không lưu reasoning nội bộ.
8. Hết trần OpenRouter trả lỗi ngân sách thật; HTTP 401/403/429 không bị đổi thành thông báo JSON chung. Lời giải thích lỗi HTTP do provider trả được lưu ở mức giới hạn và che key.
9. Sau resume thành công, lỗi cũ vẫn còn trong lịch sử/log, nhưng không tiếp tục được liệt kê như lỗi hiện tại của bước đã hoàn tất trên dashboard.

Metadata model là request GET công khai, không dùng key và không cộng quota completion. Khi hết ngân sách completion thì không tải metadata mới; test dùng transport giả cũng không gọi mạng. Metadata có thể cũ hoặc model đang hết năng lực phục vụ, nên mọi phản hồi vẫn được kiểm tra thật.

## Bổ sung ngày 30/10/2026: nguồn 429 và model chọn nhầm

Run `run-20261030T022343-210e2c` đã gọi Xing4.0 qua Phala và Gemma qua Google AI Studio; cả hai trả HTTP 429, tổng bốn lượt do code cũ có retry ngay trên cùng model. Chỉ từ mã lỗi này chưa kết luận được tài khoản đã hết quota ngày. Không có dữ liệu SerpApi/Tavily được gọi trong lượt đó.

Run trước `run-20261030T021331-cf3ca4` đã nhận JSON từ Dots nhưng seed là tiếng Việt. Nhánh sửa khi đó quay lại Gemma đã 429; lựa chọn này đã được sửa. Sau đó log còn ghi người dùng chọn model HeyGen giọng nói và model embedding, không phù hợp endpoint chat; bộ chọn mới kiểm metadata để tránh gửi những model đó khi có danh mục model hợp lệ.

Log `llm_task` hiện tách `configured_model` với `model`/`candidate_models` thực sự chuẩn bị gọi. Log HTTP lưu `requested_model`, tên provider, chi tiết upstream và `Retry-After` khi có; các trường này vẫn được che key và giới hạn kích thước. Dòng model cấu hình không còn được dùng làm nhãn gây hiểu nhầm rằng Flint luôn được gọi.

Lượt `cf3ca4` đã dùng đủ 10/10 request OpenRouter sau nhiều lần chạy tiếp; không đặt lại bộ đếm để chạy thêm. Lượt `210e2c` tại thời điểm kiểm tra mới dùng 4/8; vẫn có thể resume trong trần cũ sau khi nguồn phục hồi và server đã nạp bản sửa. Việc có lượt còn lại trong run không bảo đảm quota tài khoản/provider đang sẵn sàng.

## Chạy lại lượt bị lỗi

Dừng server cũ bằng Ctrl+C để Python nạp code mới:

```powershell
python run.py
```

Nhấn Ctrl+F5 trong trình duyệt, mở lượt bị lỗi rồi chọn **Chạy tiếp phần thiếu**. Hoặc dùng terminal:

```powershell
python run.py resume --run-id run-20261029T105559-37467a
```

Resume giữ input, các trần và request đã dùng của run. Hai lượt OpenRouter của lần lỗi ban đầu vẫn được tính; không đặt lại bộ đếm. Khi bước hiểu thành công, workflow có thể tiếp tục gọi Trends/Tavily/SerpApi theo cấu hình đã khóa. Muốn đổi trần/phạm vi thì tạo nghiên cứu mới.

Không cần đổi API key chỉ vì gặp output rỗng. Nếu log là HTTP 401/403 thì kiểm quyền/key; HTTP 429 thì xem lời giải thích nguồn để phân biệt quota tài khoản hay nguồn model đang giới hạn. Không tự tăng trần của run để xử lý giới hạn ở tài khoản nhà cung cấp.

## Đã kiểm tra gì?

- Hai model cùng trả `null`/hết token: tạo lại nội dung bằng request khác, không cố parse `null` như JSON.
- Resume sau lỗi vẫn giữ input hash/usage, bỏ cache hỏng; chưa gọi nguồn sản phẩm khi hiểu mô tả chưa hoàn tất.
- JSON đúng cú pháp nhưng sai category, seed, tháng, giá hoặc điều kiện: đi qua nhánh kiểm tra/sửa thay vì chết sau khi đã chấp nhận kế hoạch.
- Giữ lỗi hết ngân sách, lỗi auth và lời giải thích 429; raw/log được che key.
- Kiểm metadata, cache, model miễn phí, dung lượng và timeout bằng HTTP giả; không gọi API thật trong test.
- Dashboard ẩn lỗi đã giải quyết khỏi danh sách lỗi hiện tại, vẫn giữ lịch sử.

Phép thử nguồn thật được giới hạn **hai request OpenRouter free**, chỉ bước hiểu input trong thư mục chẩn đoán riêng. Cả hai trả HTTP 429, nên chưa xác nhận được một kế hoạch thành công từ nguồn thật trong lần kiểm tra này. Không gọi SerpApi/Tavily và không sửa input/usage của run gốc. Kết quả test không được công bố thành dữ liệu thị trường.

Nguồn kỹ thuật: [OpenRouter reasoning và trần token](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens), [metadata model](https://openrouter.ai/docs/api/api-reference/models/list-all-models-and-their-properties), [provider và yêu cầu hỗ trợ tham số](https://openrouter.ai/docs/guides/routing/provider-selection).
