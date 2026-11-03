"""Bounded HTTP, sanitized raw observations and persistent request accounting."""
import hashlib
import json
import os
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..common import ROOT, now, read_json, write_json
from ..control import check_cancel

KEYS = ("SERPAPI_API_KEY", "TAVILY_API_KEY", "EXA_API_KEY", "OPENROUTER_API_KEY", "OPENROUTER_MODEL")


class SourceError(RuntimeError):
    def __init__(self, message, *, status_code=None, provider=None, details=None):
        super().__init__(message)
        self.status_code, self.provider, self.details = status_code, provider, details or {}


class BudgetExceeded(SourceError):
    pass


def environment(root=ROOT):
    values = {}
    for path in (Path(root) / "api/.env", Path(root) / ".env"):
        if path.exists():
            for line in path.read_text(encoding="utf-8-sig").splitlines():
                if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    if k.strip() in KEYS:
                        values[k.strip()] = v.strip().strip("\"'")
    values.update({k: os.environ[k] for k in KEYS if os.environ.get(k)})
    return values


def scrub(value, secrets=()):
    if isinstance(value, dict):
        return {k: "[REDACTED]" if k.lower() in {"api_key", "x-api-key", "authorization", "token", "serpapi_api_key", "tavily_api_key", "exa_api_key", "openrouter_api_key"} else scrub(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v, secrets) for v in value]
    if isinstance(value, str):
        import re
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        return re.sub(r"(?i)([?&](?:api_key|token)=)[^&#\s]+", r"\1[REDACTED]", value)
    return value


class Client:
    def __init__(self, run, config, transport=None, cancel_event=None):
        self.run, self.config = run, config
        self.env = environment(run.root)
        self.transport = transport
        self.cancel_event = cancel_event
        self.started = time.monotonic()
        self.free_trends_error = None

    def log(self, event, message, **details):
        """Provider diagnostics are bounded and contain no credentials/widget codes."""
        logger = getattr(self.run, "log", None)
        if not callable(logger):
            return
        secrets = [self.env.get(k, "") for k in KEYS if k.endswith("KEY")]
        def bounded(value):
            if isinstance(value, dict):
                return {k: bounded(v) for k, v in list(value.items())[:40] if k.lower() not in {"widget_code", "reasoning", "reasoning_details", "cookie", "set-cookie"}}
            if isinstance(value, list):
                return [bounded(v) for v in value[:20]]
            if isinstance(value, str):
                return value[:6000]
            return value
        logger(self.run.manifest.get("current_stage", "provider"), event, message,
               **bounded(scrub(details, secrets)))

    def trends_budget(self, purpose=None):
        """Paid Trends shares the total cap while protecting product-search quota."""
        limits = self.config["limits"]
        usage = self.run.manifest["usage"]
        total_used = sum(u["provider"] == "serpapi" for u in usage)
        trend_used = sum(u["provider"] == "serpapi" and u.get("engine") == "google_trends" for u in usage)
        broad = self.config.get("discovery", {}).get("enabled", False)
        guarded = (broad or self.config.get("trends", {}).get("history_scope") == "seasonal") and "trends_serpapi_requests" in limits
        reserve = limits.get("serpapi_product_reserve", 0) if guarded else 0
        cap = min(limits.get("trends_serpapi_requests", limits["serpapi_requests"]), max(0, limits["serpapi_requests"] - reserve)) if guarded else limits["serpapi_requests"]
        from ..workflow.planning import trends_plan
        plan = trends_plan(self.config)
        history_used = sum(u["provider"] == "serpapi" and u.get("purpose") == "trends_history" for u in usage)
        remaining = max(0, min(cap - trend_used, limits["serpapi_requests"] - total_used))
        history_reserved = min(remaining, max(0, getattr(self, "history_reserve_target", plan["history_reserve"]) - history_used))
        if purpose in {"trends_screen", "trends_related"}:
            remaining = max(0, remaining - history_reserved)
        return {"total_cap": limits["serpapi_requests"], "total_used": total_used,
                "trends_cap": cap, "trends_used": trend_used, "product_reserve": reserve,
                "remaining": remaining, "history_reserve": history_reserved,
                "related_cap": limits.get("trends_related_requests", 0) if guarded else None,
                "related_used": sum(u["provider"] == "serpapi" and u.get("engine") == "google_trends" and (u.get("purpose") == "trends_related" or u.get("data_type") == "RELATED_QUERIES") for u in usage)}

    def invalidate(self, envelope, reason):
        """Retain raw observations, but never replay a semantically invalid cache."""
        provider = envelope.get("provider")
        if provider not in {"google_trends_free", "serpapi", "tavily", "exa", "openrouter"}:
            return
        boundary = (self.run.path / "raw" / provider).resolve()
        if not boundary.is_relative_to(self.run.path.resolve()):
            self.log("cache_invalidation_rejected", "Không sửa thư mục raw nằm ngoài lượt nghiên cứu", provider=provider)
            return
        files = [envelope.get("raw_file"), *envelope.get("request_raw_files", [])]
        invalidated = []
        for raw_file in dict.fromkeys(item for item in files if isinstance(item, str)):
            path = (self.run.path / raw_file).resolve()
            if not path.is_relative_to(boundary) or path.suffix != ".json":
                self.log("cache_invalidation_rejected", "Không sửa raw ngoài ranh giới nguồn", provider=provider)
                continue
            previous = read_json(path)
            if not isinstance(previous, dict):
                continue
            if provider == "openrouter" and not previous.get("validation_error"):
                # A fresh request can replace the fingerprint cache. Keep the
                # original unusable reply separately so its log stays auditable.
                token = hashlib.sha256(json.dumps([previous.get("retrieved_at"), reason], ensure_ascii=False).encode()).hexdigest()[:12]
                archived = path.with_name(path.stem + ".invalid-" + token + ".json")
                write_json(archived, scrub({**previous, "validation_error": str(reason)[:1000], "error": str(reason)[:1000]}, [self.env.get(k, "") for k in KEYS if k.endswith("KEY")]))
                invalidated.append(str(archived.relative_to(self.run.path)).replace("\\", "/"))
            previous.update(error="Dữ liệu chưa dùng được: " + str(reason)[:1000], validation_error=str(reason)[:1000], invalidated_at=now())
            previous = scrub(previous, [self.env.get(k, "") for k in KEYS if k.endswith("KEY")])
            write_json(path, previous)
            if provider in {"google_trends_free", "tavily", "exa"}:
                shared = self.run.root / "data/cache" / provider / path.name
                saved = read_json(shared)
                if isinstance(saved, dict):
                    saved.update(error=previous["error"], validation_error=previous["validation_error"], invalidated_at=previous["invalidated_at"])
                    write_json(shared, saved)
            invalidated.append(raw_file)
        if invalidated:
            self.log("cache_invalidated", "Giữ raw để kiểm tra, đánh dấu cache cần lấy lại", provider=provider, reason=reason, raw_files=invalidated)

    def request(self, provider, params, *, purpose=None):
        check_cancel(self.cancel_event)
        fingerprint = hashlib.sha256(json.dumps([2, provider, params], sort_keys=True).encode()).hexdigest()
        path = self.run.path / "raw" / provider / f"{fingerprint}.json"
        cached = read_json(path)
        if cached and not cached.get("error"):
            self.run.manifest["cache_hits"] = self.run.manifest.get("cache_hits", 0) + 1
            self.run.save()
            self.log("cache_hit", "Dùng phản hồi đã lưu trong lượt", provider=provider, purpose=purpose, parameters=params, raw_file=cached.get("raw_file"))
            return cached
        shared = self.run.root / "data/cache" / provider / f"{fingerprint}.json"
        hours = self.config.get("trends", {}).get("cache_hours", 24)
        if provider in {"google_trends_free", "tavily", "exa"} and hours:
            previous = read_json(shared)
            try:
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(previous["retrieved_at"].replace("Z", "+00:00"))).total_seconds()
                if 0 <= age < hours * 3600 and not previous.get("error"):
                    previous.update(raw_file=str(path.relative_to(self.run.path)).replace("\\", "/"), shared_cache=True)
                    write_json(path, previous)
                    self.run.manifest["shared_cache_hits"] = self.run.manifest.get("shared_cache_hits", 0) + 1
                    self.run.save()
                    self.log("cache_hit", "Dùng cache chung còn hạn", provider=provider, purpose=purpose, parameters=params, raw_file=previous.get("raw_file"), retrieved_at=previous.get("retrieved_at"))
                    return previous
            except (TypeError, KeyError, ValueError):
                pass
        free = provider == "google_trends_free"
        if free and self.free_trends_error:
            raise SourceError(self.free_trends_error)
        cooldown_path = self.run.root / "data/cache/google_trends_free/cooldown.json"
        if free and not self.transport:
            cooldown = read_json(cooldown_path, {})
            if time.time() < cooldown.get("until", 0):
                raise SourceError("Google Trends miễn phí đang nghỉ 15 phút sau HTTP 429")
        # A valid no-results response is frozen within a run; let the search
        # stage broaden its query instead of repeatedly charging for the same miss.
        if cached and cached.get("response", {}).get("error") and any(s in str(cached["response"]["error"]).lower() for s in ("returned any results", "no results")):
            raise SourceError("Nguồn báo lỗi: " + str(cached["response"]["error"])[:600])
        key_name = {"serpapi": "SERPAPI_API_KEY", "tavily": "TAVILY_API_KEY", "exa": "EXA_API_KEY", "openrouter": "OPENROUTER_API_KEY"}.get(provider)
        if not free and not self.transport and not self.env.get(key_name):
            raise SourceError(f"Thiếu {key_name}; cấu hình trong .env hoặc api/.env")
        attempts = 1 if free else self.config["limits"]["retry_attempts"] + 1
        for attempt in range(attempts):
            check_cancel(self.cancel_event)
            if time.monotonic() - self.started > self.config["limits"]["max_run_seconds"]:
                raise BudgetExceeded("Đã chạm giới hạn thời gian chạy")
            count = sum(u["provider"] == provider for u in self.run.manifest["usage"])
            budget_key = {"serpapi": "serpapi_requests", "tavily": "tavily_requests", "exa": "exa_requests", "openrouter": "llm_requests", "google_trends_free": "free_trends_requests"}[provider]
            if count >= self.config["limits"].get(budget_key, 0):
                raise BudgetExceeded(f"Đã chạm ngân sách {provider}: {count} lượt")
            if provider == "serpapi" and params.get("engine") == "google_trends":
                policy = self.trends_budget(purpose)
                if policy["remaining"] <= 0:
                    self.log("budget_blocked", "Không gửi Trends trả phí: giữ trần chung và lượt dành cho sản phẩm", **policy)
                    raise BudgetExceeded(f"Hết phần SerpApi dành cho Trends ở phép đo này ({policy['trends_used']}/{policy['trends_cap']}); trần chung {policy['total_cap']}, giữ {policy['product_reserve']} lượt cho sản phẩm và {policy['history_reserve']} lượt cho lịch sử")
                if params.get("data_type") == "RELATED_QUERIES" and policy["related_cap"] is not None and policy["related_used"] >= policy["related_cap"]:
                    raise BudgetExceeded("Đã chạm trần SerpApi Related Queries; giữ lượt cho sàng lọc và sản phẩm")
            elif provider == "serpapi":
                policy = self.trends_budget()
                if policy["history_reserve"] and policy["total_cap"] - policy["total_used"] <= policy["history_reserve"]:
                    self.log("budget_blocked", "Không gửi mẫu/chi tiết mới: giữ lượt tổng còn lại cho lịch sử Trends", **policy)
                    raise BudgetExceeded(f"Giữ {policy['history_reserve']} lượt SerpApi còn lại cho lịch sử; không tăng trần tổng {policy['total_cap']}")
            event = {"provider": provider, "engine": params.get("engine", params.get("endpoint")), "purpose": purpose, "data_type": params.get("data_type"), "requested_at": now(), "status": "started", "cost_usd": 0 if free else None}
            if provider == "openrouter":
                event["requested_model"] = params.get("model")
            self.run.manifest["usage"].append(event)
            self.run.save()  # Reserve before network, including on process termination.
            self.log("request_started", "Gửi yêu cầu nguồn", provider=provider, purpose=purpose, parameters=params, attempt=attempt + 1, used=count + 1, cap=self.config["limits"][budget_key])
            envelope = {"provider": provider, "parameters": params, "retrieved_at": now(), "raw_file": str(path.relative_to(self.run.path)).replace("\\", "/")}
            retryable = False
            try:
                if self.transport:
                    response = self.transport(provider, params)
                else:
                    response = self._send(provider, params)
                if not isinstance(response, dict):
                    raise ValueError("response is not an object")
                if free and params.get("endpoint") == "explore":
                    for widget in (response.get("widgets") or []):
                        if not isinstance(widget, dict):
                            raise ValueError("Malformed Trends widget")
                        if "token" in widget:
                            widget["widget_code"] = widget.pop("token")
                envelope["response"] = response
                if response.get("error"):
                    envelope["error"] = "Nguồn báo lỗi: " + str(response["error"])[:600]
                    raise SourceError(envelope["error"])
                if provider == "openrouter":
                    for choice in response.get("choices", []):
                        message = choice.get("message") or {}
                        message.pop("reasoning", None)
                        message.pop("reasoning_details", None)
                    event.update(tokens=response.get("usage"), model=response.get("model"))
                    event["cost_usd"] = (response.get("usage") or {}).get("cost")
                if provider == "exa":
                    cost = response.get("costDollars") or {}
                    total = cost.get("total") if isinstance(cost, dict) else None
                    if type(total) in (int, float) and 0 <= total < float("inf"):
                        event["cost_usd"] = total
                    event["billing_scope"] = "provider_reported_cost_credit_or_paid_balance_unknown"
                envelope["response"] = response
                event["status"] = "received"
            except HTTPError as error:
                envelope["error"] = f"HTTP {error.code}"
                envelope["http_status"] = error.code
                # Keep a bounded provider explanation (daily quota, upstream
                # model overload, unsupported settings, auth), never headers.
                try:
                    detail = json.loads(error.read(8193).decode("utf-8"))
                    detail = detail.get("error", detail) if isinstance(detail, dict) else {}
                    if isinstance(detail, dict):
                        reason = detail.get("message")
                        if isinstance(reason, str) and reason.strip():
                            envelope["error"] += ": " + reason[:800]
                        metadata = detail.get("metadata") or {}
                        envelope["provider_error"] = {"code": detail.get("code"), "message": reason[:800] if isinstance(reason, str) else None,
                            "provider_name": metadata.get("provider_name") if isinstance(metadata, dict) else None}
                        upstream = metadata.get("raw") if isinstance(metadata, dict) else None
                        if isinstance(upstream, str):
                            envelope["provider_error"]["raw"] = upstream[:3000]
                            try:
                                parsed = json.loads(upstream)
                                parsed = parsed.get("error", parsed) if isinstance(parsed, dict) else {}
                                upstream_message = parsed.get("message") if isinstance(parsed, dict) else None
                            except (ValueError, TypeError):
                                upstream_message = None
                            if isinstance(upstream_message, str) and upstream_message.strip():
                                envelope["provider_error"]["upstream_message"] = upstream_message[:800]
                                if upstream_message != reason:
                                    envelope["error"] += ": " + upstream_message[:800]
                            elif upstream.strip() and reason == "Provider returned error":
                                envelope["error"] += ": " + upstream[:800]
                        try:
                            retry_after = float(error.headers.get("Retry-After"))
                            if 0 <= retry_after <= 86400:
                                envelope["provider_error"]["retry_after_seconds"] = retry_after
                        except (ValueError, TypeError, AttributeError):
                            pass
                except (OSError, ValueError, TypeError, AttributeError):
                    pass
                if free and error.code == 429 and not self.transport:
                    write_json(cooldown_path, {"until": time.time() + 900, "reason": "HTTP 429", "at": now()})
                retryable = error.code in {408, 429, 500, 502, 503, 504}
                if provider in {"openrouter", "exa", "tavily"} and error.code == 429:
                    # Let the LLM task choose a different model instead of
                    # spending another request on the same limited endpoint.
                    retryable = False
            except (URLError, socket.timeout, TimeoutError, OSError):
                envelope["error"] = "Lỗi mạng hoặc timeout"
                retryable = True
            except (ValueError, TypeError):
                envelope["error"] = "Nguồn không trả dữ liệu JSON hợp lệ"
            except SourceError:
                envelope.setdefault("error", "Nguồn báo lỗi; xem raw đã che key")
            envelope = scrub(envelope, [self.env.get(k, "") for k in KEYS if k.endswith("KEY")])
            write_json(path, envelope)
            event["status"] = envelope.get("error", event["status"])
            self.run.save()
            self.log("request_failed" if envelope.get("error") else "request_received", envelope.get("error", "Đã nhận phản hồi nguồn"), provider=provider, purpose=purpose,
                     raw_file=envelope["raw_file"], response_fields=list(envelope.get("response", {}))[:30], tokens=event.get("tokens"), model=event.get("model"),
                     requested_model=params.get("model") if provider == "openrouter" else None, provider_error=envelope.get("provider_error"))
            # A request already sent may use quota. Keep its response before
            # acknowledging stop, so resume can reuse it without another call.
            check_cancel(self.cancel_event)
            if not envelope.get("error"):
                if provider in {"google_trends_free", "tavily", "exa"} and hours:
                    write_json(shared, envelope)
                return envelope
            if free:
                self.free_trends_error = "Trends miễn phí tạm dừng trong lượt này: " + envelope["error"]
            if not retryable or attempt + 1 == attempts:
                raise SourceError(f"{provider}: {envelope['error']}", status_code=envelope.get("http_status"), provider=provider, details=envelope.get("provider_error"))
            delay = min(2 ** attempt, 4)
            self.log("request_retry", "Thử lại yêu cầu lỗi tạm thời trong trần", provider=provider, purpose=purpose, delay_seconds=delay)
            if self.cancel_event is None:
                time.sleep(delay)
            else:
                self.cancel_event.wait(delay)
                check_cancel(self.cancel_event)

    def _send(self, provider, params):
        if provider == "google_trends_free":
            from .free_trends import send
            return send(self, params)
        if provider == "serpapi":
            url = "https://serpapi.com/search.json?" + urlencode({**params, "api_key": self.env["SERPAPI_API_KEY"]})
            request = Request(url)
        elif provider == "exa":
            request = Request("https://api.exa.ai/search", data=json.dumps(params).encode(),
                headers={"x-api-key": self.env["EXA_API_KEY"], "Content-Type": "application/json"})
        else:
            endpoint = {"tavily": "https://api.tavily.com/search", "openrouter": "https://openrouter.ai/api/v1/chat/completions"}[provider]
            key = self.env[{"tavily": "TAVILY_API_KEY", "openrouter": "OPENROUTER_API_KEY"}[provider]]
            request = Request(endpoint, data=json.dumps(params).encode(), headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
        with urlopen(request, timeout=self.config["limits"]["timeout_seconds"]) as response:
            return json.loads(response.read().decode("utf-8"))
