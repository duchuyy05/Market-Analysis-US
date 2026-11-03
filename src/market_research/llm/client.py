"""LLM tasks never own metrics, source IDs, rankings or report rendering."""
import json
import re
from pathlib import Path

from ..providers.client import SourceError, BudgetExceeded


def json_object(body, *, allow_singleton_array=False):
    """Accept a JSON object, optionally wrapped in one complete single-item array."""
    if not isinstance(body, str) or len(body) > 200000:
        raise ValueError("Invalid model content")
    body = re.sub(r"^```(?:json)?\s*|\s*```$", "", body.strip())
    try:
        result = json.loads(body)
    except ValueError:
        # A frequent free-model response has a short introduction before JSON.
        starts = [index for token in ("{", "[") if (index := body.find(token)) >= 0]
        start = min(starts, default=-1)
        if not 0 <= start <= 2000:
            raise
        result, end = json.JSONDecoder().raw_decode(body[start:])
        # Never salvage the first object from a truncated/multi-plan array.
        if isinstance(result, list) and body[start + end:].strip():
            raise ValueError("Unexpected content after JSON array")
    if allow_singleton_array and isinstance(result, list) and len(result) == 1 and isinstance(result[0], dict):
        result = result[0]
    if not isinstance(result, dict):
        raise ValueError("Expected JSON object")
    return result


def validate_result(task, result, payload):
    if task == "understand":
        from .plan import validate_plan
        return validate_plan(result, payload)
    elif task == "cluster":
        groups = result.get("directions")
        ids = {k["id"] for k in payload["keywords"]}
        if not isinstance(groups, list) or not groups:
            raise ValueError("cluster thiếu directions")
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("name"), str) or not isinstance(group.get("keyword_ids"), list) or not group["keyword_ids"] or any(not isinstance(i, str) or i not in ids for i in group["keyword_ids"]) or group.get("representative_keyword_id") not in group["keyword_ids"]:
                raise ValueError("cluster chứa keyword ID ngoài đầu vào")
    elif task == "extract" and not isinstance(result.get("candidates"), list):
        raise ValueError("extract thiếu candidates")
    elif task == "expand" and not isinstance(result.get("candidates"), list):
        raise ValueError("expand thiếu candidates")
    return result


class InvalidOutput(ValueError):
    def __init__(self, kind, message, *, body=None, model=None, finish=None):
        super().__init__(message)
        self.kind, self.body, self.model, self.finish = kind, body, model, finish


def decode_response(task, envelope, payload, requested_model):
    response = envelope.get("response") or {}
    if not isinstance(response, dict):
        raise InvalidOutput("empty_choices", "LLM trả cấu trúc phản hồi không hợp lệ", model=requested_model)
    choices = response.get("choices") or []
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise InvalidOutput("empty_choices", "LLM không trả lựa chọn nội dung", model=response.get("model", requested_model))
    choice = choices[0]
    message = choice.get("message") or {}
    actual = response.get("model") or requested_model
    if not isinstance(actual, str):
        actual = requested_model
    finish = choice.get("finish_reason")
    if not isinstance(message, dict):
        raise InvalidOutput("empty_content", "Model trả cấu trúc message không hợp lệ", model=actual, finish=finish)
    body = message.get("content")
    if isinstance(body, list):
        body = "".join(part.get("text", "") for part in body if isinstance(part, dict) and part.get("type") in {"text", "output_text"} and isinstance(part.get("text"), str))
    if message.get("refusal") or finish in {"content_filter", "safety"}:
        raise InvalidOutput("refusal", "Model từ chối tác vụ; cần xem lại phạm vi hoặc chọn model free khác", model=actual, finish=finish)
    if finish in {"length", "max_tokens"}:
        raise InvalidOutput("token_limit", "Model hết trần token trước khi trả đủ JSON; đây không phải lỗi API key", body=body, model=actual, finish=finish)
    if not isinstance(body, str) or not body.strip():
        raise InvalidOutput("empty_content", "Model trả phản hồi rỗng, chưa có JSON để xử lý", model=actual, finish=finish)
    try:
        result = json_object(body, allow_singleton_array=task == "understand")
    except ValueError as error:
        raise InvalidOutput("invalid_json", "Model trả nội dung chưa đúng JSON", body=body, model=actual, finish=finish) from error
    try:
        return validate_result(task, result, payload)
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise InvalidOutput("invalid_schema", "JSON chưa đúng dữ liệu tác vụ: " + str(error)[:400], body=body, model=actual, finish=finish) from error


def complete(client, task, payload):
    if task == "understand":
        from ..control import check_cancel
        from .saved_plan import recover_saved_plan
        check_cancel(client.cancel_event)
        saved = recover_saved_plan(client.run.path, payload)
        if saved:
            client.run.log(client.run.manifest.get("current_stage", task), "llm_saved_plan_revalidated",
                           "Dùng lại phản hồi đã lưu sau khi kiểm tra nhóm và chất lượng seed theo input hiện tại; không gọi thêm API", task=task, **saved)
            return saved["result"]
    model = client.config["llm"].get("model") or client.env.get("OPENROUTER_MODEL") or "openrouter/free"
    if model != "openrouter/free" and not model.endswith(":free"):
        raise SourceError("Bản này chỉ gọi model free; model trả phí cần cấu hình ngân sách riêng")
    prompt = (Path(__file__).parent / "prompts" / f"{task}.txt").read_text(encoding="utf-8")
    from .models import catalog, eligible_models
    unusable = client.run.manifest.setdefault("llm_unusable_models", {})
    maximum = client.config["limits"]["max_output_tokens"]
    if maximum < 1:
        raise SourceError("Trần max_output_tokens phải lớn hơn 0 khi sử dụng LLM")
    remaining = client.config["limits"]["llm_requests"] - sum(u["provider"] == "openrouter" for u in client.run.manifest["usage"])
    models = catalog(client) if remaining > 0 else []
    metadata = {row["id"]: row for row in models if isinstance(row, dict) and isinstance(row.get("id"), str)}
    compatible = eligible_models(models, maximum)
    reasoning = metadata.get(model, {}).get("reasoning") or {}
    mandatory = isinstance(reasoning, dict) and reasoning.get("mandatory") is True
    incompatible = bool(models) and model != "openrouter/free" and model not in compatible
    if mandatory or incompatible:
        client.run.log(client.run.manifest.get("current_stage", task), "llm_model_incompatible",
                       "Model cấu hình bắt buộc reasoning" if mandatory else "Metadata chưa xác nhận model cấu hình tương thích chat/text JSON và trần token; không gửi thử model giọng nói/embedding",
                       model=model, fallback="Chọn model free tương thích")
    primary = [] if mandatory or incompatible or model in unusable or (model == "openrouter/free" and compatible) else [model]
    available = [name for name in dict.fromkeys([*primary, *compatible, "openrouter/free"]) if name not in unusable or name == "openrouter/free"]
    candidates = available[:1]
    if candidates:
        # Free variants from the same vendor often share an upstream limit.
        # Prefer a different vendor for the second bounded attempt.
        other = next((name for name in available[1:] if name.split("/", 1)[0] != candidates[0].split("/", 1)[0]), None)
        other = other or next(iter(available[1:]), None)
        if other:
            candidates.append(other)
    last_error, malformed = None, None
    unavailable_models = set()
    stage = client.run.manifest.get("current_stage", task)
    client.run.log(stage, "llm_task", "Chuẩn bị tác vụ LLM", task=task, model=candidates[0] if candidates else None, configured_model=model, candidate_models=candidates,
                   input_keyword_count=len(payload.get("keywords", [])), page_count=len(payload.get("pages", [])))
    messages = [{"role": "system", "content": prompt}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]

    def request(selected, content, *, recovery=False):
        params = {"model": selected, "messages": content,
                  "response_format": {"type": "json_object"}, "max_tokens": maximum,
                  "provider": {"require_parameters": True, "max_price": {"prompt": 0, "completion": 0}},
                  "temperature": 1.0 if selected.startswith("recursive/flint-") else 0.2}
        supported = metadata.get(selected, {}).get("supported_parameters")
        if supported is None or "reasoning" in supported:
            params["reasoning"] = {"enabled": False, "exclude": True}
        envelope = client.request("openrouter", params, purpose="llm_" + task)
        try:
            result = decode_response(task, envelope, payload, selected)
            client.run.log(stage, "llm_repaired" if recovery else "llm_result", "LLM trả kết quả hợp lệ", task=task, model=envelope["response"].get("model", selected), result=result)
            return result
        except InvalidOutput as error:
            error.requested_model = selected
            client.invalidate(envelope, str(error))
            usage = (envelope.get("response") or {}).get("usage") or {}
            usage = usage if isinstance(usage, dict) else {}
            details = usage.get("completion_tokens_details") or {}
            client.run.log(stage, "llm_invalid_json" if error.kind in {"invalid_json", "invalid_schema"} else "llm_empty_output",
                           str(error), task=task, model=error.model, requested_model=selected, kind=error.kind,
                           finish_reason=error.finish, visible_characters=len(error.body or ""),
                           completion_tokens=usage.get("completion_tokens"),
                           reasoning_tokens=details.get("reasoning_tokens") if isinstance(details, dict) else None)
            if error.kind in {"empty_choices", "empty_content", "token_limit", "refusal"}:
                blocked = error.model if error.model and error.model.endswith(":free") else selected
                if blocked != "openrouter/free":
                    unusable[blocked] = str(error)
                    if selected != "openrouter/free":
                        unusable[selected] = str(error)
                    client.run.save()
                    client.run.log(stage, "llm_model_circuit", str(error), model=blocked)
            raise

    for selected in candidates:
        if selected in unusable and selected != "openrouter/free":
            continue
        try:
            return request(selected, messages)
        except BudgetExceeded:
            raise
        except InvalidOutput as error:
            last_error, malformed = error, error
        except SourceError as error:
            last_error = error
            unavailable_models.add(selected)
            if error.status_code in {400, 404}:
                unusable[selected] = str(error)
                client.run.save()
            client.run.log(stage, "llm_error", str(error), task=task, model=selected)
    # At most two model attempts plus one distinct repair/regeneration, always
    # through Client so retries, stop and the frozen request budget still apply.
    if malformed:
        repairable = malformed.kind in {"invalid_json", "invalid_schema"} and isinstance(malformed.body, str) and bool(malformed.body.strip())
        extra = ([{"role": "assistant", "content": malformed.body[:10000]}] if repairable else [])
        instruction = ("Previous response failed validation: " + str(malformed) + ". " if repairable else "Previous attempt produced no complete visible JSON. Generate a fresh answer without reasoning text. ")
        if task == "understand":
            instruction += "Return 1 to 5 niches, normally 3, not one per company category. Every niches[].seeds[] must be a natural English ASCII search phrase. Translate Vietnamese product seeds to English; do not remove accents or return Vietnamese seeds. Keep only hard requirements explicitly supplied by the user; soft affordability or convenience wishes belong in preferences. "
        instruction += "Return ONLY one compact JSON object using the original supplied data and IDs. No commentary or markdown."
        recovery_messages = [*messages, *extra, {"role": "user", "content": instruction}]
        preferred = getattr(malformed, "requested_model", None) if repairable else None
        selected = preferred if preferred and preferred not in unavailable_models and preferred not in unusable else next((name for name in compatible if name not in unusable and name not in unavailable_models), "openrouter/free")
        client.run.log(stage, "llm_repair" if repairable else "llm_regenerate", "Thử khôi phục phản hồi LLM một lần trong trần còn lại", task=task, model=selected, kind=malformed.kind)
        try:
            return request(selected, recovery_messages, recovery=True)
        except BudgetExceeded:
            raise
        except (SourceError, InvalidOutput) as error:
            last_error = error
            client.run.log(stage, "llm_repair_failed", "Không khôi phục được JSON trong ngân sách; chuyển cách xử lý của bước", task=task, reason=str(error))
    elif isinstance(last_error, SourceError) and last_error.status_code == 429:
        # Use the same final recovery slot for a third vendor when both initial
        # providers were unavailable. Never add a fourth completion attempt.
        vendors = {name.split("/", 1)[0] for name in unavailable_models}
        selected = next((name for name in available if name not in unavailable_models and name not in unusable and name.split("/", 1)[0] not in vendors and (name != "openrouter/free" or not models)), None)
        if selected:
            client.run.log(stage, "llm_rate_limit_recovery", "Hai lựa chọn trước chưa dùng được; thử một nguồn khác trong lượt khôi phục cuối", task=task, model=selected)
            try:
                return request(selected, messages)
            except BudgetExceeded:
                raise
            except (SourceError, InvalidOutput) as error:
                last_error = error
                client.run.log(stage, "llm_recovery_failed", "Chưa có nguồn LLM dùng được sau lượt khôi phục cuối; giữ dữ liệu để chạy tiếp", task=task, model=selected, reason=str(error))
    if isinstance(last_error, InvalidOutput):
        used = sum(u["provider"] == "openrouter" for u in client.run.manifest["usage"])
        cap = client.config["limits"]["llm_requests"]
        raise SourceError(f"{last_error}. Đã dùng {used}/{cap} lượt OpenRouter; chưa có kết quả tác vụ hợp lệ. Xem log model/token; khởi động lại server sau cập nhật và chạy tiếp nếu còn trần.") from last_error
    raise last_error or SourceError("Không có model free phù hợp để xử lý tác vụ")
