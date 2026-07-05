"""TCP 帧编解码（协议 §1）。

帧格式：5 位十进制长度前缀（body 的 UTF-8 字节数，≤99999）+ UTF-8 JSON body。
接收端必须处理半包（缓存至完整）、粘包（按前缀循环拆多条）、中文跨包（先按字节缓存再 UTF-8 解码）。
消息边界只按长度前缀判断，不能按换行/read 次数判断。
"""

import json
import re

import config


class FramingError(Exception):
    """帧层不可恢复错误（长度前缀非法或 JSON 解析失败），意味着字节流失步。"""


# 匹配 JSON 字符串字面量（处理转义），用于把 body 切成「非字符串段 / 字符串段」交替序列，
# 这样下面的裸数字键修补只作用于非字符串段，绝不会改动字符串值内部。
_STRING_LITERAL_RE = re.compile(r'("(?:\\.|[^"\\])*")')
# 裸数字键：出现在 object 键位置（紧随 '{' 或 ',' 及空白），形如 `1001:` / `-1:` / `1.5:`。
# 标准 JSON 要求键为字符串，但比赛服务端某些消息会发出未加引号的数字键（如 `{1001:"MOVE"}`），
# Python 的 json.loads 会直接抛 JSONDecodeError 致整条帧失步。预处理把它们加上引号。
_BARE_NUMERIC_KEY_RE = re.compile(r'([{,]\s*)(-?\d+(?:\.\d+)?)(\s*:)', re.DOTALL)


def _quote_numeric_keys(text):
    """把 object 里的裸数字键补成字符串键（字符串字面量内部不动）。

    例：`{1001:"MOVE"}` → `{"1001":"MOVE"}`、`{1.5:-2, -3:"x"}` → `{"1.5":-2, "-3":"x"}`。
    仅在 '{' / ',' 之后的键位置匹配，数值（在 ':' 右侧）不受影响。
    """
    parts = _STRING_LITERAL_RE.split(text)
    # split 结果为 [非字符串, 字符串, 非字符串, 字符串, ...]；只改偶数下标段。
    for i in range(0, len(parts), 2):
        parts[i] = _BARE_NUMERIC_KEY_RE.sub(r'\1"\2"\3', parts[i])
    return "".join(parts)


def encode_frame(envelope):
    """把消息信封 dict 序列化为 `5位长度前缀 + UTF-8 body` 字节串。

    envelope 形如 {"msg_name": ..., "msg_data": {...}}。
    """
    body = json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(body) > config.MAX_FRAME_BODY_BYTES:
        raise FramingError(
            "body too large: %d > %d bytes" % (len(body), config.MAX_FRAME_BODY_BYTES)
        )
    prefix = str(len(body)).zfill(config.LENGTH_PREFIX_WIDTH).encode("ascii")
    return prefix + body


class FrameDecoder:
    """按长度前缀从字节流增量拆帧。

    用法：
        decoder.feed(chunk)              # 喂入任意长度字节
        for envelope in decoder.frames() # 取出当前已完整的所有帧（dict）
    半包会保留在内部缓冲，等待后续 feed。
    """

    _W = config.LENGTH_PREFIX_WIDTH

    def __init__(self):
        self._buf = bytearray()

    def feed(self, data):
        if data:
            self._buf.extend(data)

    def frames(self):
        while True:
            if len(self._buf) < self._W:
                return  # 连长度前缀都没收齐
            prefix = bytes(self._buf[: self._W])
            if not prefix.isdigit():
                raise FramingError("invalid length prefix: %r" % prefix)
            length = int(prefix)
            total = self._W + length
            if len(self._buf) < total:
                return  # body 未收齐（半包）
            body = bytes(self._buf[self._W : total])
            del self._buf[:total]
            try:
                text = body.decode("utf-8")
                # 容忍服务端发出的裸数字键（如 {1001:"MOVE"}），先补引号再解析。
                yield json.loads(_quote_numeric_keys(text))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise FramingError("bad frame body: %s" % exc) from exc

    @property
    def pending_bytes(self):
        """当前缓冲中尚未组成完整帧的字节数（用于诊断）。"""
        return len(self._buf)
