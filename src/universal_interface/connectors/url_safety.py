"""Basic SSRF guards for user-supplied URLs."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse


def is_safe_https_url(url: str, *, allow_http: bool = False) -> bool:
    """Allow only http(s) URLs that are not obviously local/internal."""
    try:
        parsed = urlparse(url.strip())
    except Exception:
        return False

    scheme = (parsed.scheme or "").lower()
    if scheme == "https":
        pass
    elif scheme == "http" and allow_http:
        pass
    else:
        return False

    host = parsed.hostname
    if not host:
        return False

    h = host.lower()
    blocked_hosts = {
        "localhost",
        "127.0.0.1",
        "::1",
        "0.0.0.0",
        "metadata.google.internal",
        "metadata.google.internal.",
    }
    if h in blocked_hosts or h.endswith(".localhost") or h.endswith(".local"):
        return False

    try:
        ip = ipaddress.ip_address(h)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
        ):
            return False
    except ValueError:
        pass

    return True
