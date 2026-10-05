"""
Parallel TCP latency checker for proxy nodes.
"""

import time
import socket
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Optional, Any
from core.constants import PING_DEFAULT_TIMEOUT, PING_SAMPLE_MAX


def tcp_ping(host: str, port: int, timeout: float = PING_DEFAULT_TIMEOUT) -> Optional[float]:
    """Measures TCP handshake latency in milliseconds. Returns None if connection failed."""
    start = time.time()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return (time.time() - start) * 1000.0
    except Exception:
        return None


def check_nodes_ping(nodes: List[Dict[str, Any]], max_workers: int = 25, timeout: float = PING_DEFAULT_TIMEOUT) -> List[Dict[str, Any]]:
    """Runs parallel TCP ping across candidate nodes and returns sorted responsive nodes."""
    alive_nodes = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(tcp_ping, n["server"], n["port"], timeout): n
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
