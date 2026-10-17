"""
Parallel TCP latency checker for proxy nodes.
"""

import time
import socket
import ssl
import random
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Optional, Any
from core.constants import PING_DEFAULT_TIMEOUT, PING_SAMPLE_MAX, URL_TEST_URL, URL_TEST_FALLBACK


def handshake_ping(host: str, port: int, sni: Optional[str] = None, timeout: float = PING_DEFAULT_TIMEOUT) -> Optional[float]:
    """
    Measures TCP + TLS handshake latency in milliseconds.
    If SNI is provided, performs full TLS ClientHello/ServerHello negotiation.
    Returns None if connection failed.
    """
    start = time.time()
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        if sni:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            with ctx.wrap_socket(s, server_hostname=sni):
                return (time.time() - start) * 1000.0
        s.close()
        return (time.time() - start) * 1000.0
    except Exception:
        return None


def tcp_ping(host: str, port: int, timeout: float = PING_DEFAULT_TIMEOUT) -> Optional[float]:
    """Measures TCP handshake latency in milliseconds. Returns None if connection failed."""
    return handshake_ping(host, port, sni=None, timeout=timeout)


def http_url_test(url: str = URL_TEST_URL, timeout: float = 2.5) -> Optional[float]:
    """
    Measures end-to-end HTTP 204 latency through current system connection (TUN / proxy).
    Returns real delay in milliseconds, or None if failed.
    """
    start = time.time()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.getcode() in (200, 204):
                return (time.time() - start) * 1000.0
    except Exception:
        pass

    # Fallback to secondary endpoint
    try:
        start_fb = time.time()
        req = urllib.request.Request(URL_TEST_FALLBACK, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.getcode() in (200, 204):
                return (time.time() - start_fb) * 1000.0
    except Exception:
        pass

    return None


def check_nodes_ping(nodes: List[Dict[str, Any]], max_workers: int = 25, timeout: float = 1.8) -> List[Dict[str, Any]]:
    """Runs parallel TLS/TCP handshake ping across candidate nodes and returns sorted responsive nodes."""
    alive_nodes = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(handshake_ping, n["server"], n["port"], n.get("sni") or n.get("host"), timeout): n
            for n in nodes
            if n.get("server") and n.get("port")
        }
        for future in as_completed(futures):
            node = futures[future]
            try:
                latency = future.result()
                if latency is not None:
                    node_copy = node.copy()
                    node_copy["ping"] = int(latency)
                    alive_nodes.append(node_copy)
            except Exception:
                pass

    # Sort ascending by latency (fastest first)
    alive_nodes.sort(key=lambda x: x["ping"])
    return alive_nodes


def select_best_nodes(
    nodes: List[Dict[str, Any]],
    target_count: int = 15,
    sample_size: int = PING_SAMPLE_MAX,
    log_func=None
) -> List[Dict[str, Any]]:
    """
    Selects top responsive nodes by sampling and TCP pinging.
    Preserves fallback order if ping fails.
    """
    if not nodes:
        return []

    sampled = random.sample(nodes, min(len(nodes), sample_size))
    if log_func:
        log_func(f"Pinging {len(sampled)} sampled nodes for top {target_count} selection...")

    try:
        alive = check_nodes_ping(sampled)
        if log_func:
            log_func(f"Ping finished: {len(alive)} nodes responsive out of {len(sampled)}.")

        if alive:
            selected = alive[:target_count]
            # If we got fewer alive than requested, backfill with remaining nodes
            if len(selected) < target_count:
                seen_endpoints = {(n["server"], n["port"]) for n in selected}
                for n in nodes:
                    endpoint = (n.get("server"), n.get("port"))
                    if endpoint not in seen_endpoints:
                        selected.append(n)
                        seen_endpoints.add(endpoint)
                        if len(selected) >= target_count:
                            break
            return selected
    except Exception as e:
        if log_func:
            log_func(f"Ping selection encountered error: {e}")

    # Fallback to head of original list
    return nodes[:target_count]
