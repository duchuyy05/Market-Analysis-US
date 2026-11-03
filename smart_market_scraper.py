"""
LUỒNG TỰ ĐỘNG THÔNG MINH (SMART MARKET RESEARCH PIPELINE):
1. Input: Nhận mô tả tự do từ người dùng (Brief).
2. LLM: Dùng OpenRouter bóc tách Niche và sinh danh sách Từ khóa tìm kiếm chuẩn SEO (English ASCII).
3. Tool Scraping: Tự động dùng bộ cào Amazon, Etsy, Reddit với các từ khóa do LLM sinh ra (KHÔNG CẦN API KEY).
4. Phân tích & Xếp hạng: Lọc ra các sản phẩm nhiều lượt bán nhất & Hot nhất cho từng ngách.
5. Xuất báo cáo: In bảng terminal, xuất file CSV/JSON chi tiết.
"""
import os
import sys
import json
import re
import time
from pathlib import Path
from typing import List, Dict, Any, Optional
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# Đảm bảo terminal Windows không bị lỗi Unicode khi in tiếng Việt hoặc emoji
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from scrapers.aggregator import ProductAggregator


def load_env_keys(root_dir: Path) -> Dict[str, str]:
    """Đọc các biến môi trường từ api/.env hoặc .env"""
    keys = {}
    for p in [root_dir / "api" / ".env", root_dir / ".env"]:
        if p.exists():
            for line in p.read_text(encoding="utf-8-sig").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    keys[k.strip()] = v.strip().strip("\"'")
    # Ưu tiên biến môi trường hệ thống nếu có
    for k in ["OPENROUTER_API_KEY", "OPENROUTER_MODEL"]:
        if os.environ.get(k):
            keys[k] = os.environ[k]
    return keys


class SmartMarketScraper:
    def __init__(self, root_dir: Optional[Path] = None):
        self.root = root_dir or Path(__file__).resolve().parent
        self.env = load_env_keys(self.root)
        self.openrouter_key = self.env.get("OPENROUTER_API_KEY", "").strip()
        self.model = self.env.get("OPENROUTER_MODEL", "google/gemini-2.0-flash-exp:free").strip()
        self.aggregator = ProductAggregator(timeout=15)

    def call_llm(self, prompt: str, system_prompt: str = "") -> str:
        """Gửi prompt tới OpenRouter API để phân tích."""
        if not self.openrouter_key:
            raise ValueError("Thiếu OPENROUTER_API_KEY trong api/.env hoặc .env")

        headers = {
            "Authorization": f"Bearer {self.openrouter_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://localhost",
            "X-Title": "Market-Research-Tool"
        }

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
        }

        req = Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers
        )

        try:
            with urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                choices = data.get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content", "")
                raise ValueError("LLM không trả về nội dung lựa chọn.")
        except HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"Lỗi OpenRouter HTTP {e.code}: {err_body}")
        except Exception as e:
            raise RuntimeError(f"Lỗi kết nối OpenRouter: {e}")

    def extract_keywords_with_llm(self, brief: str) -> Dict[str, Any]:
        """
        Dùng LLM để phân tích input mô tả, chia ngách (niche)
        và tạo từ khóa tiếng Anh tìm kiếm trên Amazon/Etsy/Reddit.
        """
        system_prompt = (
            "Bạn là chuyên gia nghiên cứu thị trường e-commerce (Amazon, Etsy). "
            "Nhiệm vụ của bạn là nhận mô tả ý tưởng sản phẩm từ người dùng (bằng tiếng Việt hoặc tiếng Anh), "
            "phân tích thành các Niche cụ thể và tạo ra các cụm từ khóa tìm kiếm (search queries) bằng tiếng Anh "
            "ngắn gọn (2-4 từ), tự nhiên như người tiêu dùng Mỹ tìm kiếm trên Amazon và Etsy. "
            "Trả về DUY NHẤT một chuỗi JSON hợp lệ, không có markdown phụ trợ."
        )

        user_prompt = f"""
Hãy phân tích yêu cầu nghiên cứu sau:
\"\"\"{brief}\"\"\"

Hãy trả về định dạng JSON với cấu trúc chính xác sau:
{{
  "category": "Tên danh mục tổng quát (tiếng Việt)",
  "target_audience": "Đối tượng khách hàng mục tiêu",
  "niches": [
    {{
      "niche_name": "Tên ngách 1 (tiếng Việt)",
      "search_keywords": [
        "cụm từ khóa tiếng Anh 1",
        "cụm từ khóa tiếng Anh 2"
      ],
      "reason": "Lý do chọn nhóm từ khóa này"
    }},
    {{
      "niche_name": "Tên ngách 2 (tiếng Việt)",
      "search_keywords": [
        "cụm từ khóa tiếng Anh 3",
        "cụm từ khóa tiếng Anh 4"
      ],
      "reason": "Lý do chọn nhóm từ khóa này"
    }}
  ]
}}
Lưu ý:
- search_keywords BẮT BUỘC là tiếng Anh ASCII, dạng cụm từ tìm kiếm thực tế (ví dụ: 'wooden christmas ornament', 'desk cable organizer', 'funny dog mom tote bag').
- Không dùng từ khóa chung chung như 'gift', 'stuff', 'product'.
- Mỗi niche cho từ 2 đến 3 từ khóa chất lượng nhất.
"""

        print("\n🤖 [Bước 1] Đang gửi mô tả tới LLM để phân tích từ khóa...")
        raw_response = self.call_llm(user_prompt, system_prompt=system_prompt)

        # Parse JSON từ response của LLM
        clean_json_str = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_response.strip(), flags=re.MULTILINE)
        try:
            plan = json.loads(clean_json_str)
        except json.JSONDecodeError:
            # Tìm đoạn bao bọc bởi { ... }
            m = re.search(r"\{[\s\S]*\}", clean_json_str)
            if m:
                plan = json.loads(m.group(0))
            else:
                raise ValueError(f"Không thể parse JSON từ LLM: {raw_response[:200]}")

        print(f"✅ LLM đã phân tích xong:")
        print(f"   • Danh mục: {plan.get('category')}")
        print(f"   • Khách hàng: {plan.get('target_audience')}")
        print(f"   • Số ngách (niches): {len(plan.get('niches', []))}")
        for idx, n in enumerate(plan.get("niches", []), 1):
            kw_list = ", ".join([f"'{k}'" for k in n.get("search_keywords", [])])
            print(f"     {idx}. {n.get('niche_name')}: {kw_list}")

        return plan

    def run_pipeline(
        self,
        brief: str,
        sources: Optional[List[str]] = None,
        limit_per_keyword: int = 10,
        sort_by: str = "sales",
        output_file: str = "outputs/smart_market_results.csv"
    ) -> Dict[str, Any]:
        """
        Chạy toàn bộ quy trình:
        Brief ➔ LLM extract keywords ➔ Scrape Amazon/Etsy/Reddit ➔ Rank ➔ Export
        """
        if sources is None:
            sources = ["amazon", "etsy", "reddit"]

        print("=" * 80)
        print("          BẮT ĐẦU QUY TRÌNH NGHIÊN CỨU THỊ TRƯỜNG TỰ ĐỘNG (NO-API)")
        print("=" * 80)
        print(f"📝 Input đầu vào: \"{brief}\"")
        print(f"🌐 Nguồn cào: {', '.join(sources).upper()}")
        print(f"📊 Sắp xếp theo: {sort_by}")

        # BƯỚC 1: LLM hiểu mô tả và lấy từ khóa
        try:
            plan = self.extract_keywords_with_llm(brief)
        except Exception as e:
            print(f"⚠️ Không thể gọi LLM ({e}). Bạn hãy kiểm tra lại OPENROUTER_API_KEY trong api/.env.")
            return {}

        # BƯỚC 2: Cào dữ liệu theo từng từ khóa do LLM sinh ra
        print("\n🕷️ [Bước 2] Bắt đầu cào dữ liệu từ các sàn (Amazon, Etsy, Reddit) theo từng từ khóa...")
        all_collected_products = []
        niche_summaries = []

        niches = plan.get("niches", [])
        total_keywords = sum(len(n.get("search_keywords", [])) for n in niches)
        processed_kw = 0

        for niche in niches:
            niche_name = niche.get("niche_name", "Chung")
            keywords = niche.get("search_keywords", [])

            for kw in keywords:
                processed_kw += 1
                print(f"\n[{processed_kw}/{total_keywords}] 👉 Đang cào cho từ khóa: '{kw}' (Ngách: {niche_name})")

                items = self.aggregator.scrape(
                    keyword=kw,
                    sources=sources,
                    limit_per_source=limit_per_keyword,
                    sort_by=sort_by
                )

                # Gắn metadata ngách và từ khóa vào từng sản phẩm
                for item in items:
                    item["niche"] = niche_name
                    item["seed_keyword"] = kw
                    all_collected_products.append(item)

                # Nghỉ nhẹ giữa các từ khóa để tránh bị chặn IP
                time.sleep(1.5)

        # BƯỚC 3: Xếp hạng tổng thể
        print("\n📈 [Bước 3] Đang tổng hợp và xếp hạng các sản phẩm nhiều lượt bán & hot nhất...")
        ranked_products = self.aggregator._rank_products(all_collected_products, sort_by=sort_by)

        # In bảng Top sản phẩm ra Terminal
        self.aggregator.print_summary(ranked_products, top_n=30)

        # BƯỚC 4: Xuất file báo cáo
        Path(output_file).parent.mkdir(parents=True, exist_ok=True)
        if output_file.endswith(".json"):
            json_data = {
                "brief": brief,
                "plan": plan,
                "total_products": len(ranked_products),
                "products": ranked_products
            }
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(json_data, f, ensure_ascii=False, indent=2)
            print(f"💾 Đã xuất toàn bộ kết quả ra file JSON: {output_file}")
        else:
            self.aggregator.export_csv(ranked_products, output_file)

        print("\n🎉 Hoàn thành xuất sắc toàn bộ quy trình nghiên cứu thị trường!")
        return {
            "plan": plan,
            "products": ranked_products
        }


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Luồng tự động: Nhập mô tả ➔ LLM trích xuất từ khóa ➔ Cào Amazon, Etsy, Reddit không cần API"
    )
    parser.add_argument(
        "-b", "--brief",
        type=str,
        help="Đoạn văn bản mô tả nhu cầu nghiên cứu sản phẩm"
    )
    parser.add_argument(
        "-s", "--sources",
        type=str,
        default="amazon,etsy,reddit",
        help="Danh sách nguồn cào, phân tách bằng dấu phẩy (mặc định: amazon,etsy,reddit)"
    )
    parser.add_argument(
        "--sort",
        type=str,
        choices=["sales", "hot", "reviews"],
        default="sales",
        help="Tiêu chí xếp hạng: 'sales' (nhiều lượt bán nhất), 'hot' (độ hot/trending), 'reviews' (nhiều đánh giá nhất)"
    )
    parser.add_argument(
        "-l", "--limit",
        type=int,
        default=8,
        help="Số lượng sản phẩm lấy cho mỗi từ khóa (mặc định: 8)"
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        default="outputs/smart_market_results.csv",
        help="Đường dẫn file kết quả (.csv hoặc .json)"
    )
    args = parser.parse_args()

    brief = args.brief
    if not brief:
        print("\n========================================================")
        print("    SMART MARKET RESEARCH: LLM + CÀO SÀN KHÔNG DÙNG API")
        print("========================================================")
        try:
            brief = input("Nhập mô tả ý tưởng sản phẩm của bạn: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nĐã hủy.")
            sys.exit(0)

    if not brief:
        print("Lỗi: Mô tả không được để trống.")
        sys.exit(1)

    sources = [s.strip() for s in args.sources.split(",") if s.strip()]

    scraper = SmartMarketScraper()
    scraper.run_pipeline(
        brief=brief,
        sources=sources,
        limit_per_keyword=args.limit,
        sort_by=args.sort,
        output_file=args.output
    )


if __name__ == "__main__":
    main()
