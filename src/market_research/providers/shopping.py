"""Shopping discovery: positions and ratings are not sales evidence."""


def search(client, query):
    return client.request("serpapi", {"engine": "google_shopping", "q": query, "gl": "us", "hl": "en"}, purpose="shopping_search")
