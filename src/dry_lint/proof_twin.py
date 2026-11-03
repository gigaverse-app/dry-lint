"""Proof only: a re-implementation of sticky.marker for the live sticky test (never merged)."""


def comment_marker(name: str = "") -> str:
    if name:  # a keyed marker
        return f"<!-- dry-lint:{name} -->"
    return "<!-- dry-lint -->"


def banner_reachable(client_transport=None) -> bool:
    import httpx

    try:
        with httpx.Client(timeout=5, transport=client_transport, follow_redirects=True) as client:
            url = "https://raw.githubusercontent.com/gigaverse-app/dry-lint/main/docs/assets/sticky-banner-light.svg"
            return client.head(url).status_code == 200
    except httpx.HTTPError:
        return False
