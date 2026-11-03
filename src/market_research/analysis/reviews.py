"""Auditable review mentions; a mention is not population sentiment."""
import re

PATTERNS = {
    "packaging": ("Đóng gói", r"\b(packaging|packaged|wrapped|broken|damaged)\b"),
    "size": ("Kích thước và số lượng", r"\b(size|small|smaller|large|pieces|quantity)\b"),
    "instructions": ("Hướng dẫn và lắp ráp", r"\b(instructions?|assembly|assemble|installation)\b"),
    "material": ("Vật liệu và độ bền", r"\b(material|quality|durable|flimsy|broke|broken)\b"),
    "appearance": ("Hình thức", r"\b(color|colour|cute|beautiful|design|bright)\b"),
    "value": ("Giá trị cảm nhận", r"\b(price|value|worth|expensive|money)\b"),
}

IMPROVEMENTS = [
    (r"\b(?:no|missing|without|unclear|poor)\s+(?:assembly\s+)?instructions?\b", "kèm hướng dẫn sử dụng/lắp ráp rõ ràng", "Kiểm thử hướng dẫn với người chưa từng sử dụng"),
    (r"\b(?:arrived|came|received)\b.{0,35}\b(?:broken|damaged)\b", "thử quy cách đóng gói bảo vệ tốt hơn", "Thử đóng gói và vận chuyển trên mẫu thực tế"),
    (r"\b(?:smaller|larger)\s+than\s+(?:expected|pictured|advertised)\b", "thể hiện kích thước thực tế và ảnh tỷ lệ rõ ràng", "Đối chiếu thông số, ảnh tỷ lệ và kỳ vọng người mua"),
]


def themes(reviews):
    output = []
    for review in reviews:
        for key, (label, pattern) in PATTERNS.items():
            match = re.search(pattern, review["text"], re.I)
            if match:
                output.append({"review_id": review["id"], "product_id": review["product_id"], "theme": key, "label": label,
                    "excerpt": review["text"][max(0, match.start()-70):match.end()+150], "rating": review["rating"],
                    "evidence_ids": review["evidence_ids"], "method": "keyword_mention_v1_not_sentiment"})
    return output
