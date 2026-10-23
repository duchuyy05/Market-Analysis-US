"""Read provider account usage without sending search or model requests."""
import json
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .io import load_env


def remaining(limit, used):
    if type(limit) not in (int,float) or type(used) not in (int,float):
        return None
    return max(0,limit-used)


def check_quota():
    env=load_env()
    endpoints={"SerpApi":("SERPAPI_API_KEY","https://serpapi.com/account.json"),
               "Tavily":("TAVILY_API_KEY","https://api.tavily.com/usage"),
               "OpenRouter":("OPENROUTER_API_KEY","https://openrouter.ai/api/v1/key")}
    result={}
    for name,(key_name,url) in endpoints.items():
        key=env.get(key_name)
        if not key:
            result[name]={"error":"Chưa có key trong api/.env"}
            continue
        request=Request(url+"?"+urlencode({"api_key":key})) if name=="SerpApi" else Request(url,headers={"Authorization":"Bearer "+key})
        try:
            with urlopen(request,timeout=20) as response:
                body=json.load(response)
            if name=="SerpApi":
                result[name]={"plan":body.get("plan_name"),"monthly_price":body.get("plan_monthly_price"),
                    "remaining_plan_searches":body.get("plan_searches_left"),"used_this_month":body.get("this_month_usage"),
                    "extra_credits":body.get("extra_credits")}
            elif name=="Tavily":
                account,key_usage=body.get("account") or {},body.get("key") or {}
                result[name]={"plan":account.get("current_plan"),"plan_limit":account.get("plan_limit"),
                    "plan_used":account.get("plan_usage"),"plan_remaining":remaining(account.get("plan_limit"),account.get("plan_usage")),
                    "key_remaining":remaining(key_usage.get("limit"),key_usage.get("usage")),"paygo_used":account.get("paygo_usage")}
            else:
                account=body.get("data") or {}
                result[name]={"model":env.get("OPENROUTER_MODEL","openrouter/free"),"is_free_tier":account.get("is_free_tier"),
                    "usage_usd":account.get("usage"),"key_spending_limit_usd":account.get("limit"),
                    "key_spending_remaining_usd":account.get("limit_remaining"),"free_requests_remaining":None,
                    "note":"API không trả số lượt miễn phí còn lại. Giới hạn chi tiêu của key không phải số lượt gọi hoặc số dư tài khoản."}
        except HTTPError as error:
            result[name]={"error":f"HTTP {error.code}; chưa xác minh hạn mức"}
        except (OSError,ValueError,TypeError):
            result[name]={"error":"Không đọc được API hạn mức; chưa xác minh"}
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return result
