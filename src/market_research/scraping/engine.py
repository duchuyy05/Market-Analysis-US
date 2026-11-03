"""Observed listing fields only. Missing metrics stay missing; blocks are explicit."""
import html
import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup


def headers(site="general"):
    return {"User-Agent": "ONEF-ProductResearch/2.0 (public product research; no login)",
            "Accept": "application/json" if site == "reddit" else "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9"}


def count(text):
    match = re.search(r"(?<![\d.])(\d[\d,]*(?:\.\d+)?)\s*([km])?", str(text), re.I)
    return int(float(match[1].replace(",", "")) * {None: 1, "k": 1000, "m": 1000000}[match[2].lower() if match[2] else None]) if match else None


def money(text):
    text = str(text)
    currency = next((code for pattern, code in [(r"CA\$|CAD", "CAD"), (r"AU\$|AUD", "AUD"),
        (r"₫|VND", "VND"), (r"€|EUR", "EUR"), (r"£|GBP", "GBP"), (r"\$|USD", "USD")] if re.search(pattern, text, re.I)), None)
    match = re.search(r"\d[\d,.]*", text)
    if not match:
        return None, currency
    value = match[0].rstrip(".,")
    if currency == "VND":
        value = re.sub(r"[,.]", "", value)
    elif currency == "EUR" and "," in value and ("." not in value or value.rfind(",") > value.rfind(".")):
        value = value.replace(".", "").replace(",", ".")
    else:
        value = value.replace(",", "")
    try:
        return float(value), currency
    except ValueError:
        return None, currency


def rating(text):
    match = re.search(r"([0-5](?:[.,]\d+)?)\s*(?:out of|of|trên|sur|von)\s*5", str(text), re.I)
    return float(match[1].replace(",", ".")) if match and float(match[1].replace(",", ".")) <= 5 else None


class PublicScraper:
    source = ""

    def __init__(self, timeout=15, retries=1, cancel=None):
        self.timeout, self.retries, self.cancel = timeout, max(1, min(retries, 3)), cancel
        self.session = requests.Session()
        self.last_status = {}
        self.raw_snapshot = None

    def _fetch(self, url, parser):
        self.last_status = {"source": self.source, "url": url, "status": "unavailable", "requests": 0, "count": 0}
        self.raw_snapshot = None
        for attempt in range(self.retries):
            if self.cancel:
                self.cancel()
            self.last_status["requests"] += 1
            try:
                response = self.session.get(url, headers=headers(self.source), timeout=self.timeout)
            except requests.RequestException:
                self.last_status.update(reason="Lỗi kết nối hoặc timeout; chưa có dữ liệu nguồn")
                break
            if self.cancel:
                self.cancel()
            self.last_status["http_status"] = response.status_code
            self.raw_snapshot = response.text[:8_000_000]
            blocked = re.search(r"captcha|robot.?check|validatecaptcha|cf-turnstile|challenge-running|datadome|aws.?waf|goku.?props|bm-verify|akam-logo|interstitialchallenge|please enable js|are you a human", response.text, re.I)
            if response.status_code in {401, 403, 429} or blocked:
                self.last_status.update(status="blocked", reason="Nguồn chặn/yêu cầu xác minh; dừng nguồn, không vượt CAPTCHA hoặc đổi IP")
                break
            if response.status_code != 200:
                self.last_status.update(reason="HTTP " + str(response.status_code))
                if response.status_code >= 500 and attempt + 1 < self.retries:
                    time.sleep(1)
                    continue
                break
            try:
                rows = parser(response.text)
            except (ValueError, TypeError, KeyError, AttributeError):
                self.last_status.update(reason="Cấu trúc trang/JSON chưa đọc được; không coi là không có sản phẩm")
                break
            if rows:
                self.last_status.update(status="available", count=len(rows))
            elif re.search(r"no results|did not match any products|couldn.t find|nothing here", response.text, re.I):
                self.last_status.update(status="empty", reason="Trang nguồn công bố không có kết quả")
            else:
                self.last_status.update(reason="HTTP 200 nhưng chưa có thẻ dữ liệu; có thể trang yêu cầu JavaScript hoặc đã đổi cấu trúc")
            return rows
        return []


class AmazonScraper(PublicScraper):
    source = "amazon"

    def search(self, keyword, limit=25, sort="relevance"):
        # Search position is not a sales ranking; keep the measured query.
        return self._fetch("https://www.amazon.com/s?k=" + quote_plus(keyword)+"&language=en_US&currency=USD", lambda body: self._parse_amazon_html(body, limit))

    def _parse_sales_volume(self, text):
        return count(text) if re.search(r"\bbought\b", text or "", re.I) else None

    def _parse_amazon_html(self, body, limit):
        soup, output, seen = BeautifulSoup(body, "html.parser"), [], set()
        cards = soup.select('[data-component-type="s-search-result"]') or soup.select(".s-result-item[data-asin]")
        for card in cards:
            asin = str(card.get("data-asin", "")).strip()
            title = card.select_one("h2 a span") or card.select_one("h2 span") or card.select_one("h2")
            if not re.fullmatch(r"[A-Z0-9]{10}", asin) or asin in seen or title is None:
                continue
            seen.add(asin)
            price = card.select_one(".a-price .a-offscreen")
            amount, currency = money(price.get_text(" ", strip=True)) if price else (None, None)
            stars = card.select_one(".a-icon-alt")
            reviews = card.select_one('a[href*="customerReviews"] span')
            review_count = count(reviews.get_text()) if reviews else None
            # Review counts can be in an explicitly labelled rating-count link.
            if review_count is None:
                labelled = card.select_one('[aria-label*="ratings"], [aria-label*="reviews"]')
                review_count = count(labelled.get("aria-label")) if labelled else None
            match = re.search(r"\d[\d,.]*\s*[KM]?\+?\s+bought\s+in\s+(?:the\s+)?(?:past|last)\s+month", card.get_text(" ", strip=True), re.I)
            bought = match[0] if match else None
            image = card.select_one("img.s-image")
            badge = card.select_one(".a-badge-text")
            sponsored = bool(card.select_one('[data-component-type="sp-sponsored-result"]')) or any(s.get_text(strip=True).casefold() == "sponsored" for s in card.select("span"))
            sales = self._parse_sales_volume(bought)
            output.append({"source": "Amazon", "id": asin, "title": title.get_text(" ", strip=True),
                "price": amount, "currency": currency, "rating": rating(stars.get_text()) if stars else None,
                "review_count": review_count, "rating_scope": "listing_may_share_variants", "sales_count": sales,
                "purchase_lower_bound": sales, "bought_label": bought, "purchase_scope": "amazon_search_card_past_month",
                "badge": badge.get_text(" ", strip=True) if badge else None, "sponsored": sponsored,
                "link": "https://www.amazon.com/dp/" + asin, "image": image.get("src") if image else None,
                "hotness_score": sales or 0, "snippet": None, "subreddit": None})
            if len(output) >= limit:
                break
        return output

    def detail(self, asin):
        if not re.fullmatch(r"[A-Z0-9]{10}", asin):
            raise ValueError("ASIN không hợp lệ")
        return self._fetch("https://www.amazon.com/dp/" + asin, self._parse_detail)

    def _parse_detail(self, body):
        soup = BeautifulSoup(body, "html.parser")
        title = soup.select_one("#productTitle")
        if not title:
            return []
        description = soup.select_one("#feature-bullets")
        reviews = []
        for card in soup.select('[data-hook="review"]')[:20]:
            content = card.select_one('[data-hook="review-body"]')
            if content:
                stars = card.select_one('[data-hook="review-star-rating"]')
                reviews.append({"id": card.get("id"), "text": content.get_text(" ", strip=True)[:1500],
                    "rating": rating(stars.get_text()) if stars else None})
        return [{"title": title.get_text(" ", strip=True), "description": description.get_text(" ", strip=True) if description else "", "reviews": reviews}]


class EtsyScraper(PublicScraper):
    source = "etsy"

    def search(self, keyword, limit=25, sort="most_relevant"):
        return self._fetch("https://www.etsy.com/search?q=" + quote_plus(keyword) + "&explicit=1", lambda body: self._parse_etsy_html(body, limit))

    def _parse_in_cart_count(self, text):
        return count(text) if re.search(r"\bcarts?\b|people.*their cart", text or "", re.I) else None

    def _parse_etsy_html(self, body, limit):
        soup, output, seen = BeautifulSoup(body, "html.parser"), [], set()
        cards = soup.select('li[data-listing-id], div[data-listing-id], .v2-listing-card') or soup.select('a[href*="/listing/"]')
        for card in cards:
            link = card if card.name == "a" else card.select_one('a[href*="/listing/"]')
            href = html.unescape(link.get("href", "")) if link else ""
            match = re.search(r"/listing/(\d+)", href)
            if not match or match[1] in seen:
                continue
            title = card.select_one("h3, h2, .v2-listing-card__title")
            name = title.get_text(" ", strip=True) if title else link.get("title", "")
            image = card.select_one("img")
            if not name and image:
                name = image.get("alt", "")
            if not name:
                continue
            seen.add(match[1])
            price = card.select_one(".currency-value")
            scope = price.parent.get_text(" ", strip=True) if price else ""
            amount, currency = money(scope)
            text = card.get_text(" ", strip=True)
            cart = re.search(r"in\s+\d+\+?\s+carts?|over\s+\d+\+?\s+people.*?their\s+cart", text, re.I)
            stars = card.select_one('[aria-label*="out of 5"], .wt-screen-reader-only')
            # Do not guess whether parenthesized numbers are listing reviews.
            reviews = card.select_one('[data-review-count]')
            output.append({"source": "Etsy", "id": match[1], "title": name, "price": amount, "currency": currency,
                "rating": rating(stars.get("aria-label") or stars.get_text()) if stars else None,
                "rating_scope": "etsy_card_scope_unverified", "review_count": count(reviews.get("data-review-count")) if reviews else None,
                "sales_count": None, "cart_count": self._parse_in_cart_count(cart[0]) if cart else None,
                "bought_label": cart[0] if cart else None, "badge": "Bestseller" if re.search(r"\bbest\s?seller\b", text, re.I) else None,
                "sponsored": bool(re.search(r"\bad by\b|\badvertisement\b", text, re.I)),
                "link": "https://www.etsy.com/listing/" + match[1], "image": (image.get("src") or image.get("data-src")) if image else None,
                "hotness_score": 0, "snippet": None, "subreddit": None})
            if len(output) >= limit:
                break
        return output


class RedditScraper(PublicScraper):
    source = "reddit"

    def search(self, keyword, limit=25, sort="relevance", time_filter="all"):
        if sort not in {"top", "hot", "relevance", "new"} or time_filter not in {"all", "year", "month", "week", "day"}:
            raise ValueError("Bộ lọc Reddit không hợp lệ")
        url = "https://www.reddit.com/search.json?q=" + quote_plus(keyword) + f"&sort={sort}&t={time_filter}&limit={min(limit,100)}"
        return self._fetch(url, lambda body: self._parse_reddit_json(json.loads(body), keyword))

    def _parse_reddit_json(self, data, keyword):
        if not isinstance(data.get("data", {}).get("children"), list):
            raise ValueError("Reddit thiếu children")
        output = []
        for child in data["data"]["children"]:
            post = child.get("data", {})
            if not post.get("title") or not post.get("permalink") or post.get("over_18"):
                continue
            score, comments = post.get("score"), post.get("num_comments")
            published = None
            if isinstance(post.get("created_utc"), (int, float)):
                published = datetime.fromtimestamp(post["created_utc"], timezone.utc).isoformat()
            output.append({"source": "Reddit", "id": post.get("id"), "title": post["title"].strip(),
                "link": urljoin("https://www.reddit.com", post["permalink"]), "external_url": post.get("url"),
                "snippet": str(post.get("selftext") or "")[:2000], "subreddit": "r/" + str(post.get("subreddit") or ""),
                "score": score, "num_comments": comments, "published_at": published, "kind": "discussion",
                "price": None, "currency": None, "rating": None, "review_count": None, "sales_count": None,
                "badge": None, "hotness_score": (score or 0)*1.2 + (comments or 0)*2.5 + (post.get("upvote_ratio") or 0)*100})
        return output
