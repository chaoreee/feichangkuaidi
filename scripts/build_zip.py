"""打包提交 ZIP 并执行提交前自检（任务书 §10）。

产出 dist/gameclient.zip：ZIP 根目录直接含可执行 start.sh 与 client/ 源码（纯标准库、离线可跑）。
排除 tests/__pycache__/日志/样例/文档等非运行必需内容，保证提交包纯净。

用法：python3 scripts/build_zip.py    （提交环境用 python3；本机开发用 py）
自检不通过（结构类）返回非零。
"""

import os
import re
import stat
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
ZIP_NAME = "gameclient.zip"

# 允许的标准库顶层模块 + 客户端自有顶层包
STDLIB = {
    "socket", "json", "threading", "queue", "os", "sys", "time", "math", "heapq",
    "dataclasses", "argparse", "unittest", "collections", "statistics", "functools",
    "itertools", "typing", "io", "re", "enum", "abc", "copy", "datetime", "tempfile",
}
INTERNAL = {"config", "communication", "protocol", "core", "strategy", "logger", "utils"}

INSTALL_PAT = re.compile(r"\b(pip\s+install|npm\s+install|apt-get|yum\s+install|conda\s+install)\b")
IPV4_PAT = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")
IMPORT_PAT = re.compile(r"^\s*(?:from\s+([a-zA-Z_][\w.]*)\s+import|import\s+([a-zA-Z_][\w.]*))")


def _client_py_files():
    base = os.path.join(ROOT, "client")
    out = []
    for dirpath, _dirs, files in os.walk(base):
        if "__pycache__" in dirpath or os.sep + "tests" in dirpath + os.sep:
            continue
        for f in files:
            if f.endswith(".py"):
                full = os.path.join(dirpath, f)
                out.append((full, os.path.relpath(full, ROOT).replace(os.sep, "/")))
    return out


def build():
    os.makedirs(DIST, exist_ok=True)
    zip_path = os.path.join(DIST, ZIP_NAME)
    if os.path.exists(zip_path):
        os.remove(zip_path)
    files = _client_py_files()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # start.sh 置于 ZIP 根，标记可执行
        info = zipfile.ZipInfo("start.sh")
        info.external_attr = (stat.S_IFREG | 0o755) << 16
        info.compress_type = zipfile.ZIP_DEFLATED
        with open(os.path.join(ROOT, "start.sh"), encoding="utf-8") as fh:
            zf.writestr(info, fh.read())
        for full, arc in files:
            zf.write(full, arc)
    return zip_path, [arc for _f, arc in files]


def self_check(zip_path):
    """返回 (ok, results)：results 为 (level, item, detail)；level ∈ PASS/WARN/FAIL。"""
    results = []

    def add(level, item, detail=""):
        results.append((level, item, detail))

    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        bad = zf.testzip()
        add("PASS" if bad is None else "FAIL", "ZIP 可正常解压", bad or "")
        add("PASS" if "start.sh" in names else "FAIL", "根目录直接包含 start.sh")
        # 不套同名目录
        add("PASS" if not any(n.startswith("gameclient/") for n in names) else "FAIL", "未多套一层同名目录")
        # start.sh 可执行位
        info = zf.getinfo("start.sh") if "start.sh" in names else None
        mode = (info.external_attr >> 16) if info else 0
        add("PASS" if mode & 0o111 else "FAIL", "start.sh 具可执行权限", oct(mode))
        start_src = zf.read("start.sh").decode("utf-8") if info else ""
        # 3 参数
        ok_args = ('"$1"' in start_src and '"$2"' in start_src and '"$3"' in start_src) or "$@" in start_src
        add("PASS" if ok_args else "WARN", "start.sh 接收 3 个参数(playerId/host/port)")
        add("PASS" if "client/main.py" in names else "FAIL", "包含 client/main.py")

    # 源码扫描：第三方依赖 / 硬编码 / 安装命令
    third_party, hardcoded, installs = set(), [], []
    scan_files = [os.path.join(ROOT, "start.sh")] + [f for f, _ in _client_py_files()]
    for full in scan_files:
        with open(full, encoding="utf-8") as fh:
            text = fh.read()
        if INSTALL_PAT.search(text):
            installs.append(os.path.relpath(full, ROOT))
        if full.endswith(".py"):
            for line in text.splitlines():
                m = IMPORT_PAT.match(line)
                if m:
                    top = (m.group(1) or m.group(2) or "").split(".")[0]
                    if top and top not in STDLIB and top not in INTERNAL:
                        third_party.add(top)
                for ip in IPV4_PAT.findall(line):
                    if not line.strip().startswith("#"):
                        hardcoded.append("%s: %s" % (os.path.relpath(full, ROOT), ip))

    add("PASS" if not third_party else "FAIL", "无第三方依赖(纯标准库)", ",".join(sorted(third_party)))
    add("PASS" if not installs else "FAIL", "无现场安装命令", ",".join(installs))
    add("PASS" if not hardcoded else "WARN", "无硬编码 IP(不写死服务器地址)", "; ".join(hardcoded[:3]))

    ok = all(level != "FAIL" for level, _i, _d in results)
    return ok, results


def main():
    zip_path, arcs = build()
    print("built %s (%d client files)" % (zip_path, len(arcs)))
    ok, results = self_check(zip_path)
    print("\n=== 提交前自检（任务书 §10.7）===")
    for level, item, detail in results:
        mark = {"PASS": "[x]", "WARN": "[!]", "FAIL": "[ ]"}[level]
        print("%s %s %s" % (mark, item, ("— " + detail) if detail else ""))
    print("\n本地启动测试：./start.sh <playerId> <host> <port>（对 scripts/mock_server.py 验证；平台环境用 python3）")
    print("结果：%s" % ("通过" if ok else "存在 FAIL，请修复"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
