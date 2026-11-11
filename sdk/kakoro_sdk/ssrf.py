"""SSRF (Server-Side Request Forgery) protection module.

Ported from the hardened Rust MCP server implementation.
Protects against requests to private, loopback, link-local, and cloud metadata addresses.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse
from typing import List, Optional


class SSRFSecurityError(ValueError):
    """Raised when a URL violates SSRF security policies."""
    pass


BLOCKED_IP_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),      # IPv4 loopback
    ipaddress.ip_network("10.0.0.0/8"),       # RFC1918 private
    ipaddress.ip_network("172.16.0.0/12"),    # RFC1918 private
    ipaddress.ip_network("192.168.0.0/16"),   # RFC1918 private
    ipaddress.ip_network("169.254.0.0/16"),   # IPv4 Link-local / AWS/GCP metadata
    ipaddress.ip_network("0.0.0.0/8"),        # Current network
    ipaddress.ip_network("::1/128"),          # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),         # IPv6 unique local
    ipaddress.ip_network("fe80::/10"),        # IPv6 link-local
]


def is_ip_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Checks whether an IP address falls within prohibited ranges."""
    for network in BLOCKED_IP_NETWORKS:
        if ip in network:
            return True
    return False


def validate_url(
    url: str,
    allow_http: bool = False,
    allowed_hosts: Optional[List[str]] = None,
    allow_loopback: bool = False,
) -> str:
    """
    Validates a URL against strict SSRF defense policies.
    
    Args:
        url: The candidate destination URL.
        allow_http: If True, allows http scheme (otherwise https only).
        allowed_hosts: Optional explicit host allowlist.
        allow_loopback: If True, allows 127.0.0.1 (used ONLY in local test suites).
    
    Returns:
        The validated URL.
        
    Raises:
        SSRFSecurityError: If the URL fails any security check.
    """
    if not url or not isinstance(url, str):
        raise SSRFSecurityError("Invalid or empty URL")

    try:
        parsed = urlparse(url)
    except Exception as e:
        raise SSRFSecurityError(f"Malformed URL: {e}")

    # 1. Scheme check
    valid_schemes = ("https", "http") if allow_http else ("https",)
    if parsed.scheme.lower() not in valid_schemes:
        raise SSRFSecurityError(f"Scheme '{parsed.scheme}' not allowed. Must be {valid_schemes}")

    hostname = parsed.hostname
    if not hostname:
        raise SSRFSecurityError("Missing hostname in URL")

    # 2. Host allowlist check (if specified)
    if allowed_hosts:
        if hostname.lower() not in [h.lower() for h in allowed_hosts]:
            raise SSRFSecurityError(f"Host '{hostname}' is not in the allowed hosts list")

    # 3. DNS resolution and IP address validation
    try:
        addr_infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as e:
        raise SSRFSecurityError(f"Failed to resolve hostname '{hostname}': {e}")

    for addr_info in addr_infos:
        ip_str = addr_info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            raise SSRFSecurityError(f"Invalid IP address resolved: {ip_str}")

        if allow_loopback and (ip.is_loopback or ip == ipaddress.ip_address("127.0.0.1")):
            continue

        if is_ip_blocked(ip):
            raise SSRFSecurityError(
                f"Hostname '{hostname}' resolves to prohibited IP address {ip_str} (SSRF blocked)"
            )

    return url
