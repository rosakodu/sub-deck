"""Linux route and DNS setup for the tunnel interface."""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Union

from core.constants import DNS_SERVERS, TUN_INTERFACE, TUN_IP_CIDR, TUN_MTU, TUN_ROUTE_PROTOCOL
from core.system import is_interface_present, run_command


@dataclass
class _ActiveRoutes:
    gateway: Optional[str]
    interface: Optional[str]
    server_ips: List[str] = field(default_factory=list)
    cleanup_tun: bool = True

    def snapshot(self) -> Dict[str, Any]:
        state = {
            "tun_interface": TUN_INTERFACE,
            "server_ip": self.server_ips.copy(),
            "gw_ip": self.gateway,
            "iface": self.interface,
        }
        if not self.cleanup_tun:
            state["cleanup_tun"] = False
        return state


def _command_error(command: List[str]) -> Optional[str]:
    result = run_command(command)
    if result is not None and result.returncode == 0:
        return None
    if result is None:
        detail = "command failed to execute or timed out"
    else:
        detail = (result.stderr or "").strip() or f"exit status {result.returncode}"
    return f"{' '.join(command)}: {detail}"


def _require_command(command: List[str]) -> None:
    error = _command_error(command)
    if error is not None:
        raise RuntimeError(error)


class TunnelRouting:
    """Owns Linux network changes for one tunnel, including partial setup."""

    def __init__(self, log: Callable[[str], None]) -> None:
        self._log = log
        self._active: Optional[_ActiveRoutes] = None

    def configure(
        self,
        gw_ip: str,
        iface: str,
        server_ips: Iterable[str],
        node_dns: Optional[Union[str, Iterable[str]]],
    ) -> Dict[str, Any]:
        active = _ActiveRoutes(gw_ip, iface)
        self._active = active
        _require_command(["ip", "addr", "add", TUN_IP_CIDR, "dev", TUN_INTERFACE])
        _require_command(["ip", "link", "set", "dev", TUN_INTERFACE, "mtu", TUN_MTU, "up"])

        # Keep proxy traffic on the physical network. Never replace an existing host route.
        for sip in dict.fromkeys(server_ips):
            _require_command(["ip", "route", "add", sip, "via", gw_ip, "dev", iface,
                                   "proto", TUN_ROUTE_PROTOCOL])
            active.server_ips.append(sip)

        _require_command(["ip", "route", "add", "default", "dev", TUN_INTERFACE,
                               "metric", "1", "proto", TUN_ROUTE_PROTOCOL])

        if node_dns:
            if isinstance(node_dns, str):
                dns_list = [d.strip() for d in node_dns.split(",") if d.strip()]
            else:
                dns_list = [str(d).strip() for d in node_dns if str(d).strip()]
        else:
            dns_list = DNS_SERVERS

        _require_command(["resolvectl", "dns", TUN_INTERFACE] + dns_list)
        _require_command(["resolvectl", "domain", TUN_INTERFACE, "~."])
        _require_command(["resolvectl", "default-route", TUN_INTERFACE, "yes"])

        return active.snapshot()

    def clear(self, saved_state: Dict[str, Any]) -> Dict[str, Any]:
        """Remove owned routes and return any state still needed for cleanup."""
        state = self._active.snapshot() if self._active is not None else saved_state
        if state.get("tun_interface") != TUN_INTERFACE:
            return {}

        cleanup_tun = False
        if state.get("cleanup_tun", True):
            errors = [
                _command_error(["resolvectl", "revert", TUN_INTERFACE]),
                _command_error(["ip", "route", "del", "default", "dev", TUN_INTERFACE, "metric", "1",
                                "proto", TUN_ROUTE_PROTOCOL]),
                _command_error(["ip", "link", "delete", TUN_INTERFACE]),
            ]
            # The kernel and resolved drop routes and per-link DNS when the interface vanishes.
            cleanup_tun = errors[-1] is not None and is_interface_present(TUN_INTERFACE)
            if cleanup_tun:
                for error in errors:
                    if error is not None:
                        self._log(f"VPN cleanup failed: {error}")

        server_ips = state.get("server_ip")
        gw_ip = state.get("gw_ip")
        iface = state.get("iface")
        if isinstance(server_ips, str):
            server_ips = [server_ips]
        remaining_ips = []
        if gw_ip and iface:
            for sip in server_ips or []:
                route = [sip, "via", gw_ip, "dev", iface, "proto", TUN_ROUTE_PROTOCOL]
                error = _command_error(["ip", "route", "del", *route])
                if error is None:
                    continue
                probe = run_command(["ip", "route", "show", "exact", *route])
                if probe is not None and probe.returncode == 0 and not (probe.stdout or "").strip():
                    continue
                self._log(f"VPN cleanup failed: {error}")
                remaining_ips.append(sip)

        self._active = None
        if cleanup_tun or remaining_ips:
            self._active = _ActiveRoutes(gw_ip, iface, remaining_ips, cleanup_tun=cleanup_tun)
            return self._active.snapshot()
        return {}
