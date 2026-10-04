# -*- coding: utf-8 -*-
import json
import logging
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWebSockets import QWebSocketServer, QWebSocket
from PyQt6.QtNetwork import QHostAddress

logger = logging.getLogger(__name__)

class PluginServer(QObject):
    """
    WebSocket server for managing multi-browser extension connections and real-time task dispatching.
    """
    # Signals
    client_connected_signal = pyqtSignal(dict)       # Emitted when worker sends 'online' or connects
    client_disconnected_signal = pyqtSignal(str)     # Emitted when worker disconnects (client_id)
    client_updated_signal = pyqtSignal(dict)          # Emitted when worker status or points update
    report_received_signal = pyqtSignal(dict)         # Emitted when worker completes batch and sends report
    rpc_response_signal = pyqtSignal(dict)            # Emitted when worker responds to JSON-RPC action
    alarm_detected_signal = pyqtSignal(dict)          # Emitted when worker encounters Google security/risk limits

    def __init__(self, port=18188, parent=None):
        super().__init__(parent)
        self.port = port
        self.ports = [port] if port != 18188 else [18188, 8000, 8765]
        self.servers = []
        self.clients = {}  # socket -> dict info: {client_id, name, remaining_points, status, socket}
        self.client_id_counter = 1

    def start(self):
        """Starts the WebSocket server listening on configured ports."""
        if self.servers:
            return True

        started_any = False
        for p in self.ports:
            try:
                server = QWebSocketServer(
                    f"FlowPluginServer_{p}",
                    QWebSocketServer.SslMode.NonSecureMode,
                    self
                )
                if server.listen(QHostAddress.SpecialAddress.LocalHost, p):
                    logger.info(f"WebSocket server started listening on ws://127.0.0.1:{p}")
                    server.newConnection.connect(lambda s=server: self.on_new_connection_from_server(s))
                    self.servers.append(server)
                    started_any = True
                else:
                    logger.warning(f"Port {p} in use or unavailable: {server.errorString()}")
            except Exception as e:
                logger.warning(f"Failed to start server on port {p}: {e}")

        return started_any

    def stop(self):
        """Stops all WebSocket servers."""
        for socket in list(self.clients.keys()):
            try:
                socket.disconnected.disconnect()
            except Exception:
                pass
            try:
                socket.close()
            except Exception:
                pass
        self.clients.clear()

        for s in self.servers:
            try:
                s.close()
            except Exception:
                pass
        self.servers.clear()
        logger.info("All WebSocket servers stopped.")

    def on_new_connection_from_server(self, server):
        """Handles new WebSocket client connection from any listening server."""
        if not server:
            return
        socket = server.nextPendingConnection()
        if not socket:
            return
            
        # Security: Validate Origin header against Cross-Site WebSocket Hijacking (CSWSH)
        client_origin = socket.origin()
        if client_origin:
            origin_lower = client_origin.lower().strip()
            # Explicitly reject 'null' origin to prevent CSWSH attacks from sandboxed iframes or data URLs
            if origin_lower == "null":
                logger.warning("🚨 [Security] Rejected untrusted WebSocket connection from null Origin")
                socket.close()
                return

            import urllib.parse
            try:
                parsed_origin = urllib.parse.urlparse(origin_lower)
                scheme = parsed_origin.scheme
                hostname = (parsed_origin.hostname or "").lower()
            except Exception:
                logger.warning(f"🚨 [Security] Rejected malformed Origin: {client_origin}")
                socket.close()
                return

            is_allowed = False
            # 1. Browser extension schemes
            if scheme in ("chrome-extension", "moz-extension", "safari-web-extension"):
                is_allowed = True
            # 2. Localhost web origins
            elif scheme in ("http", "https") and hostname in ("127.0.0.1", "localhost"):
                is_allowed = True
            # 3. Legitimate Google web origins for Labs / AI Test Kitchen
            elif scheme == "https":
                google_hosts = (
                    "labs.google",
                    "aitestkitchen.withgoogle.com",
                    "google.com",
                    "googleusercontent.com"
                )
                if hostname in google_hosts or any(hostname.endswith(f".{d}") for d in google_hosts):
                    is_allowed = True

            if not is_allowed:
                logger.warning(f"🚨 [Security] Rejected untrusted WebSocket connection from Origin: {client_origin}")
                socket.close()
                return

        temp_id = f"Worker_{self.client_id_counter}"
        self.client_id_counter += 1

        client_info = {
            "client_id": temp_id,
            "email": "",
            "name": f"浏览器 ({temp_id})",
            "remaining_points": 0,
            "status": "low_points",
            "socket": socket,
            "current_batch": None
        }

        self.clients[socket] = client_info

        socket.textMessageReceived.connect(lambda msg, s=socket: self.on_message_received(s, msg))
        socket.disconnected.connect(lambda s=socket: self.on_client_disconnected(s))

        self.client_connected_signal.emit(client_info)
        self.client_updated_signal.emit(client_info)

    def on_client_disconnected(self, socket):
        """Handles WebSocket client disconnection."""
        try:
            if socket in self.clients:
                info = self.clients.pop(socket)
                client_id = info["client_id"]
                logger.info(f"Client disconnected: {client_id}")
                try:
                    self.client_disconnected_signal.emit(client_id)
                except Exception:
                    pass
        except Exception:
            pass

    def on_message_received(self, socket, message_str):
        """Parses incoming JSON message from client (supporting both type, event, and RPC action formats)."""
        if socket not in self.clients:
            return

        info = self.clients[socket]
        try:
            msg = json.loads(message_str)
        except Exception as e:
            logger.warning(f"Invalid JSON received from {info.get('client_id')}: {e}")
            return

        msg_type = msg.get("type") or msg.get("event") or msg.get("action")

        # 0. 心跳包 (Ping/Pong)
        if msg_type == "ping":
            try:
                socket.sendTextMessage(json.dumps({"type": "pong"}))
            except Exception:
                pass
            return

        # 1. 客户端首次上线/注册 / 欢迎握手注册 / 点数响应 (以真实 Google 邮箱或唯一 client_id 更新)
        if msg_type in ("online", "client_connected", "get_points_response") or str(msg_type).startswith("get_points"):
            data_obj = msg.get("data") if isinstance(msg.get("data"), dict) else {}
            
            raw_email = msg.get("email") or data_obj.get("email") or ""
            raw_name = msg.get("name") or data_obj.get("name") or ""
            raw_client_id = msg.get("client_id") or data_obj.get("client_id") or ""
            
            # 为每个独立的 socket 分配唯一且可读的 ID，支持同账号多开窗口以及多账号同时并发
            socket_suffix = abs(id(socket)) % 10000
            if raw_email:
                info["email"] = raw_email
                info["client_id"] = f"{raw_email} (W#{socket_suffix})"
            elif raw_client_id:
                info["client_id"] = f"{raw_client_id}_{socket_suffix}" if not raw_client_id.endswith(str(socket_suffix)) else raw_client_id

            if raw_name:
                info["name"] = raw_name
            elif raw_email:
                info["name"] = raw_email

            credits = msg.get("credits") or msg.get("remaining_points") or data_obj.get("remaining_points")
            if credits is not None:
                info["remaining_points"] = int(credits)
                info["status"] = "idle" if int(credits) >= 7 else "low_points"

            logger.info(f"✅ Client identified: {info['client_id']} ({info['name']}), Points: {info['remaining_points']}")
            self.client_updated_signal.emit(info)
            return

        # 2. 状态/点数实时更新
        if msg_type == "status_update":
            if "remaining_points" in msg:
                info["remaining_points"] = int(msg.get("remaining_points", 0))
            if "status" in msg:
                info["status"] = msg.get("status")
            self.client_updated_signal.emit(info)

        # 3. 任务执行完成报告 / 单条视频完成
        elif msg_type in ("execution_report", "video_completed"):
            if "remaining_points" in msg or "credits" in msg:
                credits = msg.get("credits") if msg.get("credits") is not None else (msg.get("remaining_points") if msg.get("remaining_points") is not None else info.get("remaining_points", 0))
                info["remaining_points"] = int(credits)

            info["status"] = "idle" if info.get("remaining_points", 0) >= 7 else "low_points"
            info["current_batch"] = None

            if msg_type == "video_completed":
                s_idx = msg.get("segment_index")
                if s_idx is None:
                    s_idx = msg.get("s_idx")
                
                data_list = [{
                    "index": s_idx,
                    "prompt": msg.get("prompt", ""),
                    "download_url": msg.get("url") or msg.get("download_url") or msg.get("rawUrl"),
                    "download_path": msg.get("download_path"),
                    "base64Data": msg.get("base64Data") or msg.get("base64_data"),
                    "status": "success",
                    "message": "video_completed"
                }]
            else:
                data_list = msg.get("data", [])

            report_data = {
                "client_id": info["client_id"],
                "batch_id": msg.get("batch_id"),
                "remaining_points": info.get("remaining_points", 0),
                "data": data_list,
                "raw_message": msg
            }

            logger.info(f"Execution/video_completed report received from {info['client_id']} ({len(data_list)} items)")
            self.report_received_signal.emit(report_data)
            self.client_updated_signal.emit(info)

        # 4. JSON-RPC 开放接口响应 (如 get_points_response, upload_image_response, generate_video_response)
        elif str(msg_type).endswith("_response") or "request_id" in msg:
            if "data" in msg and isinstance(msg["data"], dict) and "remaining_points" in msg["data"]:
                info["remaining_points"] = int(msg["data"]["remaining_points"])
                self.client_updated_signal.emit(info)
            
            logger.info(f"RPC Response received [{msg_type}] from {info['client_id']}")
            self.rpc_response_signal.emit({
                "client_id": info["client_id"],
                "message": msg
            })

        # 5. 安全限制风控报警推送
        elif msg_type == "alarm_detected":
            logger.warning(f"🚨 Google Security Alarm received from {info['client_id']}: {msg.get('message')}")
            info["status"] = "suspended"
            self.alarm_detected_signal.emit({
                "client_id": info["client_id"],
                "message": msg.get("message", "检测到 Google 安全限制（异常活动）")
            })
            self.client_updated_signal.emit(info)

        elif msg_type == "pong":
            pass

    def send_rpc_action(self, client_id, action, params=None, request_id=None):
        """
        Sends an atomic JSON-RPC request to a specific client.
        """
        target_socket = None
        for socket, info in self.clients.items():
            if info["client_id"] == client_id:
                target_socket = socket
                break

        if not target_socket:
            logger.warning(f"Cannot send RPC action: Client {client_id} not found.")
            return False

        import uuid
        req_id = request_id or f"req_{uuid.uuid4().hex[:8]}"
        payload = {
            "action": action,
            "request_id": req_id,
            "params": params or {}
        }

        try:
            target_socket.sendTextMessage(json.dumps(payload, ensure_ascii=False))
            logger.info(f"Sent RPC Action '{action}' (ID={req_id}) to {client_id}")
            return req_id
        except Exception as e:
            logger.error(f"Error sending RPC action to {client_id}: {e}")
            return False

    def send_tasks_to_client(self, client_id, batch_id, tasks_data):
        """
        Sends a batch of tasks to a specific connected client socket by client_id.
        Automatically converts local_image_path to Base64 image_data_url for seamless browser upload.
        """
        target_socket = None
        target_info = None

        for socket, info in self.clients.items():
            if info["client_id"] == client_id:
                target_socket = socket
                target_info = info
                break

        if not target_socket or not target_info:
            logger.warning(f"Cannot send tasks: Client {client_id} not found.")
            return False

        # Process tasks to add base64 image data URLs
        import base64
        from pathlib import Path

        processed_tasks = []
        for task in tasks_data:
            task_copy = dict(task)
            img_path = task_copy.get("local_image_path")
            
            if img_path and Path(img_path).exists():
                try:
                    p = Path(img_path)
                    ext = p.suffix.lower().replace(".", "")
                    if ext == "jpg":
                        ext = "jpeg"
                    mime = f"image/{ext}" if ext in ["png", "jpeg", "webp", "gif"] else "image/png"
                    
                    with open(p, "rb") as f:
                        b64_str = base64.b64encode(f.read()).decode("utf-8")
                        task_copy["image_data_url"] = f"data:{mime};base64,{b64_str}"
                except Exception as err:
                    logger.warning(f"Failed to read image {img_path} for base64 encoding: {err}")

            processed_tasks.append(task_copy)

        payload = {
            "type": "execute_tasks",
            "batch_id": batch_id,
            "tasks": processed_tasks
        }

        try:
            target_info["status"] = "busy"
            target_info["current_batch"] = batch_id
            target_socket.sendTextMessage(json.dumps(payload, ensure_ascii=False))
            self.client_updated_signal.emit(target_info)
            logger.info(f"Sent Batch {batch_id} ({len(processed_tasks)} tasks) to {client_id}")
            return True
        except Exception as e:
            logger.error(f"Error sending tasks to {client_id}: {e}")
            target_info["status"] = "idle"
            return False

    def get_online_clients(self):
        """Returns list of client info dictionaries."""
        return list(self.clients.values())

    def query_all_clients_points(self):
        """Broadcasts get_points RPC request to all currently connected browser clients."""
        online_clients = self.get_online_clients()
        sent_count = 0
        for client in online_clients:
            client_id = client.get("client_id")
            if client_id:
                self.send_rpc_action(client_id, "get_points", {})
                sent_count += 1
        logger.info(f"Broadcasted get_points request to {sent_count} online clients.")
        return sent_count
