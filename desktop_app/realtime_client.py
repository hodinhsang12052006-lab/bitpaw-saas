"""
Kết nối Socket.io THẬT từ Desktop App lên cloud_relay/socket_server/ (Railway/Render — KHÔNG
phải Vercel, xem ghi chú trong cloud_relay/socket_server/server.js). Giữ 1 kết nối ngầm,
auto-reconnect khi mạng chập chờn, nhận tin nhắn Zalo/FB real-time và gọi callback để ghi
vào bot_messages/bot_customers của app.

Yêu cầu cài đặt: pip install python-socketio[client]
"""
import logging
import threading

import socketio

logger = logging.getLogger("bitpaw.realtime_client")

SOCKET_SERVER_URL = "https://bitpaw-relay.up.railway.app"  # đổi thành domain thật sau khi deploy
RECONNECT_DELAY_SEC = 3
RECONNECT_DELAY_MAX_SEC = 30


class RelaySocketClient:
    """Wrapper quanh python-socketio để: (1) tự reconnect vô hạn khi mất mạng, (2) không bao
    giờ để lỗi kết nối làm crash tiến trình Flask nền, (3) log lỗi thật thay vì nuốt bằng
    pass — mọi exception trong on_new_message đều được bắt và log rõ ràng."""

    def __init__(self, business_id, api_key, on_new_message):
        self.business_id = business_id
        self.api_key = api_key
        self.on_new_message = on_new_message
        self.sio = socketio.Client(
            reconnection=True,
            reconnection_delay=RECONNECT_DELAY_SEC,
            reconnection_delay_max=RECONNECT_DELAY_MAX_SEC,
        )
        self._register_handlers()
        self._thread = None

    def _register_handlers(self):
        @self.sio.event
        def connect():
            logger.info("[RelaySocketClient] Đã kết nối tới Cloud Relay (business_id=%s).", self.business_id)

        @self.sio.event
        def connect_error(data):
            logger.error("[RelaySocketClient] Kết nối thất bại: %s", data)

        @self.sio.event
        def disconnect():
            logger.warning("[RelaySocketClient] Mất kết nối tới Cloud Relay — sẽ tự động thử lại.")

        @self.sio.on("new-message")
        def _handle_new_message(data):
            try:
                self.on_new_message(data)
            except Exception:
                # Lỗi xử lý 1 tin nhắn KHÔNG được phép làm rớt kết nối socket hay crash thread
                # nền — log đầy đủ traceback để còn biết mà sửa, thay vì print rồi bỏ qua.
                logger.exception(
                    "[RelaySocketClient] Lỗi khi xử lý tin nhắn real-time (business_id=%s): %s",
                    self.business_id, data,
                )

    def start(self):
        """Chạy kết nối trong 1 thread nền riêng, không block luồng chính của Flask."""
        self._thread = threading.Thread(target=self._run_forever, daemon=True)
        self._thread.start()

    def _run_forever(self):
        try:
            self.sio.connect(
                SOCKET_SERVER_URL,
                auth={"business_id": self.business_id, "api_key": self.api_key},
                transports=["websocket"],
            )
            self.sio.wait()
        except socketio.exceptions.ConnectionError as e:
            logger.error(
                "[RelaySocketClient] Không thể thiết lập kết nối ban đầu tới Cloud Relay: %s. "
                "Sẽ không nhận được tin nhắn real-time cho tới khi kết nối lại được.", e,
            )
        except Exception:
            logger.exception("[RelaySocketClient] Lỗi không xác định trong vòng lặp kết nối socket.")

    def stop(self):
        try:
            self.sio.disconnect()
        except Exception:
            logger.exception("[RelaySocketClient] Lỗi khi ngắt kết nối socket.")
