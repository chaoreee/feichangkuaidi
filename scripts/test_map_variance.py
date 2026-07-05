"""换图回归（项5）：在多张不同拓扑/距离的地图上跑 client vs mock，断言每张都能成功交付、不退赛。

初赛后官方地图会变（任务书 §2.2：路线边/距离/拓扑可变，机制/节点角色固定）。本脚本用三张图
验证客户端不依赖具体地图：
  - arena  : 初赛竞技地图(samples/map_config.json)，基准对照
  - sparse : 合成线性链(距离 18，无捷径/支路/水路)，验证最小拓扑下路由+突破+交付
  - large  : 合成线性链(距离 25)，验证帧预算门控/RUSH 前置动态触发随距离标度缩放

通过判据：mock 输出 "DELIVER_SUCCESS"（client 在 600 帧内完成交付）。
非交付(超时 TIME_LIMIT / 退赛)即判失败。

用法：python scripts/test_map_variance.py
"""

import os
import socket
import subprocess
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MOCK = os.path.join(_ROOT, "scripts", "mock_server.py")
_MAIN = os.path.join(_ROOT, "client", "main.py")
VARIANTS = ["arena", "sparse", "large"]
TIMEOUT = 90  # 单局墙钟上限（秒）


def free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def run_variant(variant):
    port = free_port()
    mock = subprocess.Popen(
        [sys.executable, _MOCK, "127.0.0.1", str(port), "600", "--variant=" + variant],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    # 等 mock 监听就绪：注意不能用 TCP connect 探测——mock 只 accept 一次，探测连接会消耗掉
    # 唯一的 accept 槽位，导致真正的 client 连不上。mock 在 bind+listen 后很快进入 accept，固定等待即可。
    time.sleep(1.5)
    if mock.poll() is not None:
        out = mock.stdout.read() if mock.stdout else ""
        return False, "mock 启动即退出: " + out[-300:]

    client = subprocess.Popen(
        [sys.executable, _MAIN, "1", "127.0.0.1", str(port)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        mock.wait(timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        mock.kill()
        client.kill()
        return False, "mock 超时未结束"
    try:
        client.wait(timeout=10)
    except subprocess.TimeoutExpired:
        client.kill()

    out = mock.stdout.read() if mock.stdout else ""
    delivered = "DELIVER_SUCCESS" in out
    retired = "retired=True" in out or "RETIRED" in out
    detail = ""
    for line in out.splitlines():
        if "DELIVER_SUCCESS" in line or "TIME_LIMIT" in line:
            detail = line.strip()
            break
    if delivered and not retired:
        return True, detail
    return False, ("未交付或退赛: " + detail) if detail else ("未交付: " + out[-400:])


def main():
    print("=" * 60)
    print("换图回归：client 必须在每张地图上成功交付、不退赛")
    print("=" * 60)
    all_ok = True
    for v in VARIANTS:
        print("\n>>> 变体 %s ..." % v, flush=True)
        ok, detail = run_variant(v)
        status = "PASS" if ok else "FAIL"
        print("[%s] %s — %s" % (status, v, detail), flush=True)
        if not ok:
            all_ok = False
    print("\n" + ("=" * 60))
    print("全部通过" if all_ok else "存在失败变体，请排查地图无关性")
    print("=" * 60)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
