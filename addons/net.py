from ipaddress import ip_address
from urllib.parse import urlparse


def safe_public_url(url: str) -> str:
    """Validate that url is a complete, public http(s) URL. Raises ValueError
    with a user-facing message otherwise. Shared by any add-on that reaches
    out to the web, so local/private addresses are never reachable through
    them."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Use a complete public http or https URL.")
    if parsed.hostname.lower() in {"localhost", "localhost.localdomain"}:
        raise ValueError("Local network addresses are not available through this add-on.")
    try:
        if ip_address(parsed.hostname).is_private or ip_address(parsed.hostname).is_loopback:
            raise ValueError("Private network addresses are not available through this add-on.")
    except ValueError as error:
        if "not available" in str(error):
            raise
    return url
