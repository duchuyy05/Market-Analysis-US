import hashlib
import json
import os
from pathlib import Path
import re
import socket
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
KEYS = ("SERPAPI_API_KEY", "TAVILY_API_KEY", "OPENROUTER_API_KEY")


def now():
    return datetime.now(timezone.utc).isoformat()


def load_env():
    env = {}
    path = ROOT / "api" / ".env"
    if path.exists():
        for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, separator, value = line.partition("=")
            if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key.strip()):
                raise ValueError(f"Invalid .env line {number}; expected KEY=value")
            env[key.strip()] = value.strip().strip('"').strip("'")
    for key in (*KEYS, "OPENROUTER_MODEL"):
        if os.environ.get(key):
            env[key] = os.environ[key].strip()
    return env


def scrub(value, secrets):
    if isinstance(value, dict):
        return {k: "[REDACTED]" if k.lower() in {"api_key", "authorization", *[n.lower() for n in KEYS]}
                else scrub(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        return re.sub(r"(?i)([?&](?:api_key|token)=)[^&#\s]+", r"\1[REDACTED]", value)
    return value


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


class Client:
    def __init__(self, output, env, event=None):
        self.output, self.env = Path(output), env
        self.secrets = [env.get(k, "") for k in KEYS]
        self.calls = []
        self.event = event
        self.reuse_cache = True
        self.max_calls = {"serpapi": 17, "tavily": 2, "openrouter": 2}

    def say(self, message):
        if self.event:
            self.event(message)
        else:
            print(message, flush=True)

    def request(self, provider, params, *, cache=True):
        cache = cache and self.reuse_cache
        fingerprint = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()[:20]
        path = self.output / "raw" / f"{provider}-{fingerprint}.json"
        if cache and not path.exists() and provider != "openrouter":
            # Reuse this session's exact same source request, preserving the original timestamp.
            for old_path in (ROOT / "data").glob(f"*/raw/{path.name}"):
                old = json.loads(old_path.read_text(encoding="utf-8"))
                age = datetime.now(timezone.utc) - datetime.fromisoformat(old["fetched_at_utc"])
                if old.get("parameters") == params and not old.get("error") and age.total_seconds() < 86400:
                    save_json(path, old)
                    break
        if cache and path.exists():
            cached = json.loads(path.read_text(encoding="utf-8"))
            if not cached.get("error") and cached.get("response") is not None:
                self.say(f"Cache: {provider} {params.get('engine', 'search')}")
                return cached
        if sum(c["provider"] == provider for c in self.calls) >= self.max_calls[provider]:
            raise RuntimeError(f"Local {provider} request budget reached")
        key_name = {"serpapi": "SERPAPI_API_KEY", "tavily": "TAVILY_API_KEY", "openrouter": "OPENROUTER_API_KEY"}[provider]
        key = self.env.get(key_name, "")
        if not key or key.lower().endswith("xxx"):
            raise RuntimeError(f"Missing {key_name} in api/.env")
        endpoint = {"serpapi": "https://serpapi.com/search.json", "tavily": "https://api.tavily.com/search",
                    "openrouter": "https://openrouter.ai/api/v1/chat/completions"}[provider]
        if provider == "serpapi":
            request = Request(endpoint + "?" + urlencode({**params, "api_key": key}))
        else:
            request = Request(endpoint, data=json.dumps(params).encode("utf-8"), method="POST",
                              headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        self.say(f"Calling: {provider} {params.get('engine', 'search')} (one request)")
        event = {"provider": provider, "engine": params.get("engine"), "started_at_utc": now()}
        self.calls.append(event)
        envelope = {"provider": provider, "endpoint": endpoint, "parameters": params,
                    "fetched_at_utc": now(), "raw_file": str(path.relative_to(self.output)).replace('\\', '/')}
        try:
            with urlopen(request, timeout=180 if provider == "openrouter" else 60) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Expected JSON object")
            envelope["response"] = payload
            if provider == "openrouter":
                for choice in payload.get("choices", []):
                    message = choice.get("message") or {}
                    message.pop("reasoning", None)
                    message.pop("reasoning_details", None)
            if payload.get("error"):
                envelope["error"] = "Provider returned error; inspect sanitized raw response"
        except HTTPError as error:
            envelope["error"] = f"HTTP {error.code}; no retry"
        except (URLError, socket.timeout, TimeoutError, OSError):
            envelope["error"] = "Network/timeout error; no retry"
        except (ValueError, UnicodeError):
            envelope["error"] = "Invalid JSON response; no retry"
        envelope = scrub(envelope, self.secrets)
        save_json(path, envelope)
        event["status"] = envelope.get("error", "received")
        if envelope.get("error"):
            raise RuntimeError(envelope["error"])
        return envelope


def public_json(url):
    try:
        with urlopen(Request(url), timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        raise RuntimeError("Cannot fetch public OpenRouter model catalog") from None
