"""Full deterministic tables with source-linked LLM interpretations at relevant sections."""
import json
from pathlib import Path

from .csv_exports import csv_files,csv_downloads_html
from .io import ROOT,now,save_json
from .llm_report import digest,paragraph_digest,publish_latest,run_llm_report,validate_paragraph
from .seasonal_report import make_blocks,block_render,source,fmt

LABELS={"observations":"Nhận định từ dữ liệu","reviews":"Phản hồi của người mua trong mẫu",
        "recommendations":"Đề xuất cần kiểm chứng","gaps":"Thông tin còn thiếu"}


def saved_analysis(output,data_hash,analysis_hash):
    warnings=[]
    path=output/"llm-report-evaluation.json"
    if not path.exists(): return {},[],{},["Chưa có phần diễn giải LLM cho dữ liệu này."]
    try:
        evaluation=json.loads(path.read_text(encoding="utf-8"))
        run=(output/evaluation["run_directory"]).resolve()
        if not run.is_relative_to(output.resolve()/"llm-reports"):
            raise ValueError()
        pack=json.loads((run/"input.json").read_text(encoding="utf-8"))
        if evaluation.get("input_sha256")!=data_hash or pack.get("input_sha256")!=data_hash:
            return {},[],evaluation,["Nhận định LLM đã lưu thuộc phiên bản dữ liệu cũ nên chưa được ghép vào báo cáo này."]
        if evaluation.get("analysis_sha256") and evaluation["analysis_sha256"]!=analysis_hash:
            return {},[],evaluation,["Phân tích số liệu đã thay đổi sau khi model viết; cần viết lại phần diễn giải."]
        manual=evaluation.get("manual_review")
        sections=json.loads((run/("reviewed-sections.json" if manual else "sections.json")).read_text(encoding="utf-8"))
        keep={(d["task"],d["paragraph_sha256"]) for d in manual["decisions"] if d["decision"]=="keep"} if manual else None
        tasks={t["id"]:t["evidence"] for t in pack["tasks"]}
        accepted=[]
        for section in sections:
            identifier=section["id"]
            if identifier!="overview" and identifier not in tasks:
                warnings.append("Bỏ mục LLM không thuộc niche trong dữ liệu đầu vào.")
                continue
            cards=pack["evidence"] if identifier=="overview" else tasks[identifier]
            paragraphs=[]
            for item in section["paragraphs"]:
                if keep is not None and (identifier,paragraph_digest(item)) not in keep:
                    warnings.append("Bỏ đoạn không có quyết định giữ trong kết quả đọc đối chiếu.")
                elif validate_paragraph(item,cards):
                    warnings.append("Bỏ đoạn LLM không khớp mã nguồn hoặc câu trích khi xuất bản kết hợp.")
                else: paragraphs.append(item)
            accepted.append({**section,"paragraphs":paragraphs})
        if evaluation.get("profile")!="combined":
            warnings.append("Phần diễn giải dùng lại lượt LLM trước, chưa được cung cấp bộ bảng xếp hạng và lịch sử mở rộng của nhánh kết hợp.")
        if evaluation.get("status")=="partial":
            warnings.append("Phần LLM còn thiếu một số mục hoặc đã có đoạn bị loại sau khi đọc đối chiếu; không xem là phân tích hoàn chỉnh.")
        return pack,accepted,evaluation,list(dict.fromkeys(warnings))
    except (OSError,ValueError,KeyError,TypeError,AttributeError):
        return {},[],{},["Không đọc được kết quả LLM hợp lệ; báo cáo vẫn giữ các bảng số liệu."]


def interpretation_blocks(items,cards):
    blocks=[]; previous=None
    for item in items:
        if item["section"]!=previous:
            blocks.append({"kind":"heading","level":4,"text":LABELS[item["section"]]+" — LLM"})
            previous=item["section"]
        blocks.append({"kind":"paragraph","text":item["text"]})
        if item.get("quote"):
            blocks.append({"kind":"paragraph","text":"Trích nguyên văn ["+item["quote"]["id"]+"]: "+item["quote"]["text"]})
        rows=[]
        for identifier in item["evidence_ids"]:
            card=cards[identifier]
            label=card.get("product_name") or card.get("name") or card.get("title") or identifier
            if card["type"]=="review":
                label+=" — "+("Nhận xét đầy đủ" if card["text_kind"]=="full" else "Trích đoạn")
                label+="; sao: "+fmt(card.get("rating"))+"; ngày đăng: "+(card.get("date") or "Chưa có")
                if card.get("variant"): label+="; biến thể: "+card["variant"]
                if card.get("country_explicit"): label+="; quốc gia nguồn ghi: "+card["country_explicit"]
            rows.append([identifier,label,source(card["source_id"],card.get("source_url"))])
        blocks.append({"kind":"table","headers":["Mã","Nguồn đang dẫn","Liên kết"],"rows":rows})
    return blocks


def generate_combined_report(output,event=None,*,extra_warnings=()):
    output=Path(output); event=event or (lambda text:print(text,flush=True))
    data_hash=digest(output/"dataset.json"); analysis_hash=digest(output/"monthly-analysis.json")
    data=json.loads((output/"dataset.json").read_text(encoding="utf-8"))
    analysis=json.loads((output/"monthly-analysis.json").read_text(encoding="utf-8"))
    config=json.loads((output/"collection.json").read_text(encoding="utf-8"))["config"]
    if analysis.get("input_sha256")!=data_hash:
        raise RuntimeError("Phân tích chưa khớp dataset; cần tính lại dữ liệu trước khi xuất báo cáo")
    pack,sections,evaluation,warnings=saved_analysis(output,data_hash,analysis_hash)
    warnings=list(dict.fromkeys([*warnings,*extra_warnings]))
    by_id={s["id"]:s["paragraphs"] for s in sections}
    count=sum(len(s["paragraphs"]) for s in sections)
    served_models=sorted({a["served_model"] for a in evaluation.get("attempts",[]) if a.get("served_model")})
    blocks=make_blocks(data,analysis,config,combined=True)
    result=[]
    for block in blocks:
        if block["kind"]!="llm_slot":
            result.append(block)
            continue
        name=block["name"]
        if name=="overview":
            items=[p for p in by_id.get("overview",[]) if p["section"] in {"observations","reviews"}]
        elif name=="conclusion":
            items=[p for p in by_id.get("overview",[]) if p["section"] in {"recommendations","gaps"}]
        else:
            items=by_id.get(name.removeprefix("niche:"),[])
        if items:
            result.extend(interpretation_blocks(items,pack["evidence"]))
        elif name.startswith("niche:"):
            result.append({"kind":"paragraph","text":"Nhóm này chưa có phần diễn giải LLM hợp lệ; các bảng và trích dẫn trên vẫn là dữ liệu đã thu thập."})
    status="combined_with_llm" if count else "python_only"
    note=("Báo cáo kết hợp bảng số liệu tính bằng Python và "+str(count)+" đoạn diễn giải do LLM viết. Model/tuyến yêu cầu: "+evaluation.get("model","")+". Thời điểm viết phần LLM: "+evaluation.get("finished_at_utc","Chưa ghi nhận")+"."
          if count else "Báo cáo hiện có các bảng số liệu Python; chưa có diễn giải LLM khớp dữ liệu để ghép.")
    result.insert(1,{"kind":"paragraph","text":note})
    if count:
        result.insert(2,{"kind":"paragraph","text":"Các đoạn ghi LLM là diễn giải cần đọc đối chiếu nguồn. Kiểm tra mã và câu trích không chứng minh mọi kết luận đều đúng; nhãn mua Amazon cũng không phải doanh số từng tháng trong quá khứ."})
    result.append({"kind":"heading","level":3,"text":"Cách tạo bản báo cáo này"})
    result.append({"kind":"paragraph","text":"Python giữ các bảng sản phẩm, xếp hạng theo tháng, lịch sử tìm kiếm, mẫu nhận xét và giới hạn nguồn. Các câu đề xuất soạn sẵn trong idea_vi không được dùng trong bản kết hợp; đề xuất ghi LLM được lấy từ kết quả model có dẫn chứng."})
    if served_models:
        result.append({"kind":"paragraph","text":"Model thực tế đã trả lời trong lượt này: "+", ".join(served_models)+"."})
    if evaluation.get("manual_review"):
        review=evaluation["manual_review"]
        result.append({"kind":"paragraph","text":"Phần LLM đã được đọc đối chiếu bởi "+review.get("reviewer","Chưa ghi tên")+"; kết quả gốc và lý do giữ/loại được lưu trong nhật ký. Đây chưa phải xác nhận đã được người dùng duyệt."})
    elif count:
        result.append({"kind":"paragraph","text":"Phần LLM mới qua kiểm tra tự động, chưa có lượt đọc đối chiếu nội dung được ghi nhận."})
    for warning in warnings: result.append({"kind":"paragraph","text":warning})
    result.append({"kind":"table","headers":["Tài liệu đối chiếu","Nội dung"],"rows":[
        [source("report.html","report.html"),"Bản báo cáo Python"],
        [source("llm-report-evaluation.json","llm-report-evaluation.json"),"Lượt gọi model và kết quả kiểm tra/đọc đối chiếu"]]})
    markdown,body=block_render(result)
    assets=ROOT/"market_radar/assets"
    css=(assets/"seasonal.css").read_text(encoding="utf-8")+(assets/"csv.css").read_text(encoding="utf-8")
    downloads='<section id="downloads" class="csv-section"><h2>Tải dữ liệu CSV</h2>'+csv_downloads_html(csv_files(output),expanded=True)+'</section>'
    document="<!doctype html><html lang='vi'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Báo cáo kết hợp</title><style>"+css+"</style></head><body class='report'><nav class='report-nav'><a href='dashboard.html'>← Dashboard</a><a href='report.html'>Bản Python</a><a href='#downloads'>Tải CSV</a><a href='report-combined.md'>Bản Markdown</a><button onclick='window.print()'>In / lưu PDF</button></nav><main>"+body+downloads+"</main></body></html>"
    if digest(output/"dataset.json")!=data_hash or digest(output/"monthly-analysis.json")!=analysis_hash:
        raise RuntimeError("Dữ liệu đổi trong lúc ghép báo cáo; chưa ghi đè bản kết hợp")
    (output/"report-combined.md").write_text(markdown,encoding="utf-8")
    (output/"report-combined.html").write_text(document,encoding="utf-8")
    metadata={"generated_at_utc":now(),"mode":status,"input_sha256":data_hash,"analysis_sha256":analysis_hash,
        "llm_paragraphs":count,"llm_run":evaluation.get("run_directory") if count else None,
        "llm_status":evaluation.get("status") if count else None,
        "model":evaluation.get("model") if count else None,"warnings":warnings,"config_ideas_included":False,
        "served_models":served_models if count else [],
        "manual_review_recorded":bool(evaluation.get("manual_review")) if count else False,
        "outputs":["report-combined.md","report-combined.html"]}
    save_json(output/"combined-report-build.json",metadata)
    event(f"Đã xuất {output/'report-combined.html'} — {count} đoạn LLM cùng các bảng số liệu Python")
    return metadata


def run_combined_report(output,ai=False,model=None,max_calls=6,event=None):
    output=Path(output); event=event or (lambda text:print(text,flush=True))
    attempted=None; warnings=[]
    if ai:
        _,previous_sections,previous,_=saved_analysis(output,digest(output/"dataset.json"),digest(output/"monthly-analysis.json"))
        attempted=run_llm_report(output,model,max_calls,event,profile="combined")
        if attempted["status"]=="failed" and any(s["paragraphs"] for s in previous_sections):
            previous_run=(output/previous["run_directory"]).resolve()
            publish_latest(previous_run,output)
            warnings.append("Lần gọi mới với "+attempted["model"]+" chưa tạo được đoạn hợp lệ. Bản này dùng lại phần LLM khớp dữ liệu từ lượt trước, có thời điểm viết ghi ở đầu báo cáo.")
            event("Lần gọi mới chưa có đoạn hợp lệ; dùng lại phần LLM đã lưu khớp dữ liệu. Lần thất bại vẫn được giữ trong lịch sử.")
    result=generate_combined_report(output,event,extra_warnings=warnings)
    if attempted:
        result["last_ai_attempt"]={"model":attempted["model"],"status":attempted["status"],"run_directory":attempted["run_directory"],
            "calls":attempted["calls"],"reported_cost_usd":attempted["reported_cost_usd"]}
        save_json(output/"combined-report-build.json",result)
    return result
