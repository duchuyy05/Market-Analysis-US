# Dữ liệu thị trường Mỹ ngoài Amazon — phương án không thêm Apify

Đối chiếu tài liệu chính thức: **29/10/2026**. Không gọi API trả phí hoặc dùng key của dự án trong nghiên cứu này. Khả năng được mô tả bởi nhà cung cấp chưa phải kết quả kiểm thử live trên máy hiện tại.

Dự án hiện có SerpApi, Tavily và OpenRouter. Nhánh đã triển khai trước đợt sửa này dùng Tavily tìm trang công khai TikTok/Facebook/Etsy/Walmart/Pinterest/eBay rồi trích keyword có câu nguồn. Các adapter Walmart/eBay chuyên dụng và thu thập số liệu TikTok Shop/Meta bên dưới là **đề xuất**, chưa được coi là đã triển khai. Luồng xử lý lỗi Trends và ngân sách đang được cập nhật riêng theo yêu cầu mới; xem [workflow-discovery.md](workflow-discovery.md) và cấu hình thực tế khi chạy.

## Đề xuất ưu tiên cho dự án

1. Giữ **Tavily để khám phá rộng**: tên loại sản phẩm, cách dùng, dịp tặng, người nhận và liên kết nguồn. Tìm riêng trang bán hàng, trang nội dung và nguồn Creative Center để tránh gộp mọi thứ thành một chỉ số.
2. Đã thêm `limits.shopping_keywords`, mặc định **2 keyword** khi bật Shopping, để đối chiếu mẫu/giá ngoài Amazon sau shortlist. Amazon Top 10 + Shopping 2 thường bắt đầu bằng 12 truy vấn tìm mẫu, thay vì 20; chi tiết/retry/Trends vẫn nằm cùng tổng trần SerpApi.
3. Khi có nhu cầu đối chiếu rõ, thêm **Walmart hoặc eBay qua chính key SerpApi đang có**, mỗi nguồn có trần riêng nằm trong tổng trần SerpApi. Mặc định tắt, không gọi mọi sàn cho mọi keyword.
4. TikTok Shop và quảng cáo Meta sâu hơn để giai đoạn sau, khi có nguồn/quyền phù hợp. Với bộ key hiện tại, không hứa tự lấy được toàn bộ dữ liệu bán hàng hoặc quảng cáo thương mại Mỹ.

## Các đường dữ liệu khả thi

| Luồng | Lấy được gì khi nguồn trả | Dịch vụ/key | Mức bao phủ và giới hạn |
|---|---|---|---|
| TikTok/Facebook/Pinterest/Etsy công khai | Tiêu đề, đoạn nội dung, URL, ngày nếu có; keyword trích có dẫn chứng | Tavily hiện có | Trang được lập chỉ mục, không phải toàn bộ nền tảng; không tự tạo lượt xem/like/đã bán |
| Google Shopping US | Mẫu hàng, merchant/source, giá, rating/review count, ảnh, delivery khi có | SerpApi hiện có | Một truy vấn có thể trả nhiều nhà bán, nhưng không đảm bảo một merchant cụ thể xuất hiện |
| Walmart US chuyên dụng | Listing, giá offer, người bán, rating/reviews, badge, UPC khi có | SerpApi hiện có, engine `walmart` | Giá có thể khác theo store/variant; badge và thứ tự nguồn không phải số lượng đã bán |
| eBay US chuyên dụng | Listing, giá, condition, seller, shipping, watchers/rating nếu có | SerpApi hiện có, engine `ebay` | Tách mới/cũ và auction/fixed-price; watchers và phản hồi seller không phải đơn hàng |
| TikTok Creative Center | Ý tưởng từ sản phẩm/quảng cáo/keyword theo các bộ lọc nguồn hỗ trợ | Trang TikTok công khai, một số chức năng cần login | Nguồn tham khảo/nhập URL hoặc dữ liệu được phép xuất; chưa xác minh API mở để tự lấy đầy đủ |
| Meta Ad Library US | Creative, page, landing page, thời gian quan sát khi truy cập được | Website công khai; API có phạm vi riêng | Không mặc định API chính thức cho phép xuất mọi quảng cáo thương mại Mỹ |

## 1. Tavily: khám phá có căn cứ, không coi snippet là dữ liệu bán hàng

Tavily Search hỗ trợ `include_domains`, bộ lọc ngày và `country` để ưu tiên kết quả quốc gia. Basic search phù hợp giai đoạn tìm ý tưởng; giới hạn request vẫn tính cả retry. Có thể dùng các bó domain để không nhân số lần gọi theo từng keyword. [Tài liệu Tavily Search](https://docs.tavily.com/documentation/api-reference/endpoint/search).

Hướng cải tiến query:

- Social: sản phẩm + tình huống sử dụng + United States; ưu tiên bài có loại hàng và landing page rõ.
- TikTok creative: tìm `ads.tiktok.com` theo product/category và US, giữ nhãn `ad_creative` hoặc `product_category` nếu xác định được.
- Etsy/Pinterest: ưu tiên personalized gift, recipient, occasion, style; nhận diện digital download để không gộp với hàng vật lý.
- Walmart/eBay: lấy mẫu đối chiếu và URL; chỉ đưa giá/rating vào bảng sản phẩm khi adapter thật trả trường có phạm vi rõ.

Lưu title, excerpt, URL, retrieved_at, published_at nếu có và evidence ID. Ngày lấy không phải ngày xuất bản. Country boost, tiếng Anh, USD hoặc domain .com không tự chứng minh người mua/khán giả ở Mỹ. Một sản phẩm được nhiều trang nhắc chỉ là tín hiệu khám phá; cần xử lý bài sao chép, cùng shop và cùng creative.

## 2. Shopping US: cách thêm mẫu ngoài Amazon bằng key hiện có

SerpApi Google Shopping trả các trường sản phẩm và `source`/merchant khi có. Ví dụ tài liệu có Walmart và các nhà bán khác; kết quả còn có thể có giá, rating, review count, delivery và ảnh. Có thể tận dụng dữ liệu này để đối chiếu thay vì tích hợp ngay từng sàn. [Tài liệu Shopping Results](https://serpapi.com/shopping-results).

Đề xuất: thêm giới hạn **số keyword đối chiếu Shopping** độc lập với Top N Amazon. Ví dụ Amazon Top 10 nhưng Shopping chỉ Top 2; bắt đầu bằng khoảng 12 request tìm mẫu thay vì 20, chưa gồm retry/chi tiết/Trends. Đây là kế hoạch request, không cam kết chi phí bill thực tế. Mọi request vẫn nằm trong trần tổng và phần ngân sách còn lại.

Không coi rating/review từ Google Shopping là review Amazon. Không tự gộp hai listing chỉ vì tên giống; ưu tiên UPC/GTIN/model/variant. Cùng sản phẩm có nhiều offer thì lưu giá và ngày riêng.

## 3. Walmart và eBay: adapter chuyên dụng có thể dùng cùng SerpApi

**Walmart:** tài liệu có `engine=walmart`, `query`, `walmart_domain=walmart.com` cho Mỹ; hỗ trợ các kiểu sort gồm `best_seller`, `rating_high`, `new`. Listing có thể có UPC, seller, `primary_offer` và badge. Giá phụ thuộc cửa hàng và cấu hình hàng. Trường `quantity` được mô tả là lượng có sẵn, không được đổi thành đã bán. [Walmart Search API](https://serpapi.com/walmart-search-api).

**eBay:** dùng `engine=ebay`, `_nkw`, `ebay_domain=ebay.com`; có bộ lọc quốc gia, ZIP, hình thức mua và condition. Có thể giới hạn hàng mới, fixed-price để so quà bán lẻ. Tài liệu hiện nêu bộ lọc `Sold`/`Complete` đã ngừng hỗ trợ; không xây báo cáo sales history dựa trên chúng. Seller feedback, product rating và watchers phải lưu khác trường. [eBay Search API](https://serpapi.com/ebay-search-api).

Hai nguồn dùng key SerpApi nhưng tiêu thụ chung tài nguyên tài khoản; thêm sàn không làm tăng quota miễn phí. Chỉ bật adapter sau khi có fixture, trường nguồn/ngày/tiền tệ/identity rõ và kiểm thử giới hạn request. Dự án chưa gọi live hai engine trong lần nghiên cứu này.

Nếu muốn chuyển sang **eBay API chính thức** về sau: Browse API có tìm listing/lấy chi tiết và yêu cầu application access token qua client credentials. Điều này cần key eBay riêng. Điều kiện production và API hạn chế cần đối chiếu đúng sản phẩm API; không gộp yêu cầu checkout với Browse và không hứa mọi dữ liệu bán hàng đều truy cập được. [Browse API](https://www.developer.ebay.com/develop/api/buy), [Buy API requirements](https://developer.ebay.com/api-docs/buy/buy-requirements.html), [EPN phân biệt API cần phê duyệt thêm](https://ebaypartnernetwork.ebay.com/page/developer-questionnaire).

## 4. TikTok: Creative Center có ích cho ý tưởng, Shop cần nguồn riêng

TikTok mô tả Creative Center là website công khai miễn phí; Top Products và Keyword Insights phản ánh nội dung quảng cáo, Top Ads là bộ creative được nhà quảng cáo cho phép hiển thị. Có thể dùng để tìm loại hàng và cách định vị. [Giới thiệu các công cụ Creative Center](https://ads.tiktok.com/business/creativecenter/quicktok/online/tiktok_creative_accelerator/pc/en).

Top Ads hỗ trợ keyword và bộ lọc Region; hướng dẫn chính thức nói người chưa đăng nhập chỉ thấy 5 quảng cáo. Vì vậy kết quả công khai không đại diện toàn bộ TikTok và không được coi là bộ đơn hàng TikTok Shop US. [Hướng dẫn Top Ads Dashboard](https://ads-useast2a.tiktok.com/resources/help/article/how-to-use-the-top-ads-dashboard).

Đề xuất phù hợp hiện tại: lưu link tham khảo Creative Center/bài public, đối chiếu filter US được nguồn nêu, trích keyword có câu nguồn rồi kiểm tra với Trends và sàn. Nếu người dùng nhập URL hay dữ liệu xuất hợp lệ sau này, lưu nguồn và thời gian để nghiên cứu tiếp; đây vẫn không phải tự thu thập toàn bộ nền tảng. Không thêm Apify, proxy/CAPTCHA bypass hoặc âm thầm cài browser scraper trong luồng này.

## 5. Facebook/Instagram: không nhầm Ad Library web với API thương mại Mỹ

Trang API chính thức Meta hiện mô tả: quảng cáo political/issue toàn cầu trong 7 năm và quảng cáo mọi loại đã phân phối ở UK/EU trong một năm. Để tìm mọi quảng cáo đang chạy, Meta hướng sang Ad Library website. Vì vậy không nên hứa key Graph API cho phép xuất đầy đủ quảng cáo thương mại ở Mỹ. [Meta Ad Library API](https://www.facebook.com/ads/library/api/), [bản trang Meta đọc được khi đối chiếu](https://br-fr.facebook.com/ads/library/api/?source=onboarding).

Với dữ liệu quảng cáo quan sát được, lưu ad ID, creative, page, delivery dates, platform và landing page khi nguồn có. Quảng cáo chạy lâu hoặc nhiều creative chỉ là hoạt động marketing; không suy ra orders, doanh thu, spend hay ROAS của đối thủ. Tài khoản shop/quảng cáo của công ty không tự cho quyền đọc dữ liệu riêng của đối thủ.

Dùng Tavily phát hiện các trang có liên quan hoặc link đối chiếu; có thể không tìm được Ad Library do khả năng lập chỉ mục/login. Nếu cần thu thập Meta chuyên dụng về sau, chọn provider có dữ liệu thực sự bao phủ US và hạn mức riêng. `SearchApi` và `SerpApi` là hai dịch vụ khác nhau; không mặc định một key dùng được cả hai.

## 6. Luồng và cấu trúc dữ liệu nên giữ

```text
Brief và điều kiện US
  → khám phá đa nguồn có dẫn chứng
  → hợp nhất các loại sản phẩm/keyword và xử lý trùng
  → đo Trends với nguồn chính/dự phòng theo ngân sách được cấu hình
  → nếu chưa có phép đo: chờ xử lý hoặc báo thiếu, không gọi đó là Top hot
  → shortlist đã đo → Amazon + đối chiếu sàn được chọn
  → mẫu/offer/nhận định có phạm vi → báo cáo Python
```

Mỗi bản ghi cần `record_type` (product/offer/video/ad/search_trend), platform/provider, URL/ID nguồn, retrieved_at/published_at, market filter, evidence ID, metric scope/period và condition/variant. Trường không được nguồn cung cấp giữ unknown. Tách ba nhóm tín hiệu: quan tâm tìm kiếm, mẫu/giá/cạnh tranh, bằng chứng mua; không cộng views/likes/ads/reviews thành doanh số.

Ngân sách nên có phần Trends, Amazon và đối chiếu; tổng luôn bị chặn bởi trần tài khoản trong run. Cache giữ ngày quan sát gốc; fallback, retry, số lần gọi và lý do không có dữ liệu phải xem được trong log từng tiến trình. Nguồn thay thế cho sàng lọc Trends vẫn phải trả dữ liệu Trends so sánh được; một snippet social không thay cho chuỗi search interest.

## Trạng thái và bước tiếp theo

- **Đã có trước đợt sửa này:** khám phá Tavily theo domain và trích keyword có nguyên văn; Amazon/Shopping; adapter Trends miễn phí; báo cáo và CSV có nguồn.
- **Đang sửa theo yêu cầu mới:** xử lý lỗi Trends tự động, nguồn dự phòng trong ngân sách và log/chi tiết từng bước; đối chiếu hướng dẫn triển khai mới để biết cấu hình cuối.
- **Đề xuất sau, chưa triển khai trong tài liệu này:** Shopping chỉ cho một phần shortlist; adapter Walmart/eBay chuyên dụng; import URL/CSV có provenance; nguồn TikTok Shop/Meta sâu hơn khi có quyền/provider phù hợp.
- **Không thêm:** Apify hoặc key nhà cung cấp mới; không coi việc tìm thấy một trang là đã xác minh lượng bán hoặc độ phủ thị trường Mỹ.
