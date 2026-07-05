"""framing 单元测试：编码、往返、半包、粘包、中文跨包、非法前缀。

运行：从 client/ 目录执行 `python -m unittest tests.test_framing`
或直接 `python client/tests/test_framing.py`。
"""

import os
import sys
import unittest

# 让 client/ 在 import 路径上，便于直接运行本文件。
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from protocol.framing import FrameDecoder, FramingError, encode_frame  # noqa: E402


class TestFraming(unittest.TestCase):
    def test_encode_prefix_is_byte_length(self):
        env = {"msg_name": "ready", "msg_data": {"matchId": "m", "round": 1}}
        frame = encode_frame(env)
        prefix = frame[:5]
        body = frame[5:]
        self.assertTrue(prefix.isdigit())
        self.assertEqual(int(prefix), len(body))

    def test_roundtrip(self):
        env = {"msg_name": "action", "msg_data": {"round": 12, "actions": []}}
        dec = FrameDecoder()
        dec.feed(encode_frame(env))
        out = list(dec.frames())
        self.assertEqual(out, [env])

    def test_sticky_packets(self):
        e1 = {"msg_name": "a", "msg_data": {"x": 1}}
        e2 = {"msg_name": "b", "msg_data": {"y": 2}}
        dec = FrameDecoder()
        dec.feed(encode_frame(e1) + encode_frame(e2))
        out = list(dec.frames())
        self.assertEqual(out, [e1, e2])

    def test_half_packet(self):
        env = {"msg_name": "start", "msg_data": {"matchId": "match_x", "nodes": [1, 2, 3]}}
        frame = encode_frame(env)
        dec = FrameDecoder()
        # 分两次喂入，中间切在 body 中部
        cut = 5 + (len(frame) - 5) // 2
        dec.feed(frame[:cut])
        self.assertEqual(list(dec.frames()), [])  # 尚未收齐
        dec.feed(frame[cut:])
        self.assertEqual(list(dec.frames()), [env])

    def test_chinese_across_packets(self):
        env = {"msg_name": "over", "msg_data": {"name": "岭南贡队", "reason": "全图酷暑"}}
        frame = encode_frame(env)
        dec = FrameDecoder()
        # 逐字节喂入，制造中文多字节跨包
        for i in range(len(frame)):
            dec.feed(frame[i:i + 1])
            frames = list(dec.frames())
            if i < len(frame) - 1:
                self.assertEqual(frames, [])
            else:
                self.assertEqual(frames, [env])

    def test_invalid_prefix_raises(self):
        dec = FrameDecoder()
        dec.feed(b"abcde{}")
        with self.assertRaises(FramingError):
            list(dec.frames())

    def test_prefix_equals_utf8_byte_count_not_char_count(self):
        # 4 个中文字符 = 12 字节；前缀应记 12 而不是 4
        env = {"msg_name": "x", "msg_data": {"s": "荔枝争运"}}
        frame = encode_frame(env)
        body_len = int(frame[:5])
        self.assertEqual(body_len, len(frame) - 5)

    def _decode_raw(self, body_text):
        """绕过 encode_frame，直接喂入「5 位前缀 + 原样 body」模拟服务端字节流。"""
        raw = str(len(body_text.encode("utf-8"))).zfill(5).encode("ascii") + body_text.encode("utf-8")
        dec = FrameDecoder()
        dec.feed(raw)
        return list(dec.frames())

    def test_bare_numeric_key_is_quoted(self):
        # 服务端可能发出未加引号的数字键（如 {1001:"MOVE"}）；标准 json.loads 会直接拒绝。
        # 修复后应规整为字符串键，且能被解析。
        out = self._decode_raw('{"msg_name":"x","msg_data":{1001:"MOVE"}}')
        self.assertEqual(out, [{"msg_name": "x", "msg_data": {"1001": "MOVE"}}])
        # 键必须是字符串，不是 int
        self.assertEqual(list(out[0]["msg_data"].keys()), ["1001"])

    def test_bare_numeric_key_multiple_and_negative_and_float(self):
        out = self._decode_raw('{"msg_name":"x","msg_data":{1001:"MOVE", -3:"BOAT_RIGHT", 1.5:1}}')
        self.assertEqual(out[0]["msg_data"], {"1001": "MOVE", "-3": "BOAT_RIGHT", "1.5": 1})

    def test_numeric_values_not_affected(self):
        # 数值（在 ':' 右侧）不应被加引号；已有字符串键不动。
        env_text = '{"msg_name":"action","msg_data":{"round":12,"score":1001}}'
        out = self._decode_raw(env_text)
        self.assertEqual(out, [{"msg_name": "action", "msg_data": {"round": 12, "score": 1001}}])

    def test_numeric_key_pattern_inside_string_value_not_corrupted(self):
        # 字符串值里出现的 `,1001:` 不应被当作键处理。
        env_text = '{"msg_name":"x","msg_data":{"note":"a,1001:b"}}'
        out = self._decode_raw(env_text)
        self.assertEqual(out[0]["msg_data"]["note"], "a,1001:b")


if __name__ == "__main__":
    unittest.main()
