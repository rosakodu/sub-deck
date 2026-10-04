import os
import sys
import json
import urllib.request
import urllib.parse
import base64
import subprocess
import shutil
import time
import socket
import ipaddress
from concurrent.futures import ThreadPoolExecutor


def tcp_ping(host, port, timeout=1.0):
    """Возвращает время установки TCP-соединения в миллисекундах или None, если соединение провалилось."""
    start = time.time()
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        return (time.time() - start) * 1000
    except Exception:
        return None


def check_nodes_ping(nodes, max_workers=30):
    """Выполняет параллельный TCP-пинг для списка нод и возвращает отсортированный по пингу список."""
    alive_nodes = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(tcp_ping, n["server"], n["port"]): n
            for n in nodes
        }
        for future in futures:
            node = futures[future]
            latency = future.result()
            if latency is not None:
                node_copy = node.copy()
                node_copy["ping"] = int(latency)
                alive_nodes.append(node_copy)
    # Сортируем по возрастанию пинга (от быстрых к медленным)
    alive_nodes.sort(key=lambda x: x["ping"])
    return alive_nodes


class VPNManager:
    def __init__(self, plugin_dir, settings_dir, logger=None):
        self.plugin_dir = plugin_dir
        self.settings_dir = settings_dir
        self.bin_dir = os.path.join(self.settings_dir, "bin")
        self.xray_path = os.path.join(self.bin_dir, "xray")
        self.tun2socks_path = os.path.join(self.bin_dir, "tun2socks")
        self.singbox_path = self.xray_path  # Алиас для обратной совместимости
        self.config_path = os.path.join(self.settings_dir, "xray-config.json")
        self.nodes_cache_path = os.path.join(self.settings_dir, "nodes.json")
        self.settings_file = os.path.join(self.settings_dir, "settings.json")
        self.xray_process = None
        self.tun_process = None
        self.process = None  # Алиас
        self._logger = logger
        self._last_server_ip = None
        self._last_gw_ip = None
        self._last_iface = None

        os.makedirs(self.bin_dir, exist_ok=True)
        os.makedirs(self.settings_dir, exist_ok=True)

    def log(self, msg):
        """Логирование через decky.logger если доступен, иначе print."""
        if self._logger:
            self._logger.info(msg)
        else:
            print(msg)

    # ────────────────────────────────────────────────
    # Настройки
    # ────────────────────────────────────────────────

    def load_settings(self):
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, "r") as f:
                    settings = json.load(f)
                    # Миграция старых настроек
                    if "subscription_url" in settings and "subscriptions" not in settings:
                        old_url = settings.get("subscription_url", "")
                        settings["subscriptions"] = [old_url] if old_url else []
                    return settings
            except Exception:
                pass
        return {"subscriptions": [], "selected_node": None}

    def parse_all_subscriptions(self):
        """Парсит все подписки из списка и объединяет их ноды."""
        settings = self.load_settings()
        urls = settings.get("subscriptions", [])
        all_nodes = []
        
        update_intervals = settings.setdefault("update_intervals", {})
        last_update_times = settings.setdefault("last_update_times", {})
        
        self.log(f"Starting parsing of all subscriptions: {len(urls)} links")
        for url in urls:
            try:
                nodes, interval = self.parse_subscription(url)
                all_nodes.extend(nodes)
                last_update_times[url] = int(time.time())
                if interval is not None:
                    update_intervals[url] = int(interval)
            except Exception as e:
                self.log(f"Failed to parse subscription {url}: {e}")
                
        settings["update_intervals"] = update_intervals
        settings["last_update_times"] = last_update_times
        self.save_settings(settings)

        try:
            with open(self.nodes_cache_path, "w") as f:
                json.dump(all_nodes, f)
            self.log(f"Saved total of {len(all_nodes)} nodes to cache.")
        except Exception as e:
            self.log(f"Failed to save nodes cache: {e}")
            
        return all_nodes

    def add_subscription(self, url):
        settings = self.load_settings()
        subscriptions = settings.get("subscriptions", [])
        if url not in subscriptions:
            subscriptions.append(url)
            settings["subscriptions"] = subscriptions
            self.save_settings(settings)
            self.log(f"Added subscription URL: {url}")
        return self.parse_all_subscriptions()

    def add_multiple_subscriptions(self, urls):
        settings = self.load_settings()
        subscriptions = settings.get("subscriptions", [])
        updated = False
        for url in urls:
            if url not in subscriptions:
                subscriptions.append(url)
                updated = True
        if updated:
            settings["subscriptions"] = subscriptions
            self.save_settings(settings)
            self.log(f"Added multiple subscription URLs: {urls}")
        return self.parse_all_subscriptions()

    def remove_subscription(self, url):
        settings = self.load_settings()
        subscriptions = settings.get("subscriptions", [])
        if url in subscriptions:
            subscriptions.remove(url)
            settings["subscriptions"] = subscriptions
            self.save_settings(settings)
            self.log(f"Removed subscription URL: {url}")
        return self.parse_all_subscriptions()

    def update_subscription(self, url):
        self.log(f"Updating single subscription: {url}")
        new_nodes, interval = self.parse_subscription(url)
        
        # Загружаем текущие ноды
        all_nodes = self.load_nodes()
        
        # Фильтруем старые ноды для этого URL
        all_nodes = [n for n in all_nodes if n.get("subscription_url") != url]
        
        # Добавляем новые
        all_nodes.extend(new_nodes)
        self.save_nodes(all_nodes)
        
        # Обновляем метаданные в settings
        settings = self.load_settings()
        last_updates = settings.get("last_update_times", {})
        update_intervals = settings.get("update_intervals", {})
        
        last_updates[url] = int(time.time())
        if interval is not None:
             update_intervals[url] = interval
             
        settings["last_update_times"] = last_updates
        settings["update_intervals"] = update_intervals
        self.save_settings(settings)
        
        return all_nodes


    def save_settings(self, settings):
        try:
            with open(self.settings_file, "w") as f:
                json.dump(settings, f)
        except Exception:
            pass

    def update_geofiles(self, force=False):
        """Скачивает базы geosite.db и geoip.db для пресета RoscomVPN в фоне."""
        settings = self.load_settings()
        if settings.get("selected_preset") != "roscomvpn":
            return False

        geoip_path = os.path.join(self.settings_dir, "geoip.db")
        geosite_path = os.path.join(self.settings_dir, "geosite.db")

        now = time.time()
        
        need_geoip = force
        if not need_geoip:
            if not os.path.exists(geoip_path) or os.path.getsize(geoip_path) < 1000000:
                need_geoip = True
            elif now - os.path.getmtime(geoip_path) >= 6 * 3600:
                need_geoip = True

        need_geosite = force
        if not need_geosite:
            if not os.path.exists(geosite_path) or os.path.getsize(geosite_path) < 1000000:
                need_geosite = True
            elif now - os.path.getmtime(geosite_path) >= 6 * 3600:
                need_geosite = True

        updated = False
        import shutil

        # Сначала пробуем скопировать из defaults, если файлы в settings отсутствуют или битые
        default_geoip_path = os.path.join(self.plugin_dir, "defaults", "geoip.db")
        default_geosite_path = os.path.join(self.plugin_dir, "defaults", "geosite.db")

        if need_geoip and os.path.exists(default_geoip_path) and os.path.getsize(default_geoip_path) >= 1000000:
            self.log("Copying geoip.db from plugin defaults...")
            try:
                shutil.copy2(default_geoip_path, geoip_path)
                self.log("geoip.db copied successfully from defaults.")
                need_geoip = False
                updated = True
            except Exception as e:
                self.log(f"Failed to copy geoip.db from defaults: {e}")

        if need_geosite and os.path.exists(default_geosite_path) and os.path.getsize(default_geosite_path) >= 1000000:
            self.log("Copying geosite.db from plugin defaults...")
            try:
                shutil.copy2(default_geosite_path, geosite_path)
                self.log("geosite.db copied successfully from defaults.")
                need_geosite = False
                updated = True
            except Exception as e:
                self.log(f"Failed to copy geosite.db from defaults: {e}")

        import ssl
        ctx = ssl._create_unverified_context()

        if need_geoip:
            self.log("Downloading geoip.db from SagerNet...")
            try:
                req = urllib.request.Request(
                    "https://github.com/SagerNet/sing-geoip/releases/latest/download/geoip.db",
                    headers={"User-Agent": "Mozilla/5.0"}
                )
                with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
                    data = resp.read()
                    if len(data) < 1000000:
                        raise ValueError(f"Downloaded file is too small: {len(data)} bytes")
                    with open(geoip_path, "wb") as f:
                        f.write(data)
                self.log("geoip.db downloaded successfully.")
                updated = True
            except Exception as e:
                self.log(f"Failed to download geoip.db: {e}")
                if os.path.exists(geoip_path):
                    try:
                        os.remove(geoip_path)
                    except Exception:
                        pass

        if need_geosite:
            self.log("Downloading geosite.db from SagerNet...")
            try:
                req = urllib.request.Request(
                    "https://github.com/SagerNet/sing-geosite/releases/latest/download/geosite.db",
                    headers={"User-Agent": "Mozilla/5.0"}
                )
                with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
                    data = resp.read()
                    if len(data) < 1000000:
                        raise ValueError(f"Downloaded file is too small: {len(data)} bytes")
                    with open(geosite_path, "wb") as f:
                        f.write(data)
                self.log("geosite.db downloaded successfully.")
                updated = True
            except Exception as e:
                self.log(f"Failed to download geosite.db: {e}")
                if os.path.exists(geosite_path):
                    try:
                        os.remove(geosite_path)
                    except Exception:
                        pass

        return updated

    def get_nodes(self):
        if os.path.exists(self.nodes_cache_path):
            try:
                with open(self.nodes_cache_path, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    def load_nodes(self):
        return self.get_nodes()

    def save_nodes(self, nodes):
        try:
            with open(self.nodes_cache_path, "w") as f:
                json.dump(nodes, f)
            self.log(f"Saved total of {len(nodes)} nodes to cache.")
        except Exception as e:
            self.log(f"Failed to save nodes to cache: {e}")


    # ────────────────────────────────────────────────
    # Системные утилиты и проверка бинарников (Xray + tun2socks)
    # ────────────────────────────────────────────────

    def _run_cmd(self, cmd_list):
        """Запускает системную команду, добавляя sudo если процесс не под root."""
        cmd = list(cmd_list)
        if os.geteuid() != 0:
            cmd = ["sudo", "-n"] + cmd
        try:
            return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        except Exception as e:
            self.log(f"Error running {' '.join(cmd)}: {e}")
            return None

    def _get_default_gateway(self):
        """Определяет шлюз по умолчанию и физический сетевой интерфейс."""
        try:
            res = subprocess.run(["ip", "route", "show", "default"], stdout=subprocess.PIPE, text=True)
            for line in res.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 5 and parts[0] == "default" and parts[1] == "via":
                    gw = parts[2]
                    iface = parts[4]
                    return gw, iface
        except Exception as e:
            self.log(f"Error getting default gateway: {e}")
        return None, None

    def _resolve_host(self, host):
        """Разрешает домен в IP, чтобы исключить DNS-петлю при маршрутизации."""
        if not host:
            return None
        try:
            ipaddress.ip_address(host)
            return host
        except ValueError:
            pass
        try:
            return socket.gethostbyname(host)
        except Exception as e:
            self.log(f"Failed to resolve {host}: {e}")
            return host

    def _check_socket_open(self, host, port, timeout=1.5):
        """Проверяет доступность TCP-сокета."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        try:
            s.connect((host, port))
            s.close()
            return True
        except Exception:
            return False

    def ensure_binaries(self):
        """Проверяет наличие Xray и tun2socks. При отсутствии копирует из defaults или скачивает."""
        need_xray = not (os.path.exists(self.xray_path) and os.access(self.xray_path, os.X_OK))
        need_tun = not (os.path.exists(self.tun2socks_path) and os.access(self.tun2socks_path, os.X_OK))

        if not need_xray and not need_tun:
            return True

        # Сначала проверяем defaults/bin
        defaults_xray = os.path.join(self.plugin_dir, "defaults", "bin", "xray")
        defaults_tun = os.path.join(self.plugin_dir, "defaults", "bin", "tun2socks")

        if need_xray and os.path.exists(defaults_xray) and os.access(defaults_xray, os.X_OK):
            self.log("Copying xray from plugin defaults...")
            try:
                shutil.copy2(defaults_xray, self.xray_path)
                os.chmod(self.xray_path, 0o755)
                need_xray = False
            except Exception as e:
                self.log(f"Failed to copy xray from defaults: {e}")

        if need_tun and os.path.exists(defaults_tun) and os.access(defaults_tun, os.X_OK):
            self.log("Copying tun2socks from plugin defaults...")
            try:
                shutil.copy2(defaults_tun, self.tun2socks_path)
                os.chmod(self.tun2socks_path, 0o755)
                self._run_cmd(["setcap", "cap_net_admin,cap_net_raw+ep", self.tun2socks_path])
                need_tun = False
            except Exception as e:
                self.log(f"Failed to copy tun2socks from defaults: {e}")

        # Скопируем базы гео-файлов, если есть в defaults
        for dat in ["geoip.dat", "geosite.dat"]:
            dat_target = os.path.join(self.bin_dir, dat)
            dat_default = os.path.join(self.plugin_dir, "defaults", dat)
            if not os.path.exists(dat_target) and os.path.exists(dat_default):
                try:
                    shutil.copy2(dat_default, dat_target)
                except Exception:
                    pass

        if not need_xray and not need_tun:
            return True

        import ssl, zipfile
        ctx = ssl._create_unverified_context()

        # 1. Скачивание Xray
        if need_xray:
            xray_zip_url = "https://github.com/XTLS/Xray-core/releases/download/v26.9.30/Xray-linux-64.zip"
            zip_path = os.path.join(self.bin_dir, "xray.zip")
            self.log("Downloading Xray-core v26.9.30...")
            try:
                req = urllib.request.Request(xray_zip_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=90, context=ctx) as resp:
                    with open(zip_path, "wb") as f:
                        f.write(resp.read())
                with zipfile.ZipFile(zip_path, "r") as z:
                    z.extract("xray", path=self.bin_dir)
                    for dat in ["geoip.dat", "geosite.dat"]:
                        if dat in z.namelist():
                            z.extract(dat, path=self.bin_dir)
                if os.path.exists(zip_path):
                    os.remove(zip_path)
                os.chmod(self.xray_path, 0o755)
                self.log("Xray-core downloaded and installed OK")
            except Exception as e:
                self.log(f"Failed to download Xray: {e}")
                if os.path.exists(zip_path):
                    try:
                        os.remove(zip_path)
                    except Exception:
                        pass
                return False

        # 2. Скачивание tun2socks
        if need_tun:
            tun_zip_url = "https://github.com/xjasonlyu/tun2socks/releases/download/v2.7.0/tun2socks-linux-amd64.zip"
            zip_path = os.path.join(self.bin_dir, "tun2socks.zip")
            self.log("Downloading tun2socks v2.7.0...")
            try:
                req = urllib.request.Request(tun_zip_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
                    with open(zip_path, "wb") as f:
                        f.write(resp.read())
                with zipfile.ZipFile(zip_path, "r") as z:
                    for name in z.namelist():
                        if "tun2socks" in name and not name.endswith(".zip"):
                            with open(self.tun2socks_path, "wb") as f_out:
                                f_out.write(z.read(name))
                            break
                if os.path.exists(zip_path):
                    os.remove(zip_path)
                os.chmod(self.tun2socks_path, 0o755)
                self._run_cmd(["setcap", "cap_net_admin,cap_net_raw+ep", self.tun2socks_path])
                self.log("tun2socks downloaded and installed OK")
            except Exception as e:
                self.log(f"Failed to download tun2socks: {e}")
                if os.path.exists(zip_path):
                    try:
                        os.remove(zip_path)
                    except Exception:
                        pass
                return False

        return True

    def download_singbox(self):
        """Алиас для обратной совместимости."""
        return self.ensure_binaries()

    # ────────────────────────────────────────────────
    # Парсинг подписки
    # ────────────────────────────────────────────────

    def _do_http_get(self, url, user_agent):
        """Выполняет HTTP GET запрос, возвращает (bytes, headers)."""
        import ssl
        ctx = ssl._create_unverified_context()
        req = urllib.request.Request(url, headers={"User-Agent": user_agent})
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            return resp.read(), resp.info()

    def fetch_raw(self, url):
        """Скачивает подписку и возвращает сырой текст для диагностики."""
        user_agents = ["v2rayN/6.0", "clash/1.18.0",
                       "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"]
        for ua in user_agents:
            try:
                data, _ = self._do_http_get(url, ua)
                text = data.decode("utf-8", errors="replace").strip()
                return f"UA={ua} | len={len(text)} | content={repr(text[:500])}"
            except Exception as e:
                last = str(e)
        return f"ALL FAILED: {last}"

    def parse_subscription(self, url):
        """Скачивает подписку по URL и парсит ноды VLESS, отбирая топ-15 лучших по пингу."""
        import traceback

        user_agents = [
            "v2rayN/6.0",
            "clash/1.18.0",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        ]

        content = None
        headers = None
        last_error = None

        for ua in user_agents:
            try:
                content, headers = self._do_http_get(url, ua)
                self.log(f"Downloaded {len(content)} bytes with UA={ua}")
                break
            except Exception as e:
                last_error = e
                continue

        if content is None:
            self.log(f"parse_subscription FAILED: {last_error}")
            self.log(traceback.format_exc())
            return [], None

        # Читаем интервал обновления из заголовков
        update_interval = None
        if headers:
            for h_key, h_val in headers.items():
                if h_key.lower() == "profile-update-interval":
                    try:
                        update_interval = int(h_val)
                        self.log(f"Found profile-update-interval header: {update_interval} hours")
                    except Exception:
                        pass

        try:
            text = content.decode("utf-8").strip()
        except Exception:
            text = content.decode("latin-1").strip()

        # Если интервал не найден в заголовках, ищем его в тексте
        if update_interval is None:
            import re
            match = re.search(r'(?:#|//)?\s*profile-update-interval\s*:\s*(\d+)', text[:1000], re.IGNORECASE)
            if match:
                try:
                    update_interval = int(match.group(1))
                    self.log(f"Found profile-update-interval in file content: {update_interval} hours")
                except Exception:
                    pass

        # Определяем формат: plain text или base64
        supported_schemes = ("vless://", "vmess://", "trojan://", "ss://", "hysteria2://", "hy2://")
        is_plain = any(text.startswith(sch) or f"\n{sch}" in text for sch in supported_schemes)

        lines = []
        if is_plain:
            lines = text.splitlines()
            self.log(f"Plain-text format, {len(lines)} lines")
        else:
            try:
                clean_b64 = "".join(text.split())
                padded = clean_b64 + "=" * (-len(clean_b64) % 4)
                decoded = base64.b64decode(padded).decode("utf-8")
                lines = decoded.splitlines()
                self.log(f"Base64 decoded, {len(lines)} lines")
            except Exception as e:
                self.log(f"Base64 decode failed ({e}), using plain text")
                lines = text.splitlines()

        nodes = []
        proto_count = {}
        for line in lines:
            line = line.strip()
            if "://" in line:
                proto = line.split("://")[0]
                proto_count[proto] = proto_count.get(proto, 0) + 1
            
            parsed_node = None
            try:
                if line.startswith("vless://"):
                    parsed_node = self._parse_vless_link(line)
                elif line.startswith("vmess://"):
                    parsed_node = self._parse_vmess_link(line)
                elif line.startswith("trojan://"):
                    parsed_node = self._parse_trojan_link(line)
                elif line.startswith("ss://"):
                    parsed_node = self._parse_ss_link(line)
                elif line.startswith("hysteria2://") or line.startswith("hy2://"):
                    parsed_node = self._parse_hysteria2_link(line)
                
                if parsed_node:
                    parsed_node["subscription_url"] = url
                    nodes.append(parsed_node)
            except Exception as e:
                self.log(f"Failed to parse line: {repr(line[:60])}: {e}")

        # Дедупликация нод по имени и адресу (server:port)
        seen_names = set()
        seen_endpoints = set()
        unique_nodes = []
        for n in nodes:
            name = n.get("name")
            endpoint = (n.get("server"), n.get("port"))
            if name and endpoint[0] and endpoint[1]:
                if name not in seen_names and endpoint not in seen_endpoints:
                    seen_names.add(name)
                    seen_endpoints.add(endpoint)
                    unique_nodes.append(n)
        nodes = unique_nodes

        self.log(f"Protocols found: {proto_count}")
        self.log(f"Parsed {len(nodes)} total unique nodes")

        # Интеллектуальный отбор топ лучших нод по пингу (5 для Free Subscriptions, 15 для обычных)
        is_free_sub = (
            "igareck/vpn-configs-for-russia" in url or
            "AvenCores/goida-vpn-configs" in url or
            "zieng2/wl" in url
        )
        limit_nodes = 5 if is_free_sub else 15
        if nodes:
            try:
                sample_size = min(len(nodes), 50)
                import random
                sampled_nodes = random.sample(nodes, sample_size)
                self.log(f"Running parallel TCP ping for {sample_size} nodes...")
                
                alive_nodes = check_nodes_ping(sampled_nodes)
                self.log(f"Ping finished. Found {len(alive_nodes)} responsive nodes out of {sample_size}.")
                
                if alive_nodes:
                    selected = alive_nodes[:limit_nodes]
                    if len(selected) < limit_nodes:
                        seen_endpoints = {(n["server"], n["port"]) for n in selected}
                        for n in nodes:
                            endpoint = (n["server"], n["port"])
                            if endpoint not in seen_endpoints:
                                selected.append(n)
                                seen_endpoints.add(endpoint)
                                if len(selected) >= limit_nodes:
                                    break
                    nodes = selected
                else:
                    nodes = nodes[:limit_nodes]
            except Exception as e:
                self.log(f"Error during ping selection: {e}")
                nodes = nodes[:limit_nodes]
        else:
            nodes = []

        return nodes, update_interval

    def _parse_endpoint(self, endpoint):
        """Парсит host:port, поддерживает IPv6 [::1]:port."""
        if endpoint.startswith("["):
            bracket_end = endpoint.find("]")
            if bracket_end == -1:
                return endpoint, 443
            host = endpoint[1:bracket_end]
            rest = endpoint[bracket_end + 1:]
            port = int(rest.lstrip(":")) if ":" in rest else 443
        elif ":" in endpoint:
            host, port_str = endpoint.rsplit(":", 1)
            try:
                port = int(port_str)
            except ValueError:
                port = 443
        else:
            host = endpoint
            port = 443
        return host, port

    def _parse_vless_link(self, link):
        """Парсинг vless:// ссылки."""
        parsed = urllib.parse.urlparse(link)
        netloc = parsed.netloc
        if "@" not in netloc:
            return None
        uuid, endpoint = netloc.split("@", 1)
        host, port = self._parse_endpoint(endpoint)
        query = urllib.parse.parse_qs(parsed.query)
        params = {k: v[0] for k, v in query.items()}
        name = urllib.parse.unquote(parsed.fragment) if parsed.fragment else f"VLESS {host}:{port}"

        extra_val = params.get("extra", "")
        extra_obj = None
        if extra_val:
            try:
                extra_obj = json.loads(urllib.parse.unquote(extra_val))
            except Exception:
                try:
                    extra_obj = json.loads(extra_val)
                except Exception:
                    extra_obj = None

        alpn_val = params.get("alpn", "")
        alpn_list = [a.strip() for a in alpn_val.split(",") if a.strip()] if alpn_val else []

        return {
            "type": "vless",
            "name": name,
            "server": host,
            "port": port,
            "uuid": uuid,
            "security": params.get("security", "none"),
            "sni": params.get("sni", ""),
            "pbk": params.get("pbk", ""),
            "sid": params.get("sid", ""),
            "spx": params.get("spx", ""),
            "flow": params.get("flow", ""),
            "fp": params.get("fp", "chrome"),
            "transport": params.get("type", "tcp"),
            "service_name": params.get("serviceName", ""),
            "path": params.get("path", ""),
            "host": params.get("host", ""),
            "mode": params.get("mode", ""),
            "extra": extra_obj,
            "alpn": alpn_list,
        }

    def _parse_vmess_link(self, link):
        """Парсинг vmess:// ссылки (Base64 JSON)."""
        try:
            raw_b64 = link[8:].strip()
            fragment_name = ""
            if "#" in raw_b64:
                raw_b64, frag = raw_b64.split("#", 1)
                fragment_name = urllib.parse.unquote(frag.strip())
            if "?" in raw_b64:
                raw_b64 = raw_b64.split("?", 1)[0]

            b64_data = raw_b64.strip()
            padded = b64_data + "=" * (-len(b64_data) % 4)
            raw_json = base64.b64decode(padded).decode("utf-8")
            data = json.loads(raw_json)
            
            name = data.get("ps") or fragment_name or f"VMess {data.get('add')}:{data.get('port')}"
            tls_val = data.get("tls", "")
            security = "tls" if tls_val == "tls" else "none"
            
            return {
                "type": "vmess",
                "name": name,
                "server": data.get("add"),
                "port": int(data.get("port", 443)),
                "uuid": data.get("id"),
                "security": security,
                "sni": data.get("sni", ""),
                "transport": data.get("net", "tcp"),
                "path": data.get("path", "/"),
                "host": data.get("host", ""),
            }
        except Exception as e:
            self.log(f"Failed to parse vmess: {e}")
            return None

    def _parse_trojan_link(self, link):
        """Парсинг trojan:// ссылки."""
        try:
            parsed = urllib.parse.urlparse(link)
            netloc = parsed.netloc
            if "@" not in netloc:
                return None
            password, endpoint = netloc.split("@", 1)
            host, port = self._parse_endpoint(endpoint)
            query = urllib.parse.parse_qs(parsed.query)
            params = {k: v[0] for k, v in query.items()}
            name = urllib.parse.unquote(parsed.fragment) if parsed.fragment else f"Trojan {host}:{port}"
            
            return {
                "type": "trojan",
                "name": name,
                "server": host,
                "port": port,
                "password": password,
                "security": "tls",
                "sni": params.get("sni", ""),
                "transport": params.get("type", "tcp"),
                "service_name": params.get("serviceName", ""),
                "path": params.get("path", ""),
                "host": params.get("host", ""),
            }
        except Exception as e:
            self.log(f"Failed to parse trojan: {e}")
            return None

    def _parse_ss_link(self, link):
        """Парсинг ss:// ссылки (поддерживает base64 credentials и plain)."""
        try:
            parsed = urllib.parse.urlparse(link)
            netloc = parsed.netloc
            
            if "@" not in netloc:
                try:
                    padded = netloc + "=" * (-len(netloc) % 4)
                    decoded = base64.b64decode(padded).decode("utf-8")
                    if "@" in decoded:
                        netloc = decoded
                except Exception:
                    pass
            
            if "@" not in netloc:
                return None
                
            credentials, endpoint = netloc.split("@", 1)
            if ":" not in credentials:
                try:
                    padded = credentials + "=" * (-len(credentials) % 4)
                    credentials = base64.b64decode(padded).decode("utf-8")
                except Exception:
                    pass
            
            if ":" not in credentials:
                return None
                
            method, password = credentials.split(":", 1)
            host, port = self._parse_endpoint(endpoint)
            name = urllib.parse.unquote(parsed.fragment) if parsed.fragment else f"Shadowsocks {host}:{port}"
            
            return {
                "type": "shadowsocks",
                "name": name,
                "server": host,
                "port": port,
                "method": method,
                "password": password,
                "security": "none",
            }
        except Exception as e:
            self.log(f"Failed to parse ss: {e}")
            return None

    def _parse_hysteria2_link(self, link):
        """Парсинг hysteria2:// или hy2:// ссылки."""
        try:
            parsed = urllib.parse.urlparse(link)
            netloc = parsed.netloc
            if "@" not in netloc:
                return None
            password, endpoint = netloc.split("@", 1)
            host, port = self._parse_endpoint(endpoint)
            query = urllib.parse.parse_qs(parsed.query)
            params = {k: v[0] for k, v in query.items()}
            name = urllib.parse.unquote(parsed.fragment) if parsed.fragment else f"Hysteria2 {host}:{port}"
            
            insecure = params.get("insecure", "0") in ("1", "true")
            
            return {
                "type": "hysteria2",
                "name": name,
                "server": host,
                "port": port,
                "password": password,
                "security": "tls",
                "sni": params.get("sni", ""),
                "insecure": insecure,
                "obfs_type": params.get("obfs", ""),
                "obfs_password": params.get("obfs-password", ""),
            }
        except Exception as e:
            self.log(f"Failed to parse hysteria2: {e}")
            return None

    # ────────────────────────────────────────────────
    # Генерация конфига Xray-core
    # ────────────────────────────────────────────────

    def generate_config(self, node):
        """Создаёт xray-config.json с SOCKS5 inbound и соответствующим outbound."""
        server_host = node["server"]
        server_ip = self._resolve_host(server_host) or server_host
        self.log(f"Generating Xray config for server: {server_host} (resolved IP: {server_ip})")

        outbound = {}
        protocol = node.get("type")

        if protocol == "vless":
            stream_settings = {}
            transport = node.get("transport", "tcp")

            if transport == "xhttp":
                stream_settings["network"] = "xhttp"
                xhttp_settings = {
                    "path": node.get("path") or "/",
                    "host": node.get("host") or node.get("sni") or server_host,
                    "mode": node.get("mode") or "packet-up",
                }
                if node.get("extra"):
                    xhttp_settings["extra"] = node["extra"]
                stream_settings["xhttpSettings"] = xhttp_settings

                stream_settings["security"] = "tls"
                stream_settings["tlsSettings"] = {
                    "serverName": node.get("sni") or node.get("host") or server_host,
                    "fingerprint": node.get("fp") or "edge",
                    "alpn": node.get("alpn") or ["h2"]
                }
            elif transport == "grpc":
                stream_settings["network"] = "grpc"
                stream_settings["grpcSettings"] = {
                    "serviceName": node.get("service_name", "grpc"),
                    "multiMode": node.get("mode") == "multi"
                }
            elif transport in ("ws", "websocket"):
                stream_settings["network"] = "ws"
                ws_settings = {"path": node.get("path") or "/"}
                if node.get("host") or node.get("sni"):
                    ws_settings["headers"] = {"Host": node.get("host") or node.get("sni")}
                stream_settings["wsSettings"] = ws_settings
            else:
                stream_settings["network"] = "tcp"

            # Настройки безопасности (Reality / TLS / None)
            security = node.get("security", "none")
            if security == "reality":
                stream_settings["security"] = "reality"
                stream_settings["realitySettings"] = {
                    "serverName": node.get("sni") or server_host,
                    "fingerprint": node.get("fp") or "chrome",
                    "publicKey": node.get("pbk", ""),
                    "shortId": node.get("sid", ""),
                    "spiderX": node.get("spx", "")
                }
            elif security == "tls" and transport != "xhttp":
                stream_settings["security"] = "tls"
                stream_settings["tlsSettings"] = {
                    "serverName": node.get("sni") or server_host,
                    "fingerprint": node.get("fp") or "chrome",
                    "alpn": node.get("alpn") or []
                }
            elif security == "none" and transport != "xhttp":
                stream_settings["security"] = "none"

            user_obj = {
                "id": node["uuid"],
                "encryption": "none",
            }
            if node.get("flow"):
                user_obj["flow"] = node["flow"]

            outbound = {
                "protocol": "vless",
                "tag": "proxy",
                "settings": {
                    "vnext": [
                        {
                            "address": server_ip,
                            "port": node["port"],
                            "users": [user_obj]
                        }
                    ]
                },
                "streamSettings": stream_settings
            }

        elif protocol == "vmess":
            stream_settings = {"network": node.get("transport", "tcp")}
            if node.get("security") == "tls":
                stream_settings["security"] = "tls"
                stream_settings["tlsSettings"] = {
                    "serverName": node.get("sni") or server_host,
                    "fingerprint": node.get("fp") or "chrome"
                }
            outbound = {
                "protocol": "vmess",
                "tag": "proxy",
                "settings": {
                    "vnext": [
                        {
                            "address": server_ip,
                            "port": node["port"],
                            "users": [
                                {
                                    "id": node["uuid"],
                                    "alterId": 0,
                                    "security": "auto"
                                }
                            ]
                        }
                    ]
                },
                "streamSettings": stream_settings
            }

        elif protocol == "trojan":
            stream_settings = {
                "network": node.get("transport", "tcp"),
                "security": "tls",
                "tlsSettings": {
                    "serverName": node.get("sni") or server_host,
                    "fingerprint": node.get("fp") or "chrome"
                }
            }
            outbound = {
                "protocol": "trojan",
                "tag": "proxy",
                "settings": {
                    "servers": [
                        {
                            "address": server_ip,
                            "port": node["port"],
                            "password": node["password"]
                        }
                    ]
                },
                "streamSettings": stream_settings
            }

        elif protocol == "shadowsocks":
            outbound = {
                "protocol": "shadowsocks",
                "tag": "proxy",
                "settings": {
                    "servers": [
                        {
                            "address": server_ip,
                            "port": node["port"],
                            "method": node["method"],
                            "password": node["password"]
                        }
                    ]
                }
            }

        settings = self.load_settings()
        preset = settings.get("selected_preset", "default")
        self.log(f"Generating config with routing preset: {preset}")

        outbounds = [
            outbound,
            {"protocol": "freedom", "tag": "direct", "settings": {"domainStrategy": "UseIP"}},
            {"protocol": "blackhole", "tag": "block"}
        ]

        routing_rules = []
        if preset == "roscomvpn":
            routing_rules = [
                {"type": "field", "ip": ["geoip:private"], "outboundTag": "direct"},
                {"type": "field", "outboundTag": "proxy", "network": "tcp,udp"}
            ]
        else:
            routing_rules = [
                {"type": "field", "outboundTag": "proxy", "network": "tcp,udp"}
            ]

        config = {
            "log": {
                "loglevel": "warning"
            },
            "inbounds": [
                {
                    "tag": "socks-in",
                    "port": 10808,
                    "listen": "127.0.0.1",
                    "protocol": "socks",
                    "settings": {
                        "auth": "noauth",
                        "udp": True
                    },
                    "sniffing": {
                        "enabled": True,
                        "destOverride": ["http", "tls", "quic"]
                    }
                }
            ],
            "outbounds": outbounds,
            "routing": {
                "domainStrategy": "AsIs",
                "rules": routing_rules
            }
        }

        with open(self.config_path, "w") as f:
            json.dump(config, f, indent=2)

        self.log(f"Config written to {self.config_path}")
        return server_ip

    def _get_clean_env(self):
        """Очищает переменные окружения от путей PyInstaller/MEI."""
        env = os.environ.copy()
        if "LD_LIBRARY_PATH" in env:
            paths = [p for p in env["LD_LIBRARY_PATH"].split(":") if "/tmp/" not in p and "_MEI" not in p]
            if paths:
                env["LD_LIBRARY_PATH"] = ":".join(paths)
            else:
                del env["LD_LIBRARY_PATH"]
        env["XRAY_LOCATION_ASSET"] = self.bin_dir
        return env

    # ────────────────────────────────────────────────
    # Управление процессами (Xray + tun2socks)
    # ────────────────────────────────────────────────

    def start(self, node):
        """Запускает связку Xray + tun2socks с выбранным сервером."""
        self.stop()  # гасим предыдущие процессы и маршруты

        if not self.ensure_binaries():
            self.log("Required binaries (xray/tun2socks) not available, aborting start")
            return False

        gw_ip, iface = self._get_default_gateway()
        self.log(f"Detected default gateway: {gw_ip} via {iface}")

        server_ip = self.generate_config(node)

        # 1. Запуск Xray
        xray_log_path = os.path.join(self.settings_dir, "xray.log")
        try:
            xray_log = open(xray_log_path, "w")
            self.xray_process = subprocess.Popen(
                [self.xray_path, "-config", self.config_path],
                stdout=xray_log,
                stderr=xray_log,
                env=self._get_clean_env(),
                start_new_session=True
            )
            xray_log.close()
            self.log(f"xray started, PID={self.xray_process.pid}. Logs: {xray_log_path}")
        except Exception as e:
            self.log(f"Failed to start xray: {e}")
            self.stop()
            return False

        # Ожидаем готовности SOCKS-порта Xray
        time.sleep(1.0)
        if not self._check_socket_open("127.0.0.1", 10808):
            self.log("Xray failed to bind to 127.0.0.1:10808")
            self.stop()
            return False

        # 2. Запуск tun2socks
        tun_log_path = os.path.join(self.settings_dir, "tun2socks.log")
        try:
            tun_log = open(tun_log_path, "w")
            self.tun_process = subprocess.Popen(
                [self.tun2socks_path, "-d", "tun0", "-p", "socks5://127.0.0.1:10808"],
                stdout=tun_log,
                stderr=tun_log,
                env=self._get_clean_env(),
                start_new_session=True
            )
            tun_log.close()
            self.log(f"tun2socks started, PID={self.tun_process.pid}. Logs: {tun_log_path}")
        except Exception as e:
            self.log(f"Failed to start tun2socks: {e}")
            self.stop()
            return False

        # Ожидаем создания интерфейса tun0
        time.sleep(0.8)

        # 3. Настройка tun0 и маршрутизации
        self._run_cmd(["ip", "addr", "add", "198.18.0.1/15", "dev", "tun0"])
        self._run_cmd(["ip", "link", "set", "dev", "tun0", "up"])

        # Защита от зацикливания: трафик до VPN-сервера направляем через физический шлюз
        if server_ip and gw_ip and iface:
            self._run_cmd(["ip", "route", "add", server_ip, "via", gw_ip, "dev", iface])

        # Перенаправляем весь остальной трафик в tun0 с высшим приоритетом (metric 1)
        self._run_cmd(["ip", "route", "add", "default", "dev", "tun0", "metric", "1"])

        # Настраиваем DNS через tun0
        self._run_cmd(["resolvectl", "dns", "tun0", "8.8.8.8", "1.1.1.1"])
        self._run_cmd(["resolvectl", "domain", "tun0", "~."])
        self._run_cmd(["resolvectl", "default-route", "tun0", "yes"])

        self._last_server_ip = server_ip
        self._last_gw_ip = gw_ip
        self._last_iface = iface

        settings = self.load_settings()
        settings["selected_node"] = node
        settings["_routing_state"] = {
            "server_ip": server_ip,
            "gw_ip": gw_ip,
            "iface": iface
        }
        self.save_settings(settings)
        self.log(f"VPN connected successfully to {node.get('name')}")
        return True

    def stop(self):
        """Останавливает tun2socks, xray и восстанавливает маршруты."""
        self.log("Stopping VPN (xray + tun2socks)...")

        settings = self.load_settings()
        routing_state = settings.get("_routing_state") or {}
        server_ip = self._last_server_ip or routing_state.get("server_ip")
        gw_ip = self._last_gw_ip or routing_state.get("gw_ip")
        iface = self._last_iface or routing_state.get("iface")

        # Восстановление маршрутизации
        self._run_cmd(["ip", "route", "del", "default", "dev", "tun0", "metric", "1"])
        if server_ip and gw_ip and iface:
            self._run_cmd(["ip", "route", "del", server_ip, "via", gw_ip, "dev", iface])
        self._run_cmd(["resolvectl", "revert", "tun0"])
        self._run_cmd(["ip", "link", "delete", "tun0"])

        # Остановка процессов
        for proc in (self.tun_process, self.xray_process, self.process):
            if proc:
                try:
                    proc.terminate()
                except Exception:
                    pass

        try:
            subprocess.run(["pkill", "-f", self.tun2socks_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["pkill", "-f", self.xray_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

        time.sleep(0.5)

        for proc_name in ("xray", "tun2socks"):
            try:
                subprocess.run(["pkill", "-9", "-x", proc_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass

        self.tun_process = None
        self.xray_process = None
        self.process = None
        self._last_server_ip = None
        self._last_gw_ip = None
        self._last_iface = None

        settings["selected_node"] = None
        settings.pop("_routing_state", None)
        self.save_settings(settings)
        self.log("VPN stopped cleanly.")

    def is_running(self):
        """Проверяет, запущены ли процессы VPN."""
        try:
            res_xray = subprocess.run(["pgrep", "-x", "xray"], stdout=subprocess.PIPE)
            res_tun = subprocess.run(["pgrep", "-x", "tun2socks"], stdout=subprocess.PIPE)
            return res_xray.returncode == 0 and res_tun.returncode == 0
        except Exception:
            return False

    def get_singbox_log(self):
        """Возвращает логи Xray и tun2socks."""
        logs = []
        for name, fname in [("XRAY", "xray.log"), ("TUN2SOCKS", "tun2socks.log")]:
            fpath = os.path.join(self.settings_dir, fname)
            if os.path.exists(fpath):
                try:
                    with open(fpath, "r", errors="replace") as f:
                        lines = f.readlines()
                        logs.append(f"=== {name} LOGS ===\n" + "".join(lines[-30:]))
                except Exception as e:
                    logs.append(f"=== {name} LOGS ===\nError reading: {e}")
            else:
                logs.append(f"=== {name} LOGS ===\nNo log file found.")
        return "\n\n".join(logs)


