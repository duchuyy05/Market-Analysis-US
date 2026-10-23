import argparse
import sys
from .io import ROOT, load_env


def main(argv=None):
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,"reconfigure"):
            stream.reconfigure(encoding="utf-8",errors="replace")
    parser = argparse.ArgumentParser(prog="python -m market_analysis",description="Phân tích thị trường và sản phẩm từ dữ liệu web")
    subs = parser.add_subparsers(dest="command", required=True)
    subs.add_parser("status")
    subs.add_parser("quota",help="Kiểm tra hạn mức tài khoản API; không gọi tìm kiếm/model")
    report=subs.add_parser("report",help="Ghép báo cáo đầy đủ của Python với phần diễn giải LLM đã lưu")
    report.add_argument("--output",default="data/seasonal-gifts-us")
    report.add_argument("--ai",action="store_true",help="Gọi model miễn phí viết diễn giải mới với Top sản phẩm và lịch sử tìm kiếm")
    report.add_argument("--model",help="Model :free; mặc định đọc api/.env")
    report.add_argument("--max-calls",type=int,default=6,help="Giới hạn lượt OpenRouter khi dùng --ai, tối đa 8")
    seasonal=subs.add_parser("seasonal",help="Seasonal products: API collection, monthly top five, report and dashboard")
    seasonal.add_argument("--phase",choices=["collect","build","report","verify","all"],default="all")
    seasonal.add_argument("--output",default="data/seasonal-gifts-us")
    seasonal.add_argument("--config",default="config/seasonal.json",help="Study JSON: topic, niches, months, years, queries")
    seasonal.add_argument("--fresh",action="store_true",help="Bypass source cache; requires a new output folder")
    demo=subs.add_parser("demo",help="Regenerate the seasonal report/dashboard offline from collected data")
    demo.add_argument("--output",default="data/seasonal-gifts-us")
    supplement=subs.add_parser("supplement",help="Bổ sung nhãn mua và nhận xét Amazon cho nghiên cứu đã lưu")
    supplement.add_argument("--output",default="data/seasonal-gifts-us")
    supplement.add_argument("--max-requests",type=int,default=12,help="Tối đa 1–45 lượt SerpApi; chỉ dùng quota gói miễn phí")
    supplement.add_argument("--reserve-searches",type=int,default=50,help="Số lượt SerpApi giữ lại cho demo (mặc định 50)")
    supplement.add_argument("--ai",action="store_true",help="Viết lại nhận định bằng model miễn phí trong api/.env")
    local=subs.add_parser("dashboard",aliases=["serve"],help="Mở dashboard trên máy")
    local.add_argument("--port",type=int,default=8765)
    args = parser.parse_args(argv)
    if args.command == "report":
        from .combined_report import run_combined_report
        run_combined_report(ROOT/args.output,args.ai,args.model,args.max_calls)
    elif args.command == "quota":
        from .quota import check_quota
        check_quota()
    elif args.command == "status":
        env = load_env()
        for key in ("SERPAPI_API_KEY", "TAVILY_API_KEY", "OPENROUTER_API_KEY"):
            print(f"{key}: {'configured (not verified)' if env.get(key) else 'missing'}")
        print("Model: " + env.get("OPENROUTER_MODEL", "openrouter/free"))
    elif args.command == "supplement":
        from .supplement import run_supplement
        run_supplement(ROOT/args.output,args.max_requests,args.ai,reserve_searches=args.reserve_searches)
    elif args.command in {"serve","dashboard"}:
        from .local_app import serve
        if not 1024<=args.port<=65535:
            raise RuntimeError("Chọn port trong khoảng 1024–65535")
        serve(args.port)
    elif args.command in {"seasonal","demo"}:
        from .seasonal import run_seasonal
        run_seasonal(ROOT/args.output,"build" if args.command=="demo" else args.phase,
                     config_path=ROOT/args.config if args.command=="seasonal" else None,
                     fresh=args.fresh if args.command=="seasonal" else False)


def entrypoint():
    try:
        main()
    except (RuntimeError, ValueError, OSError) as error:
        # Controlled errors only; never print exception URLs, headers or env values.
        if isinstance(error, RuntimeError):
            print(f"Stopped: {error}")
        else:
            print("Stopped: check local config/data file format and permissions")
        raise SystemExit(1)


if __name__ == "__main__":
    entrypoint()
