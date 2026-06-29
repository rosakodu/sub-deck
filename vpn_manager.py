import os
import sys
import json
import urllib.request
import urllib.parse
import base64
import subprocess
import shutil


class VPNManager:
    def __init__(self, plugin_dir, settings_dir, logger=None):
        self.plugin_dir = plugin_dir
        self.settings_dir = settings_dir
        self.bin_dir = os.path.join(self.settings_dir, "bin")
        self.singbox_path = os.path.join(self.bin_dir, "sing-box")
        self.config_path = os.path.join(self.settings_dir, "sing-box-config.json")
        self.nodes_cache_path = os.path.join(self.settings_dir, "nodes.json")
        self.settings_file = os.path.join(self.settings_dir, "settings.json")
        self.process = None
        self._logger = logger

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
        
        self.log(f"Starting parsing of all subscriptions: {len(urls)} links")
        for url in urls:
            try:
                nodes = self.parse_subscription(url)
                all_nodes.extend(nodes)
            except Exception as e:
                self.log(f"Failed to parse subscription {url}: {e}")
                
        # Сохраняем объединенные ноды в кэш
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

    def remove_subscription(self, url):
        settings = self.load_settings()
        subscriptions = settings.get("subscriptions", [])
        if url in subscriptions:
            subscriptions.remove(url)
            settings["subscriptions"] = subscriptions
            self.save_settings(settings)
            self.log(f"Removed subscription URL: {url}")
        return self.parse_all_subscriptions()


    def save_settings(self, settings):
        try:
            with open(self.settings_file, "w") as f:
                json.dump(settings, f)
        except Exception:
            pass

    def get_nodes(self):
        if os.path.exists(self.nodes_cache_path):
            try:
                with open(self.nodes_cache_path, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    # ────────────────────────────────────────────────
    # Загрузка sing-box
    # ────────────────────────────────────────────────

    def download_singbox(self):
        """Скачивает sing-box 1.9.3 для Linux amd64."""
        if os.path.exists(self.singbox_path):
            return True

        version = "1.9.3"
        url = (
            f"https://github.com/SagerNet/sing-box/releases/download/v{version}/"
            f"sing-box-{version}-linux-amd64.tar.gz"
        )
        tar_path = os.path.join(self.bin_dir, "sing-box.tar.gz")

        try:
            import ssl, tarfile
            self.log(f"Downloading sing-box {version}...")
            ctx = ssl._create_unverified_context()
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
                with open(tar_path, "wb") as f:
                    f.write(resp.read())

            with tarfile.open(tar_path, "r:gz") as tar:
                for member in tar.getmembers():
                    if member.name.endswith("/sing-box") or member.name == "sing-box":
                        member.name = "sing-box"
                        try:
                            tar.extract(member, path=self.bin_dir, filter="data")
                        except TypeError:
                            tar.extract(member, path=self.bin_dir)
                        break

            os.remove(tar_path)
            os.chmod(self.singbox_path, 0o755)
            self.log("sing-box downloaded OK")
            return True
        except Exception as e:
            self.log(f"Error downloading sing-box: {e}")
            if os.path.exists(tar_path):
                os.remove(tar_path)
            return False

    # ────────────────────────────────────────────────
    # Парсинг подписки
    # ────────────────────────────────────────────────

    def _do_http_get(self, url, user_agent):
        """Выполняет HTTP GET запрос, возвращает bytes."""
        import ssl
        # _create_unverified_context гарантированно отключает проверку SSL
        # в любой версии Python/OpenSSL на SteamOS
        ctx = ssl._create_unverified_context()
        req = urllib.request.Request(url, headers={"User-Agent": user_agent})
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            return resp.read()



    def fetch_raw(self, url):
        """Скачивает подписку и возвращает сырой текст для диагностики."""
        user_agents = ["v2rayN/6.0", "clash/1.18.0",
                       "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"]
        for ua in user_agents:
            try:
                data = self._do_http_get(url, ua)
                text = data.decode("utf-8", errors="replace").strip()
                return f"UA={ua} | len={len(text)} | content={repr(text[:500])}"
            except Exception as e:
                last = str(e)
        return f"ALL FAILED: {last}"

    def parse_subscription(self, url):
        """Скачивает подписку по URL и парсит ноды VLESS."""
        import traceback

        user_agents = [
            "v2rayN/6.0",
            "clash/1.18.0",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        ]

        content = None
        last_error = None

        for ua in user_agents:
            try:
                content = self._do_http_get(url, ua)
                self.log(f"Downloaded {len(content)} bytes with UA={ua}")
                break
            except Exception as e:
                last_error = e
                continue

        if content is None:
            self.log(f"parse_subscription FAILED: {last_error}")
            self.log(traceback.format_exc())
            return []

        try:
            text = content.decode("utf-8").strip()
        except Exception:
            text = content.decode("latin-1").strip()

        # Определяем формат: plain text или base64
        supported_schemes = ("vless://", "vmess://", "trojan://", "ss://", "hysteria2://", "hy2://")
        is_plain = any(text.startswith(sch) or f"\n{sch}" in text for sch in supported_schemes)

        lines = []
        if is_plain:
            lines = text.splitlines()
            self.log(f"Plain-text format, {len(lines)} lines")
        else:
            try:
                # Убираем пробелы для корректного base64
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
                    nodes.append(parsed_node)
            except Exception as e:
                self.log(f"Failed to parse line: {repr(line[:60])}: {e}")

        self.log(f"Protocols found: {proto_count}")
        self.log(f"Parsed {len(nodes)} total nodes")

        with open(self.nodes_cache_path, "w") as f:
            json.dump(nodes, f)

        return nodes

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
            "flow": params.get("flow", ""),
            "fp": params.get("fp", "chrome"),
            "transport": params.get("type", "tcp"),
            "service_name": params.get("serviceName", ""),
            "path": params.get("path", ""),
            "host": params.get("host", ""),
        }

    def _parse_vmess_link(self, link):
        """Парсинг vmess:// ссылки (Base64 JSON)."""
        try:
            b64_data = link[8:].strip()
            padded = b64_data + "=" * (-len(b64_data) % 4)
            raw_json = base64.b64decode(padded).decode("utf-8")
            data = json.loads(raw_json)
            
            name = data.get("ps", f"VMess {data.get('add')}:{data.get('port')}")
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
    # Генерация конфига sing-box
    # ────────────────────────────────────────────────

    def generate_config(self, node):
        """Создаёт sing-box-config.json с TUN-интерфейсом."""
        # Создаем outbound-блок под тип протокола
        outbound = {}
        
        if node["type"] == "vless":
            tls_enabled = node["security"] in ("tls", "reality")
            outbound = {
                "type": "vless",
                "tag": "proxy",
                "server": node["server"],
                "server_port": node["port"],
                "uuid": node["uuid"],
                **({"flow": node["flow"]} if node["flow"] else {}),
                "tls": {
                    "enabled": tls_enabled,
                    "server_name": node["sni"] or None,
                    "utls": {
                        "enabled": True,
                        "fingerprint": node["fp"] or "chrome",
                    },
                },
            }
            if node["security"] == "reality":
                outbound["tls"]["reality"] = {
                    "enabled": True,
                    "public_key": node["pbk"],
                    "short_id": node["sid"],
                }

        elif node["type"] == "vmess":
            outbound = {
                "type": "vmess",
                "tag": "proxy",
                "server": node["server"],
                "server_port": node["port"],
                "uuid": node["uuid"],
                "security": "auto",
                "tls": {
                    "enabled": node["security"] == "tls",
                    "server_name": node["sni"] or None,
                    "utls": {
                        "enabled": True,
                        "fingerprint": "chrome"
                    }
                }
            }

        elif node["type"] == "trojan":
            outbound = {
                "type": "trojan",
                "tag": "proxy",
                "server": node["server"],
                "server_port": node["port"],
                "password": node["password"],
                "tls": {
                    "enabled": True,
                    "server_name": node["sni"] or None,
                    "utls": {
                        "enabled": True,
                        "fingerprint": "chrome"
                    }
                }
            }

        elif node["type"] == "shadowsocks":
            outbound = {
                "type": "shadowsocks",
                "tag": "proxy",
                "server": node["server"],
                "server_port": node["port"],
                "method": node["method"],
                "password": node["password"],
            }

        elif node["type"] == "hysteria2":
            outbound = {
                "type": "hysteria2",
                "tag": "proxy",
                "server": node["server"],
                "server_port": node["port"],
                "password": node["password"],
                "tls": {
                    "enabled": True,
                    "server_name": node["sni"] or None,
                    "insecure": node.get("insecure", False)
                }
            }
            obfs_type = node.get("obfs_type")
            if obfs_type:
                outbound["obfs"] = {
                    "type": obfs_type,
                    "password": node.get("obfs_password", "")
                }

        # Добавляем настройки транспорта (gRPC / WebSocket / и т.д.) для поддерживаемых протоколов
        if node["type"] in ("vless", "vmess", "trojan"):
            transport_type = node.get("transport", "tcp")
            if transport_type == "grpc":
                outbound["transport"] = {
                    "type": "grpc",
                    "service_name": node.get("service_name", "grpc")
                }
            elif transport_type in ("ws", "websocket"):
                outbound["transport"] = {
                    "type": "ws",
                    "path": node.get("path", "/"),
                }
                if node.get("host"):
                    outbound["transport"]["headers"] = {
                        "Host": node["host"]
                    }



        config = {
            "log": {"level": "info", "timestamp": True},
            "dns": {
                "servers": [
                    {"tag": "dns_direct", "address": "1.1.1.1", "detour": "direct"},
                    {"tag": "dns_proxy", "address": "8.8.8.8", "detour": "proxy"},
                ],
                "rules": [
                    {"outbound": "any", "server": "dns_direct"},
                    {"query_type": ["A", "AAAA"], "server": "dns_proxy"},
                ],
            },
            "inbounds": [
                {
                    "type": "tun",
                    "tag": "tun-in",
                    "interface_name": "tun0",
                    # sing-box 1.9+ использует inet4_address вместо address
                    "inet4_address": "172.19.0.1/30",
                    "auto_route": True,
                    "strict_route": True,
                    "stack": "system",
                    "sniff": True,
                }
            ],
            "outbounds": [
                outbound,
                {"type": "direct", "tag": "direct"},
                {"type": "dns", "tag": "dns-out"},
            ],
            "route": {
                "rules": [
                    {"protocol": "dns", "outbound": "dns-out"},
                    {"ip_is_private": True, "outbound": "direct"}
                ],
                "auto_detect_interface": True,
            },
        }

        with open(self.config_path, "w") as f:
            json.dump(config, f, indent=2)

        self.log(f"Config written to {self.config_path}")

    def _get_clean_env(self):
        """Очищает переменные окружения от путей PyInstaller/MEI.
        Предотвращает падение sing-box из-за несовместимости библиотек.
        """
        env = os.environ.copy()
        if "LD_LIBRARY_PATH" in env:
            paths = [p for p in env["LD_LIBRARY_PATH"].split(":") if "/tmp/" not in p and "_MEI" not in p]
            if paths:
                env["LD_LIBRARY_PATH"] = ":".join(paths)
            else:
                del env["LD_LIBRARY_PATH"]
        return env

    # ────────────────────────────────────────────────
    # Управление процессом
    # ────────────────────────────────────────────────

    def start(self, node):
        """Запускает sing-box с выбранным сервером."""
        self.stop()  # гасим предыдущий процесс

        if not self.download_singbox():
            self.log("sing-box not available, aborting start")
            return False

        self.generate_config(node)

        # Перенаправляем логи sing-box в файл, чтобы не забивать PIPE и иметь историю ошибок
        log_file_path = os.path.join(self.settings_dir, "sing-box.log")
        try:
            log_file = open(log_file_path, "w")
            self.process = subprocess.Popen(
                [self.singbox_path, "run", "-c", self.config_path],
                stdout=log_file,
                stderr=log_file,
                env=self._get_clean_env(),
                start_new_session=True
            )
            self.log(f"sing-box started, PID={self.process.pid}. Logs: {log_file_path}")

            settings = self.load_settings()
            settings["selected_node"] = node
            self.save_settings(settings)
            return True
        except Exception as e:
            self.log(f"Failed to start sing-box: {e}")
            return False

    def stop(self):
        """Останавливает все процессы sing-box и ждет их завершения."""
        self.log("Stopping sing-box...")
        try:
            # Отправляем SIGTERM
            subprocess.run(
                ["pkill", "-x", "sing-box"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            self.log(f"Error calling pkill: {e}")

        # Ожидаем завершения процессов (до 5 секунд)
        import time
        start_time = time.time()
        while time.time() - start_time < 5:
            if not self.is_running():
                self.log("sing-box stopped cleanly.")
                break
            time.sleep(0.2)
        else:
            self.log("sing-box did not stop in time, sending SIGKILL...")
            try:
                subprocess.run(
                    ["pkill", "-9", "-x", "sing-box"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                pass
            
            # Принудительно удаляем tun0 интерфейс из ядра Linux, если он остался
            try:
                subprocess.run(
                    ["ip", "link", "delete", "tun0"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self.log("Force deleted tun0 interface.")
            except Exception:
                pass

        if self.process:
            try:
                self.process.terminate()
            except Exception:
                pass
            self.process = None

        settings = self.load_settings()
        settings["selected_node"] = None
        self.save_settings(settings)
        self.log("sing-box stopped")

    def is_running(self):
        """Проверяет, запущен ли sing-box."""
        try:
            # -x проверяет точное совпадение имени процесса
            res = subprocess.run(["pgrep", "-x", "sing-box"], stdout=subprocess.PIPE)
            return res.returncode == 0
        except Exception:
            return False

    def get_singbox_log(self):
        """Возвращает последние 50 строк лога sing-box."""
        log_file_path = os.path.join(self.settings_dir, "sing-box.log")
        if not os.path.exists(log_file_path):
            return "No logs found."
        try:
            with open(log_file_path, "r", errors="replace") as f:
                lines = f.readlines()
                return "".join(lines[-50:])
        except Exception as e:
            return f"Error reading log: {e}"


