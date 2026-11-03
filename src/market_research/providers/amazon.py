"""Amazon source requests; ranking/selection belong to workflow stages."""


def search(client, query):
    return client.request("serpapi", {"engine": "amazon", "k": query, "amazon_domain": "amazon.com", "language": "en_US", "shipping_location": "US"}, purpose="amazon_search")


def detail(client, asin):
    return client.request("serpapi", {"engine": "amazon_product", "asin": asin, "amazon_domain": "amazon.com", "language": "en_US", "shipping_location": "US"}, purpose="amazon_detail")
