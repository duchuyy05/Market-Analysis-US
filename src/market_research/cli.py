"""CLI delegates to the exact same workflow used by the local UI."""
import argparse
import json
import sys

from .config import load_config, validate_config
from .pipeline import execute, rebuild


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        description="Nghiên cứu sản phẩm từ mô tả tự nhiên",
        epilog="Không truyền lệnh: khởi động giao diện tại http://127.0.0.1:8765",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Tự động mô tả → nguồn → phân tích → báo cáo")
    run.add_argument("--config")
    run.add_argument("--brief")
    run.add_argument("--profile", choices=["live", "demo"], default="live")
    run.add_argument("--run-id")
    for command in ("resume", "report", "status"):
        p = sub.add_parser(command)
        p.add_argument("--run-id", required=True)
    check = sub.add_parser("validate-config")
    check.add_argument("--config", required=True)
    sub.add_parser("migrate-db", help="Nhập dữ liệu JSON cũ vào SQLite, giữ nguyên file nguồn")
    serve = sub.add_parser("serve", aliases=["dashboard"])
    serve.add_argument("--port", type=int, default=8765)
    argv = list(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(argv or ["serve"])
    try:
        if args.command in {"serve", "dashboard"}:
            from .ui.server import serve as start
            start(args.port)
        elif args.command == "run":
            config = load_config(args.config) if args.config else validate_config({"brief": args.brief or "", "mode": "offline" if args.profile == "demo" else "live"})
            if args.brief:
                config["brief"] = args.brief
            if args.profile == "demo":
                config["mode"] = "offline"
                config["as_of_date"] = "2026-10-22"
                config["target_year"] = 2026
            result = execute(config, run_id=args.run_id)
            return 2 if result.manifest["status"] == "awaiting_trends" else 1 if result.manifest["status"] == "failed" else 0
        elif args.command == "resume":
            result = execute(run_id=args.run_id)
            return 2 if result.manifest["status"] == "awaiting_trends" else 1 if result.manifest["status"] == "failed" else 0
        elif args.command == "report":
            print(rebuild(args.run_id).output / "report.html")
        elif args.command == "status":
            from .common import ROOT, read_json
            from .storage.run import Run
            # Run validates the ID before resolving paths.
            obj = Run(args.run_id)
            print(json.dumps(obj.manifest, ensure_ascii=False, indent=2))
        elif args.command == "migrate-db":
            from .storage.database import migrate_legacy
            print(json.dumps(migrate_legacy(), ensure_ascii=False, indent=2))
        else:
            config = load_config(args.config)
            print(json.dumps({"status": "valid", "mode": config["mode"], "limits": config["limits"]}, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as error:
        print("LỖI: " + str(error))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
