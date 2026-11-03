"""Public indexed pages are discovery evidence, never a platform sales feed."""
from urllib.parse import urlsplit

SOURCE_DOMAINS = {"tiktok": "tiktok.com", "facebook": "facebook.com", "etsy": "etsy.com",
                  "walmart": "walmart.com", "pinterest": "pinterest.com", "ebay": "ebay.com"}


def source_for(url):
    host = (urlsplit(url).hostname or "").lower()
    return next((key for key, domain in SOURCE_DOMAINS.items() if host == domain or host.endswith("." + domain)), None)


def providers(client, config):
    """Auto uses configured keys; custom transports retain legacy Tavily tests."""
    mode = config.get("discovery", {}).get("web_provider", "auto")
    if mode in {"tavily", "exa"}:
        return [mode]
    if mode == "combined":
        return ["tavily", "exa"]
    env = getattr(client, "env", {})
    available = [name for name, key in (("tavily", "TAVILY_API_KEY"), ("exa", "EXA_API_KEY")) if env.get(key)]
    if getattr(client, "transport", None) and "tavily" not in available:
        available.insert(0, "tavily")
    return available


def remaining(client, provider):
    cap = client.config["limits"].get(provider + "_requests", 0)
    used = sum(u["provider"] == provider for u in client.run.manifest["usage"])
    return max(0, cap - used)


def search(client, query, sites=None, *, provider="tavily"):
    if provider == "exa":
        from .exa import search as exa_search
        return exa_search(client, query, sites, client.config.get("as_of_date"))
    params = {"query": query, "search_depth": "basic", "max_results": 8, "include_raw_content": False,
              "include_answer": False, "include_usage": True, "country": "united states", "topic": "general"}
    if sites:
        params["include_domains"] = [SOURCE_DOMAINS[site] for site in sites]
    return client.request("tavily", params)
