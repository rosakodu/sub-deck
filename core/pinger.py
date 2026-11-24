"""
Parallel TCP latency checker for proxy nodes.
"""

import time
import socket
import ssl
import random
import subprocess
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Optional, Any
from core.constants import PING_DEFAULT_TIMEOUT, PING_SAMPLE_MAX, URL_TEST_URL, URL_TEST_FALLBACK


def _is_ip(addr: str) -> bool:
    try:
        import ipaddress
        ipaddress.ip_address(addr)
        return True
    except (ValueError, Exception):
        return False


def extract_node_sni(node: Dict[str, Any]) -> Optional[str]:
    """Extracts valid SNI domain for TLS handshake ping, matching Throne behavior."""
    sni = node.get("sni") or node.get("host")
    if not sni:
        sec = str(node.get("security", "")).lower()
        ntype = str(node.get("type", "")).lower()
        if sec in ("tls", "reality") or ntype in ("trojan", "vless"):
            server = node.get("server", "")
            if server and not _is_ip(server):
                sni = server
    return sni


def handshake_ping(
    host: str,
    port: int,
    sni: Optional[str] = None,
    timeout: float = PING_DEFAULT_TIMEOUT,
    is_udp: bool = False
) -> Optional[float]:
    """
    Measures TCP + TLS handshake latency in milliseconds (Throne method).
    If SNI is provided, performs full TLS ClientHello/ServerHello negotiation.
    Returns None if connection failed.
    """
    if is_udp:
        # Fallback to ICMP ping for UDP protocols (e.g. WireGuard / AWG)
        try:
            p_start = time.time()
            res = subprocess.run(
                ["ping", "-c", "1", "-W", str(int(timeout) or 1), host],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=timeout,
            )
            if res.returncode == 0:
                return (time.time() - p_start) * 1000.0
        except Exception:
            pass
        return None

    # TCP / TLS handshake test (matching Throne's Tcping / TLS ping)
    start = time.time()
    s = None
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        if sni:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            with ctx.wrap_socket(s, server_hostname=sni):
                return (time.time() - start) * 1000.0
        return (time.time() - start) * 1000.0
    except Exception:
        # TCP connection refused, timeout, or TLS handshake failure -> Unavailable
        return None
    finally:
        if s is not None:
            try:
                s.close()
            except Exception:
                pass


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
        futures = {}
        for n in nodes:
            if n.get("server") and n.get("port"):
                host = n["server"]
                port = n["port"]
                ntype = n.get("type", "")
                sni = extract_node_sni(n)
                is_udp = ntype in ("awg", "wireguard")
                if is_udp:
                    fut = executor.submit(handshake_ping, host, port, sni=sni, timeout=timeout, is_udp=True)
                else:
                    fut = executor.submit(handshake_ping, host, port, sni=sni, timeout=timeout)
                futures[fut] = n
        for future in as_completed(futures):
            node = futures[future]
            try:
                latency = future.result()
                if latency is not None and latency > 0:
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
    target_count: Optional[int] = None,
    sample_size: int = PING_SAMPLE_MAX,
    log_func=None
) -> List[Dict[str, Any]]:
    """
    Selects top responsive nodes by sampling and TCP pinging.
    Preserves fallback order if ping fails.
    If target_count is None or <= 0, no limit is applied and all nodes are returned.
    """
    if not nodes:
        return []

    has_limit = target_count is not None and target_count > 0

    sampled = random.sample(nodes, min(len(nodes), sample_size))
    if log_func:
        if has_limit:
            log_func(f"Pinging {len(sampled)} sampled nodes for top {target_count} selection...")
        else:
            log_func(f"Pinging {len(sampled)} sampled nodes without limit...")

    try:
        alive = check_nodes_ping(sampled)
        if log_func:
            log_func(f"Ping finished: {len(alive)} nodes responsive out of {len(sampled)}.")

        if alive:
            # Map alive nodes back to their indices in nodes
            used_indices = set()
            alive_matched = []
            for a in alive:
                for idx, orig in enumerate(nodes):
                    if idx in used_indices:
                        continue
                    if (a.get("name") and a.get("name") == orig.get("name")) or (
                        a.get("server") == orig.get("server") and a.get("port") == orig.get("port")
                    ):
                        used_indices.add(idx)
                        alive_matched.append(a)
                        break

            remaining = [orig for idx, orig in enumerate(nodes) if idx not in used_indices]

            if has_limit:
                selected = alive_matched[:target_count]
                if len(selected) < target_count:
                    selected.extend(remaining[:target_count - len(selected)])
                return selected
            else:
                return alive_matched + remaining
    except Exception as e:
        if log_func:
            log_func(f"Ping selection encountered error: {e}")

    # Fallback to original list
    if has_limit:
        return nodes[:target_count]
    return list(nodes)


def ping_all_nodes(nodes: List[Dict[str, Any]], max_workers: int = 30, timeout: float = 2.0) -> List[Dict[str, Any]]:
    """
    Runs parallel TLS/TCP handshake ping across all nodes (matching Throne method)
    and returns the full list with updated 'ping' (latency in ms, or -1 if unreachable).
    """
    if not nodes:
        return []

    node_copies = [n.copy() for n in nodes]
    futures_map = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for idx, n in enumerate(node_copies):
            host = n.get("server")
            port = n.get("port")
            ntype = n.get("type", "")
            if host and port and ntype != "auto_balancer":
                sni = extract_node_sni(n)
                is_udp = ntype in ("awg", "wireguard")
                if is_udp:
                    fut = executor.submit(handshake_ping, host, port, sni=sni, timeout=timeout, is_udp=True)
                else:
                    fut = executor.submit(handshake_ping, host, port, sni=sni, timeout=timeout)
                futures_map[fut] = idx
            elif ntype == "auto_balancer":
                node_copies[idx]["ping"] = 1

        for fut in as_completed(futures_map):
            idx = futures_map[fut]
            try:
                lat = fut.result()
                if lat is not None and lat > 0:
                    node_copies[idx]["ping"] = int(lat)
                else:
                    node_copies[idx]["ping"] = -1
            except Exception:
                node_copies[idx]["ping"] = -1

    return node_copies


def find_best_node(
    nodes: List[Dict[str, Any]],
    timeout: float = 1.2,
    max_workers: int = 50,
    log_func=None
) -> Optional[Dict[str, Any]]:
    """
    Finds the single best responsive node with the lowest latency among available working nodes.
    First runs a fast parallel handshake ping across candidate nodes.
    If responsive nodes are found, returns the one with lowest ping.
    If none respond to ping, falls back to existing cached ping > 0.
    If none, returns the first available node.
    """
    candidate_nodes = [n for n in nodes if n.get("type") != "auto_balancer"]
    if not candidate_nodes:
        return None

    # Filter candidates with host and port
    pingable = [n for n in candidate_nodes if n.get("server") and n.get("port")]

    # Prioritize nodes with valid positive cached pings first
    pingable.sort(key=lambda x: (0 if isinstance(x.get("ping"), (int, float)) and x.get("ping") > 0 else 1, x.get("ping") or 9999))

    effective_workers = min(len(pingable), max_workers) if pingable else max_workers
    if log_func:
        log_func(f"find_best_node: testing latency for {len(pingable)} candidate nodes (timeout={timeout}s, workers={effective_workers})...")

    alive = []
    if pingable:
        alive = check_nodes_ping(pingable, max_workers=effective_workers, timeout=timeout)

    if alive:
        best = alive[0]
        if log_func:
            log_func(f"find_best_node: best responsive node is '{best.get('name')}' with ping {best.get('ping')}ms")
        return best

    # Fallback to existing cached pings
    cached_alive = [
        n for n in candidate_nodes
        if isinstance(n.get("ping"), (int, float)) and n.get("ping") > 0
    ]
    if cached_alive:
        cached_alive.sort(key=lambda x: x["ping"])
        best = cached_alive[0]
        if log_func:
            log_func(f"find_best_node: fallback to cached ping: '{best.get('name')}' ({best.get('ping')}ms)")
        return best

    # Fallback to first candidate node
    best = candidate_nodes[0]
    if log_func:
        log_func(f"find_best_node: no ping response, selected first candidate '{best.get('name')}'")
    return best

