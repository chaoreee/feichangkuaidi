"""阻塞 socket + 双线程 TCP 客户端（IO 模型见 docs/architecture.md §4）。

- 接收线程：持续 recv 字节 -> FrameDecoder 拆帧 -> 完整消息入队。
- 主线程：从队列取消息决策，直接 sendall 发送。
接收与决策分线程，互不阻塞；单帧决策慢不会导致漏读服务端下发。
"""

import queue
import socket
import threading

import config
from protocol.framing import FrameDecoder, FramingError

# 队列哨兵：接收线程结束时入队，用于唤醒等待中的消费者。
_SENTINEL = object()


class TcpClient:
    def __init__(self, host, port, logger=None):
        self.host = host
        self.port = int(port)
        self._logger = logger
        self._sock = None
        self._decoder = FrameDecoder()
        self._inbox = queue.Queue()
        self._recv_thread = None
        self._stop = threading.Event()
        # 接收线程已结束（对端关闭 / 出错）
        self.recv_ended = threading.Event()
        self.error = None  # 首个致命异常（供主线程诊断）

    # ---- 连接生命周期 ----

    def connect(self, timeout=None):
        timeout = config.CONNECT_TIMEOUT if timeout is None else timeout
        self._sock = socket.create_connection((self.host, self.port), timeout=timeout)
        self._sock.settimeout(None)  # 接收线程用阻塞读
        self._recv_thread = threading.Thread(
            target=self._recv_loop, name="tcp-recv", daemon=True
        )
        self._recv_thread.start()

    def close(self):
        self._stop.set()
        if self._sock is not None:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self._sock.close()
            except OSError:
                pass

    # ---- 收发 ----

    def send(self, envelope):
        """发送一个消息信封（dict）。失败抛 OSError，由调用方处理。"""
        from protocol.framing import encode_frame
        self._sock.sendall(encode_frame(envelope))

    def recv(self, timeout):
        """取下一条消息 dict；超时返回 None；对端关闭亦返回 None（配合 recv_ended 判断）。"""
        try:
            msg = self._inbox.get(timeout=timeout)
        except queue.Empty:
            return None
        if msg is _SENTINEL:
            return None
        return msg

    # ---- 接收线程 ----

    def _recv_loop(self):
        try:
            while not self._stop.is_set():
                data = self._sock.recv(config.RECV_CHUNK)
                if not data:
                    break  # 对端关闭连接
                self._decoder.feed(data)
                for message in self._decoder.frames():
                    self._inbox.put(message)
        except FramingError as exc:
            self.error = exc  # 字节流失步，不可恢复
            self._log_error("framing_error", str(exc))
        except OSError as exc:
            if not self._stop.is_set():
                self.error = exc
                self._log_error("socket_error", str(exc))
        finally:
            self.recv_ended.set()
            self._inbox.put(_SENTINEL)

    def _log_error(self, kind, detail):
        if self._logger is not None:
            self._logger.trace("Error", error=kind, detail=detail)
