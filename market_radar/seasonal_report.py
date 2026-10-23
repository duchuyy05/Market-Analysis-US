"""Source-backed Vietnamese report and a self-contained, offline dashboard."""
from collections import Counter
from datetime import date
import hashlib
import html
import json
import re
from statistics import median

from .io import ROOT, now, save_json
from .csv_exports import csv_files, csv_downloads_html
from .settings import study_months, period_label, month_end


STATUS={"historical_period_peak":"Đỉnh trong kỳ lặp lại","historical_q4_peak":"Đỉnh trong Q4 lặp lại","historical_build_up":"Giai đoạn tăng trước đỉnh",
    "secondary_period":"Tháng phụ còn tín hiệu","preparation_or_off_peak":"Ngoài đỉnh / chuẩn bị",
    "insufficient_search_history":"Lịch sử tìm kiếm chưa đủ chắc","no_supported_keyword":"Chưa nối được keyword phù hợp"}
THEMES={"scent":"Mùi hương","packaging":"Đóng gói","size_or_quantity":"Kích thước / số lượng","material_or_quality":"Vật liệu / chất lượng",
    "value_for_money":"Giá trị so với giá","gift_recipient_or_occasion":"Người nhận / dịp tặng","skin_or_sensitivity":"Da / độ nhạy cảm",
    "delivery":"Giao hàng","battery_or_power":"Pin / nguồn điện","assembly_or_instructions":"Lắp ráp / hướng dẫn",
    "adhesion":"Khả năng bám / tháo","appearance_or_color":"Ngoại hình / màu sắc"}

# Keep the saved source metadata unchanged; localize it when rendering reports.
LIMITATIONS_VI={
    "Google Trends indices measure relative searches, not Amazon traffic or units sold.":
        "Google Trends cho biết mức quan tâm tìm kiếm tương đối, không cho biết lượt truy cập Amazon hay số sản phẩm đã bán.",
    "Each term uses a separate fixed-window scale. Compare timing within a keyword; do not compare index magnitudes as demand size.":
        "Mỗi từ khóa có thang điểm riêng trong khoảng thời gian khảo sát. Có thể dùng để so sánh thời điểm quan tâm của cùng một từ khóa, nhưng không dùng điểm giữa các từ khóa để so quy mô nhu cầu.",
    "Monthly averages approximate source indices by overlapping days; historical peak is within selected months only.":
        "Chỉ số tháng được tính gần đúng từ các điểm dữ liệu nguồn theo số ngày giao với tháng. Tháng cao điểm chỉ được xác định trong những tháng đã chọn, không mặc định là cao điểm cả năm.",
    "Future months beyond the as-of date are blank, not zero. A completed current-year period can contribute to timing.":
        "Tháng sau mốc thu thập được để trống vì chưa có dữ liệu. Kỳ khảo sát của năm hiện tại chỉ được dùng để xác định mùa vụ khi đã có đủ dữ liệu cho cả kỳ.",
    "Amazon prices, purchase bands and ratings are current snapshots, not historical monthly ASIN sales.":
        "Giá, điểm sao và nhãn lượt mua trên Amazon phản ánh thời điểm lấy dữ liệu. Chúng không cho biết doanh số từng tháng trong quá khứ của sản phẩm.",
    "A top-five list is a transparent shortlist within this limited sample, not Amazon's global top five or a sales forecast.":
        "Top {top_n} là danh sách ưu tiên trong mẫu đã thu thập, chưa phải bảng sản phẩm bán chạy nhất toàn Amazon hoặc dự báo doanh số.",
    "Review publication month is not verified purchase month. Reviews may share variants and do not establish US demographics.":
        "Ngày đăng nhận xét không xác nhận ngày mua hàng. Một trang sản phẩm có thể gộp nhận xét của nhiều biến thể; nội dung tiếng Anh cũng không chứng minh người viết sống tại Mỹ.",
    "Full reviews and linked review excerpts are counted separately. Excerpts without date or rating remain undated/unrated; AI summaries are excluded. Records are not necessarily unique customers.":
        "Nhận xét đầy đủ và trích đoạn nhận xét được đếm riêng. Nếu trích đoạn không có ngày đăng hoặc số sao, báo cáo để trống các trường tương ứng. Phần tóm tắt do AI không được tính là nhận xét. Số nội dung thu thập được không tương ứng với số khách hàng riêng biệt.",
    "Purchase evidence preserves exact ASIN, source type and observation date. Search-result badges supplement coverage but do not silently replace product-page snapshots or enter Top 5 ranking.":
        "Thông tin lượt mua luôn gắn với ASIN, loại trang nguồn và ngày ghi nhận. Nhãn mua từ kết quả tìm kiếm chỉ bổ sung dữ liệu tham khảo, không thay số liệu đã lấy trên trang sản phẩm hoặc dùng để tính lại Top {top_n}.",
    "Search sampling is not comprehensive market coverage. Missing review/source data does not imply low demand or low competition.":
        "Mẫu khảo sát chỉ gồm những sản phẩm và nguồn đã thu thập, chưa bao quát toàn thị trường. Thiếu nhận xét hoặc dữ liệu nguồn chưa đủ để kết luận sản phẩm có nhu cầu thấp hay ít cạnh tranh.",
    "Configured families are survey seeds, not proof they are hot. No profit estimate is made without costs.":
        "Các nhóm sản phẩm được chọn làm điểm bắt đầu khảo sát, chưa phải danh sách đã được xác nhận đang bán chạy. Báo cáo chưa ước tính lợi nhuận vì thiếu dữ liệu chi phí.",
}


def source_error_text(error):
    identifier=error.get("source","")
    asin=re.search(r"(?:^|_)([A-Z0-9]{10})(?:_|$)",identifier)
    target="dữ liệu bổ sung" if identifier.startswith("supplement-") else "dữ liệu"
    if asin:
        target+=" cho ASIN "+asin.group(1)
    else:
        target+=" từ một nguồn trong lượt thu thập"
    reason=" do API nguồn trả về lỗi" if error.get("error","").startswith("Provider returned error") else ""
    return "Chưa lấy được "+target+reason+"."


def fmt(value,digits=2):
    if value is None:
        return "Chưa có"
    if isinstance(value,float):
        return f"{value:,.{digits}f}".rstrip("0").rstrip(".")
    return str(value)


def source(text,url):
    if not url:
        return str(text)+" (chưa có nguồn)"
    if not (url.startswith(("https://","http://")) or ("/" not in url and url.endswith((".csv",".html",".json",".md")))):
        return str(text)
    return {"text":str(text),"url":url}


def block_render(blocks):
    def text(cell):
        return str(cell["text"] if isinstance(cell,dict) else cell if cell is not None else "Chưa có")
    def md(cell):
        value=text(cell).replace("|","\\|").replace("\n"," ").replace("[","\\[").replace("]","\\]")
        return f"[{value}]({cell['url']})" if isinstance(cell,dict) else value
    def ht(cell):
        value=html.escape(text(cell))
        return f'<a href="{html.escape(cell["url"],quote=True)}">{value}</a>' if isinstance(cell,dict) else value
    markdown=[]; document=[]
    for block in blocks:
        kind=block["kind"]
        if kind=="heading":
            level=block["level"]
            markdown.append("#"*level+" "+block["text"]+"\n")
            document.append(f'<h{level}>{html.escape(block["text"])}</h{level}>')
        elif kind=="paragraph":
            markdown.append(block["text"]+"\n")
            document.append("<p>"+html.escape(block["text"])+"</p>")
        elif kind=="table":
            markdown.extend(["| "+" | ".join(md(c) for c in block["headers"])+" |","|"+"---|"*len(block["headers"])])
            markdown.extend("| "+" | ".join(md(c) for c in row)+" |" for row in block["rows"])
            markdown.append("")
            document.append("<div class='table-wrap'><table><thead><tr>"+"".join("<th>"+ht(c)+"</th>" for c in block["headers"])+
                "</tr></thead><tbody>"+"".join("<tr>"+"".join("<td>"+ht(c)+"</td>" for c in row)+"</tr>" for row in block["rows"])+"</tbody></table></div>")
    return "\n".join(markdown),"\n".join(document)


def make_blocks(data,analysis,config,insights=None,*,combined=False):
    blocks=[]
    def h(text,level=2): blocks.append({"kind":"heading","level":level,"text":text})
    def p(text): blocks.append({"kind":"paragraph","text":text})
    def t(headers,rows): blocks.append({"kind":"table","headers":headers,"rows":rows})
    def slot(name):
        if combined: blocks.append({"kind":"llm_slot","name":name})
    families={f["id"]:f for f in config["families"]}
    products={p["asin"]:p for p in data["products"]}
    def family_name(keyword_id): return families[keyword_id.removeprefix("K-")]["name_vi"]
    cutoff=data["as_of_date"]
    months=study_months(data)
    period=period_label(months)
    years_text=", ".join(map(str,data["history_years"]))
    top_n=config.get("top_n",5)
    counts=Counter(r["month"] for r in analysis["monthly_top5"])
    h("BÁO CÁO THỊ TRƯỜNG — "+period.upper(),1)
    p(f"Danh mục: {data['category']}. Thị trường: Mỹ, Amazon.com. Niche: "+"; ".join(n['name_vi'] for n in config['niches'])+".")
    p(f"Lịch sử tìm kiếm: {period}, các năm {years_text}; mốc dữ liệu {cutoff}. Chỉ các kỳ đã quan sát đầy đủ mới dùng suy ra tháng phù hợp. Số liệu và thứ hạng được tính bằng Python; "+("phần diễn giải từ LLM, khi có, được ghi rõ tại từng mục." if combined else "có thêm phần nhận định LLM ghi nguồn riêng." if insights and insights.get('insights') else "báo cáo dựng bằng quy tắc, chưa có nhận định LLM."))
    h("1. Kết quả cần quyết định")
    full=sum(r.get("review_text_kind","full")=="full" for r in data["reviews"])
    excerpts=sum(r.get("review_text_kind")=="excerpt" for r in data["reviews"])
    p(f"Mẫu có {len(products)} ASIN duy nhất thuộc {len(config['families'])} nhóm được khảo sát, {full} nhận xét đầy đủ, {excerpts} trích đoạn nhận xét có liên kết nguồn và {len(data['web_sources'])} trang web Tavily. Đây là Top {top_n} ưu tiên trong mẫu, không phải toàn Amazon.")
    p(f"Cách chọn: keyword có ít nhất {config.get('min_completed_years_for_timing',2)} kỳ đầy đủ và đủ điểm nguồn dương; tháng đạt ít nhất {config.get('ramp_up_profile_threshold_pct',40)}% mức đỉnh kỳ của chính keyword; ASIN có nhãn mua hiện tại. Ưu tiên đỉnh lặp lại, nhãn số mua, rồi mức phù hợp tháng. Chọn khác nhóm trước khi bổ sung ASIN cùng nhóm. Chỉ số mùa vụ không đo quy mô cầu giữa các keyword.")
    summary=[]
    for month in months:
        rows=[r for r in analysis["monthly_top5"] if r["month"]==month]
        names=list(dict.fromkeys(family_name(r["timing_keyword_id"]) for r in rows))
        summary.append([f"Tháng {month}","; ".join(names) or "Chưa đủ dữ liệu",f"{len(rows)}/{top_n} ASIN", "Tham khảo lịch sử; tháng năm hiện tại chưa quan sát" if month>int(cutoff[5:7]) else "Đối chiếu lịch sử và snapshot hiện tại"])
    t(["Tháng","Nhóm xuất hiện trong shortlist","Độ phủ","Cách đọc"],summary)
    p("Nhãn mua là snapshot tại lúc lấy, không được gán thành số bán của tháng khác hoặc năm trước. Review theo ngày đăng không chứng minh ngày khách mua.")
    if data.get("keyword_market_summary"):
        h("Từ khóa tìm kiếm và sản phẩm Amazon tương ứng")
        p("Bảng này gồm mọi nhóm đã khảo sát, kể cả nhóm chưa đủ điều kiện vào Top sản phẩm. Tháng cao điểm được suy ra từ lịch sử của chính từ khóa; nhãn mua là thông tin hiện tại của đúng ASIN. Không cộng các mức mua để suy ra doanh số thị trường.")
        t(["Từ khóa","Tháng thường cao điểm","Sản phẩm / có nhãn mua","Nhận xét đầy đủ / trích đoạn"],
          [[s["keyword"],", ".join("T"+str(m) for m in s["peak_months"]) or "Chưa đủ lịch sử",
            str(s["products_collected"])+" / "+str(s["products_with_purchase_evidence"]),
            str(s["full_review_texts"])+" / "+str(s["review_excerpts"])] for s in data["keyword_market_summary"]])
        t(["Từ khóa","Sản phẩm / ASIN","Giá USD","Nhãn mua Amazon","Nguồn / ngày ghi nhận","Nhận xét đầy đủ / trích đoạn"],
          [[r["keyword"],source(r["asin"]+" — "+r["product_name"],r["source_url"]),fmt(r["price_usd"]),r["purchase_badge"] or "Chưa lấy được",
            ("Trang sản phẩm" if r["purchase_source_type"]=="product_listing" else "Thẻ kết quả tìm kiếm" if r["purchase_source_type"]=="search_listing" else "Chưa có")+" / "+(r["purchase_observed_at_utc"] or "Chưa có")[:10],
            str(r["full_review_texts"])+" / "+str(r["review_excerpts"])] for r in data.get("keyword_product_evidence",[])])
        p("Ưu tiên nhãn mới nhất trên trang sản phẩm, rồi đến thẻ tìm kiếm nếu trang sản phẩm chưa có nhãn. Giá và thông số vẫn theo nguồn sản phẩm ban đầu, có mốc riêng trong products.csv. Các ảnh chụp số liệu có thể khác thời điểm hoặc cách hiển thị; mọi nhãn và file nguồn được giữ trong amazon_purchase_evidence.csv. Top sản phẩm vẫn theo nhãn của nguồn sản phẩm ban đầu để không thay số liệu cũ bằng nhãn từ thẻ tìm kiếm. Trích đoạn có thể thiếu sao hoặc ngày đăng và không được tính thành nhận xét đầy đủ.")
    slot("overview")
    h(f"2. Top {top_n} sản phẩm theo từng tháng")
    for index,month in enumerate(months,1):
        h(f"2.{index}. Tháng {month}",3)
        rows=[r for r in analysis["monthly_top5"] if r["month"]==month]
        if not rows:
            p("Chưa đủ bằng chứng để chọn sản phẩm cho tháng này; không tự điền cho đủ số lượng.")
            continue
        t(["Hạng trong mẫu","Nhóm / keyword","Sản phẩm / ASIN","Giá USD","Nhãn mua hiện tại","Sao / nhận xét đầy đủ / trích đoạn","Mùa vụ","Nguồn tìm kiếm"],
          [[r["rank_in_month"],family_name(r["timing_keyword_id"])+" / "+r["timing_keyword"],
            source(r["asin"]+" — "+r["product_name"],r["source_url"]),fmt(r["price_usd"]),r["current_purchase_badge"] or "Không có nhãn",
            f"{fmt(r['rating_out_of_5'])}/5; {products[r['asin']].get('full_reviews_collected',r['review_texts_collected'])} đầy đủ; {products[r['asin']].get('review_excerpts_collected',0)} trích đoạn",
            STATUS[r["timing_status"]]+f"; mức tương đối {fmt(r['historical_profile_pct_of_own_period_peak'])}%; năm {', '.join(map(str,r['historical_years_used']))}",
            source("Google Trends",next(k["source_url"] for k in analysis["monthly_keyword_analysis"] if k["keyword_id"]==r["timing_keyword_id"]))] for r in rows])
        p("Thời điểm của giá/nhãn mua từng ASIN: "+"; ".join(r["asin"]+": "+r["current_snapshot_at_utc"][:10] for r in rows)+". Giá của cả gói; chưa tính coupon, thuế hoặc phí vận chuyển khi nguồn không cung cấp.")
        ids={r["asin"] for r in rows}
        selected=sorted([r for r in data["reviews"] if r["asin"] in ids],key=lambda r:(r["rating_out_of_5"] is None,r["rating_out_of_5"] or 6,r["review_id"]))
        quotes=[]; seen=set()
        for review in selected:
            if review["asin"] in seen: continue
            quotes.append(review);seen.add(review["asin"])
            if len(quotes)==3:break
        t(["ASIN / review ID","Ngày đăng / sao review","Trích nguyên văn tiếng Anh","Nguồn"],
            [[r["asin"]+" / "+r["review_id"],fmt(r["review_date"])+" / "+fmt(r["rating_out_of_5"]),r["review_text"][:360],source("Trích đoạn" if r.get("review_text_kind")=="excerpt" else "Nhận xét đầy đủ",r["source_url"])] for r in quotes])
        if not quotes:p("Các ASIN được chọn chưa có nội dung review trong mẫu. Có sao tổng hợp không đồng nghĩa đã thu thập được review viết.")
    h("3. Phân tích từng nhóm sản phẩm" if combined else "3. Keyword → phân tích → idea theo từng niche")
    for index,niche in enumerate(config["niches"],1):
        h(f"3.{index}. {niche['name_vi']}",3)
        group=[k for k in data["keywords"] if k["niche_id"]==niche["id"]]
        t(["Keyword"," / ".join("T"+str(m) for m in months)+": mức tương đối với đỉnh riêng","Đỉnh kỳ lặp lại",f"Cùng kỳ {cutoff[:4]}/{int(cutoff[:4])-1}","Nguồn"],
            [[k["keyword"]," / ".join(fmt(r["historical_profile_pct_of_own_period_peak"]) for r in analysis["monthly_keyword_analysis"] if r["keyword_id"]==k["keyword_id"]),
              "; ".join(f"T{r['month']}: {r['peak_year_count']}/{r['completed_year_count']} mùa" for r in analysis["monthly_keyword_analysis"] if r["keyword_id"]==k["keyword_id"] and r["timing_status"] in ("historical_q4_peak","historical_period_peak")) or "Chưa đủ chắc",
              fmt(k["same_period_yoy_change_pct"])+("%" if k["same_period_yoy_change_pct"] is not None else ""),
              source("Trends",next(r["source_url"] for r in data["trends"] if r["keyword_id"]==k["keyword_id"]))] for k in group])
        family_ids={f["id"] for f in config["families"] if f["niche_id"]==niche["id"]}
        niche_products=[p for p in products.values() if any(fid in family_ids for fid in p["family_ids"])]
        prices=[p["price_usd"] for p in niche_products if p["price_usd"] is not None]
        niche_asins={p["asin"] for p in niche_products}
        sampled=[r for r in data["reviews"] if r["asin"] in niche_asins]
        p(f"Phân tích trong mẫu: {len(niche_products)} ASIN, {len(sampled)} nội dung nhận xét (đầy đủ và trích đoạn). "+
          (f"Giá cả gói: thấp nhất ${min(prices):.2f}, trung vị ${median(prices):.2f}, cao nhất ${max(prices):.2f}. " if prices else "Chưa có giá. ")+
          "Chưa đủ dữ liệu toàn thị trường để kết luận cạnh tranh thấp/cao hoặc lợi nhuận. So quy cách, số món, kích thước khi đối chiếu giá.")
        relevant=[e for e in data["customer_needs"] if e["asin"] in niche_asins]
        theme_counts=Counter(r["theme"] for r in { (r["review_id"],r["theme"]):r for r in relevant}.values())
        p("Chủ đề được nhắc trong mẫu nhận xét và trích đoạn: "+("; ".join(THEMES.get(k,k)+f": {v}/{len(sampled)} nội dung" for k,v in theme_counts.most_common(4)) if sampled else "Chưa có nội dung nhận xét")+
          ". Đây là lượt nhắc theo từ khóa, chưa tự phân loại khen/chê hoặc suy ra tỷ lệ của toàn bộ khách hàng.")
        slot("niche:"+niche["id"])
        candidates=sorted(niche_products,key=lambda p:-(p["bought_past_month_lower_bound"] or 0))
        idea_families=[]
        for product in candidates:
            for fid in product["family_ids"]:
                if fid in family_ids and fid not in [f for f,_ in idea_families]:idea_families.append((fid,product))
            if len(idea_families)>=3:break
        for idea_index,(fid,product) in enumerate(idea_families[:3],1):
            family=families[fid]
            h(("Sản phẩm đối chiếu: " if combined else f"Idea {idea_index}: ")+family["name_vi"],4)
            if not combined:
                p("Đề xuất để kiểm chứng: "+family["idea_vi"]+" Đối tượng và mục đích mua cần xác nhận từ mô tả/review; chưa có khảo sát nhân khẩu đại diện.")
            profile=[r for r in analysis["monthly_keyword_analysis"] if r["component_id"]==fid]
            peaks=[r for r in profile if r["timing_status"] in ("historical_q4_peak","historical_period_peak")]
            p("Thời điểm: "+("lịch sử gợi ý sẵn sàng bán trước tháng "+", ".join(str(r["month"]) for r in peaks)+"; thời gian nhập hàng và số lượng tồn kho chưa xác định." if peaks else "chưa đủ lịch sử để xác định tháng ưu tiên chắc chắn."))
            t(["ASIN đối chiếu / nguồn","Giá cả gói","Nhãn mua tại snapshot","Bằng chứng sản phẩm / vị trí"],
              [[source(product["asin"],product["source_url"]),fmt(product["price_usd"]),product["bought_past_month_text"] or "Chưa có",
                e["evidence_id"]+" — "+e["verbatim_quote"]+" ["+e["source_field"]+"]"] for e in analysis["listing_evidence"] if e["asin"]==product["asin"] and e["component_id"]==fid])
    h("4. Xếp hạng tín hiệu các niche trong mẫu")
    ranking=[]
    for niche in config["niches"]:
        ids={f["id"] for f in config["families"] if f["niche_id"]==niche["id"]}
        candidates=[r for r in analysis["monthly_top5"] if r["timing_keyword_id"].removeprefix("K-") in ids]
        if not candidates:continue
        best=max(candidates,key=lambda r:r["current_purchase_band_lower_bound"] or 0)
        ranking.append((niche,best))
    ranking.sort(key=lambda pair:-(pair[1]["current_purchase_band_lower_bound"] or 0))
    t(["Hạng tín hiệu trong mẫu","Niche","Tháng đỉnh có bằng chứng","Nhãn mua mạnh nhất quan sát","ASIN nguồn","Đánh giá phạm vi"],
        [[i,n["name_vi"],", ".join("T"+str(m) for m in sorted({p["month"] for p in analysis["monthly_keyword_analysis"]
            if p["timing_status"] in ("historical_q4_peak","historical_period_peak") and families[p["component_id"]]["niche_id"]==n["id"]})),
          r["current_purchase_badge"],source(r["asin"],r["source_url"]),"Ưu tiên kiểm chứng; chưa đủ dữ liệu để xếp lợi nhuận/khả năng triển khai"] for i,(n,r) in enumerate(ranking,1)])
    p("Xếp theo nhãn mua mạnh nhất của một ASIN đã đạt điều kiện mùa vụ trong mẫu. Không cộng số mua giữa các ASIN, không coi là quy mô hoặc thị phần niche; chưa đủ dữ liệu chi phí và thời gian chuẩn bị để kết luận mức đáng đầu tư.")
    h("5. Lịch sử "+period+" từng năm")
    p("Các ô là trung bình chỉ số nguồn theo ngày giao với tháng. 0 là tín hiệu rất thấp theo nguồn, không khẳng định không có nhu cầu. Không so độ lớn raw index giữa các keyword chuẩn hóa riêng. Tháng tương lai để trống/Chưa có.")
    history=[]
    for keyword in data["keywords"]:
        for year in data["history_years"]:
            rows=[r for r in data["trends"] if r["keyword_id"]==keyword["keyword_id"] and r["year"]==year]
            history.append([keyword["keyword"],year,*[fmt(r["mean_interest_index"]) for r in rows],
                "; ".join(f"T{r['month']}: {r['observation_status']}" for r in rows),source("Trends",rows[0]["source_url"])])
    t(["Keyword","Năm",*[f"Tháng {m}" for m in months],"Trạng thái","Nguồn"],history)
    h("6. Nhóm sản phẩm ưu tiên đối chiếu" if combined else "6. Tổng kết và ba idea cần kiểm chứng trước")
    upcoming=[r for r in analysis["monthly_top5"] if r["month"]>=int(cutoff[5:7])]
    upcoming.sort(key=lambda r:(-(r["current_purchase_band_lower_bound"] or 0),r["month"],r["rank_in_month"]))
    selected=[]; seen=set()
    for row in upcoming:
        if row["timing_keyword_id"] in seen:continue
        seen.add(row["timing_keyword_id"]);selected.append(row)
        if len(selected)==3:break
    t(["Ưu tiên trong mẫu","Nhóm sản phẩm" if combined else "Idea để kiểm chứng","Tháng / cơ sở","ASIN đối chiếu","Việc cần kiểm chứng"],
        [[i,family_name(r["timing_keyword_id"]),f"T{r['month']}; "+STATUS[r["timing_status"]],source(r["asin"],r["source_url"]),
          "Quy cách, review biến thể, chi phí, tồn kho và thời gian chuẩn bị"] for i,r in enumerate(selected,1)])
    p(f"Căn cứ ưu tiên: shortlist theo mùa, nhãn số mua hiện tại và tháng phù hợp gần nhất; chưa dự báo lợi nhuận hay cam kết bán chạy. Mốc quan sát {cutoff}; cần xét thời gian nhập hàng trước khi triển khai.")
    slot("conclusion")
    if insights and insights.get("insights"):
        h("Phân tích AI")
        p("Model: "+insights.get("model","")+". Các đoạn sau là diễn giải để kiểm chứng, không thay số liệu hoặc thứ hạng tính từ nguồn.")
        for item in insights["insights"]:
            p(item["text"])
            t(["Bằng chứng tham chiếu","Nguồn"],[[ref["id"],source("Mở nguồn",ref["url"])] for ref in item["sources"]])
    h("7. Dữ liệu, nguồn và giới hạn")
    t(["Bảng / tài liệu","Vai trò"],[[source(name,name),meaning] for name,meaning in (
        ("keyword_product_evidence.csv","Từ khóa → ASIN → nhãn mua, nguồn và độ phủ nhận xét"),
        ("keyword_market_summary.csv","Độ phủ sản phẩm, lượt mua và nhận xét của mọi nhóm từ khóa"),
        ("amazon_purchase_evidence.csv","Tất cả nhãn mua quan sát được, loại trang, ngày lấy và nguồn gốc"),
        ("monthly_top5.csv","Top 5 ASIN mỗi tháng và quy tắc chọn"),("monthly_keyword_analysis.csv","Điểm mùa vụ và số mùa đủ điều kiện"),
        ("products.csv","Giá, thuộc tính, sao, số lượt đánh giá hiển thị và nhãn mua tại snapshot"),("reviews.csv","Nội dung thực lấy được; review_text_kind phân biệt full và excerpt, kèm nguồn"),
        ("listing_evidence.csv","Trích dẫn nguyên văn và vị trí trong listing"),("keyword_sources.csv","Ngữ cảnh từ Tavily"),
        ("review_month_summary.csv","Độ phủ review theo ngày đăng"),("web_sources.csv","Danh sách trang web thực sự đã lấy"),
        ("dashboard.html","Dashboard lọc theo tháng, niche, keyword và sản phẩm"))])
    p("Số nội dung nhận xét được đăng trong các tháng khảo sát, theo năm: "+"; ".join(str(year)+": "+str(sum(r.get("is_selected_period",False) and r["review_year"]==year for r in data["reviews"])) for year in data["history_years"])+". Phân bố giữa các năm và sản phẩm không đồng đều.")
    p("Điểm sao trung bình, tổng số lượt đánh giá hiển thị trên Amazon và số nhận xét đã thu thập là ba chỉ số được thống kê riêng. Khi nguồn không tách rõ số lượt chấm sao và số đánh giá có nội dung, báo cáo không dùng số nhận xét trong mẫu để thay thế.")
    for limitation in data["limitations"]:
        localized=LIMITATIONS_VI.get(limitation)
        p(localized.format(top_n=top_n) if localized else limitation)
    if data["source_errors"]:
        h("Phần dữ liệu chưa lấy được",3)
        for error in data["source_errors"]:p(source_error_text(error))
        p("Các dữ liệu đã lấy thành công vẫn được giữ trong báo cáo. Chi tiết lỗi được lưu trong dataset.json, mục source_errors; nhật ký các lượt bổ sung nằm trong thư mục supplements/.")
    return blocks


def generate_report(output):
    if not (output/"monthly-analysis.json").exists():
        raise RuntimeError("Run seasonal --phase build before report")
    data=json.loads((output/"dataset.json").read_text(encoding="utf-8"))
    analysis=json.loads((output/"monthly-analysis.json").read_text(encoding="utf-8"))
    manifest=json.loads((output/"collection.json").read_text(encoding="utf-8"))
    config=manifest["config"]
    insights_path=output/"llm-insights.json"
    insights=json.loads(insights_path.read_text(encoding="utf-8")) if insights_path.exists() else None
    if insights and insights.get("input_sha256")!=hashlib.sha256((output/"dataset.json").read_bytes()).hexdigest():
        insights=None
    markdown,body=block_render(make_blocks(data,analysis,config,insights))
    exports = csv_files(output)
    downloads = '<section id="downloads" class="csv-section"><p class="eyebrow">DỮ LIỆU NGHIÊN CỨU</p><h2>Tải dữ liệu CSV</h2><p class="muted">Mỗi file có tên, nội dung và số dòng để bạn chọn đúng bảng cần dùng.</p>'+csv_downloads_html(exports,expanded=True)+'</section>'
    (output/"report.md").write_text(markdown,encoding="utf-8")
    assets=ROOT/"market_radar/assets"
    css=(assets/"seasonal.css").read_text(encoding="utf-8")+(assets/"csv.css").read_text(encoding="utf-8")
    (output/"report.html").write_text("<!doctype html><html lang='vi'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Báo cáo thị trường</title><style>"+css+
        "</style></head><body class='report'><nav class='report-nav'><a href='dashboard.html'>← Dashboard</a><a href='#downloads'>Chọn file CSV để tải ↓</a><a href='report.md'>Bản Markdown</a><button onclick='window.print()'>In / lưu PDF</button></nav><main>"+body+downloads+"</main><script>if(new URLSearchParams(location.search).get('print')==='1')window.addEventListener('load',()=>window.print());</script></body></html>",encoding="utf-8")
    payload={"data":{k:data[k] for k in ("category","niches","market","as_of_date","history_years","history_months","products","reviews","keywords","trends","customer_needs","limitations","source_errors")},
        "analysis":analysis,"config":config}
    for key in ("keyword_product_evidence","keyword_market_summary"):
        payload["data"][key]=data.get(key,[])
    meta_path=output/"study.json"
    if meta_path.exists():
        payload["display_name"]=json.loads(meta_path.read_text(encoding="utf-8")).get("display_name",data["category"])
    serialized=json.dumps(payload,ensure_ascii=False).replace("<","\\u003c").replace("\u2028","\\u2028").replace("\u2029","\\u2029")
    shell=(assets/"dashboard.html").read_text(encoding="utf-8")
    js=(assets/"dashboard.js").read_text(encoding="utf-8")
    document=shell.replace("__STYLE__",css).replace("__DOWNLOADS__",csv_downloads_html(exports)).replace("__DATA__",serialized).replace("__SCRIPT__",js)
    (output/"dashboard.html").write_text(document,encoding="utf-8")
    llm = {"model":insights.get("model"),"created_at_utc":insights.get("created_at_utc"),"insight_count":len(insights["insights"])} if insights and insights.get("insights") else None
    save_json(output/"report-build.json",{"generated_at_utc":now(),"mode":"rules_plus_llm" if llm else "deterministic_source_backed_no_llm","llm":llm,"input_sha256":hashlib.sha256((output/"dataset.json").read_bytes()).hexdigest(),
        "outputs":["report.md","report.html","dashboard.html"],"monthly_top5_counts":dict(Counter(r["month"] for r in analysis["monthly_top5"]))})
    save_json(output/"ui-validation.json",{"status":"not_run_for_this_build","generated_at_utc":now(),
        "scope":"Generated dashboard; browser layout and interaction checks are separate"})
    print("Generated report.md, report.html and dashboard.html (rendered offline)")
