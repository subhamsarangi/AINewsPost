"""URL normalization + embedding-based clustering.

Step 4 (now): normalize_url only. Ingesters import it.
Step 7 (later): cluster_new_items() gets added below.
"""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PARAMS = {
    "fbclid",
    "gclid",
    "dclid",
    "msclkid",
    "igshid",
    "ref",
    "ref_src",
    "mc_cid",
    "mc_eid",
    "_hsenc",
    "_hsmi",
    "mkt_tok",
    "yclid",
}


def normalize_url(url: str) -> str:
    """Canonical form of a URL, used as the unique key for items.

    https only, lowercase host, no www., no fragment, no tracking params,
    sorted query params, no trailing slash (except root).
    """
    url = (url or "").strip()
    if not url:
        return url
    if "://" not in url:
        url = "https://" + url
    try:
        parts = urlsplit(url)
    except ValueError:
        return url

    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return url
    if parts.port and parts.port not in (80, 443):
        host = f"{host}:{parts.port}"

    query = sorted(
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS
    )
    path = parts.path.rstrip("/") or ""
    return urlunsplit(("https", host, path, urlencode(query), ""))
