#!/usr/bin/env python3
"""make_release.py —— 打包 Dispatcher 公众试用分发包（不含任何密钥/真实数据）。

安全设计（务必遵守）：
  - 只打包 `git ls-files` 列出的受控文件 + 本脚本动态生成的干净 .env；
  - **绝不**包含仓库根的 `.env`（含真 key）、`data/`（含真实数据与密钥）、`logs/`、`.venv/`、`.git/`；
  - 打包后**强制密钥扫描**：发现 32 位 hex / sk- / AMAP 真值 / 手机号以外的敏感串即中止，不产出包；
  - 自动写入版本号、生成 SHA256 校验和。

用法：
  python3 scripts/make_release.py                # 产出到 dist/
  python3 scripts/make_release.py --version v0.2 # 指定版本标签
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(BASE, "dist")

# 敏感模式：打包产物中绝不允许出现
SECRET_PATTERNS = {
    "32位hex(高德key格式)": re.compile(r"\b[0-9a-f]{32}\b"),
    "sk-密钥": re.compile(r"\bsk-[A-Za-z0-9._-]{10,}"),
    "AMAP真值": re.compile(r"AMAP_(?:JS_KEY|SECURITY_CODE|WEB_KEY)=\s*[0-9a-f]{16,}"),
    "Where2Go密钥": re.compile(r"WHERE2GO_AMAP"),
    "私钥块": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "内网IP": re.compile(r"\b192\.168\.\d+\.\d+\b"),
    "三亚真实坐标": re.compile(r"\b18\.6[0-9]{2,},?\s*11[0-9]\."),
    "演示口令真值": re.compile(r"za2tdoed"),
}
# 允许的"假阳性"白名单（示例占位、文档说明），命中则跳过
ALLOW_SNIPPETS = ("your_amap", "示例", "e.g.", "PLACEHOLDER", "粘贴群机器人")


def run(cmd, cwd=BASE):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=True).stdout


def scan_secrets(path: str) -> list[tuple[str, str, str]]:
    """扫描一个文件或目录树，返回命中列表 [(文件, 模式名, 片段)]。"""
    hits = []
    files = []
    if os.path.isdir(path):
        for root, _, fns in os.walk(path):
            for fn in fns:
                files.append(os.path.join(root, fn))
    else:
        files = [path]
    for fp in files:
        try:
            txt = open(fp, encoding="utf-8").read()
        except (UnicodeDecodeError, OSError):
            continue  # 二进制文件跳过（包里不应有）
        for name, pat in SECRET_PATTERNS.items():
            for m in pat.finditer(txt):
                frag = m.group(0)
                line_ctx = txt[max(0, m.start() - 20):m.end() + 20]
                if any(a.lower() in line_ctx.lower() for a in ALLOW_SNIPPETS):
                    continue
                hits.append((os.path.relpath(fp, path if os.path.isdir(path) else os.path.dirname(path)), name, frag[:16]))
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="v0.2", help="版本标签，用于包名")
    ap.add_argument("--no-zip", action="store_true", help="只出 tar.gz，不出 zip")
    args = ap.parse_args()

    ver = args.version.strip().lstrip("v")
    name = f"dispatcher-demo-v{ver}"

    # ---------- 1. 收集要打包的文件 ----------
    tracked = [f for f in run(["git", "ls-files"]).splitlines() if f.strip()]
    # 必须存在的关键文件
    must = ["Dockerfile", "docker-compose.yml", ".env.example", "start.sh", "start.bat",
            "stop.sh", "stop.bat", "INSTALL.md", "USER_GUIDE.md", "LICENSE"]
    missing = [m for m in must if m not in tracked and not os.path.exists(os.path.join(BASE, m))]
    if missing:
        print(f"✗ 缺少必要文件（先创建并 git add）：{missing}")
        return 1

    # 排除清单（双保险，即使被 git 追踪也不打进公众包）
    #   .env           —— 含真 key/口令
    #   data/ logs/    —— 真实运营数据、密钥、备份
    #   docs/          —— 内部开发文档（含内网 IP、演示口令、决策、Where2Go key 来源等）
    #   deploy/        —— 云服务器部署脚本，本地试用包不需要
    #   make_release.py—— 开发者打包工具（其正则字符串会触发自身扫描，且用户用不到）
    #   .gitignore/.dockerignore —— 开发用，公众包无需
    EXCLUDE = {".env", ".gitignore", ".dockerignore", "scripts/make_release.py"}
    EXCLUDE_PREFIX = ("data/", "logs/", ".venv/", "dist/", "docs/", "deploy/")
    pack_files = [f for f in tracked if f not in EXCLUDE
                  and not f.startswith(EXCLUDE_PREFIX)]

    # ---------- 2. 暂存目录 ----------
    stage = os.path.join("/tmp", name)
    if os.path.exists(stage):
        shutil.rmtree(stage)
    os.makedirs(stage)
    for f in pack_files:
        src = os.path.join(BASE, f)
        if not os.path.exists(src):
            continue
        dst = os.path.join(stage, f)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)

    # ---------- 3. 生成干净 .env（演示模式开，无 key）----------
    env_dst = os.path.join(stage, ".env")
    shutil.copy2(os.path.join(BASE, ".env.example"), env_dst)
    # 把 .env.example 的占位行替换为可用默认（DEMO_MODE=1）
    txt = open(env_dst, encoding="utf-8").read()
    if "DEMO_MODE" in txt:
        txt = re.sub(r"^DEMO_MODE=.*$", "DEMO_MODE=1", txt, flags=re.M)
    else:
        txt += "\nDEMO_MODE=1\n"
    open(env_dst, "w", encoding="utf-8").write(txt)

    # ---------- 4. .bat 转 CRLF（Windows 兼容）----------
    for fn in os.listdir(stage):
        if fn.endswith(".bat"):
            p = os.path.join(stage, fn)
            d = open(p, "rb").read().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            open(p, "wb").write(d)

    # .sh 可执行位
    for fn in ("start.sh", "stop.sh", "run.sh", "deploy/cloud-deploy.sh", "scripts/backup_db.py", "scripts/reset_demo.py"):
        p = os.path.join(stage, fn)
        if os.path.exists(p):
            os.chmod(p, 0o755)

    # ---------- 5. 写版本标记 ----------
    with open(os.path.join(stage, "VERSION"), "w") as f:
        f.write(f"{ver}\n")

    # ---------- 6. 密钥扫描门禁（在打包前）----------
    hits = scan_secrets(stage)
    if hits:
        print("✗✗✗ 打包中止：暂存目录检测到疑似密钥，禁止发布！")
        for h in hits:
            print("   ", h)
        print(f"\n暂存目录保留供排查：{stage}")
        return 2
    print("✓ 密钥扫描通过：暂存目录无任何 key/密钥泄漏")

    # ---------- 7. 打包 ----------
    os.makedirs(DIST, exist_ok=True)
    tgz = os.path.join(DIST, f"{name}.tar.gz")
    with tarfile.open(tgz, "w:gz") as tar:
        tar.add(stage, arcname=name)

    artifacts = [tgz]
    if not args.no_zip:
        zp = os.path.join(DIST, f"{name}.zip")
        with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
            for root, _, fns in os.walk(stage):
                for fn in fns:
                    full = os.path.join(root, fn)
                    z.write(full, os.path.relpath(full, os.path.dirname(stage)))
        artifacts.append(zp)

    # ---------- 8. 产物再扫一遍（解压态）+ SHA256 ----------
    print("\n=== 产物校验 ===")
    lines = []
    for a in artifacts:
        with open(a, "rb") as f:
            sha = hashlib.sha256(f.read()).hexdigest()
        size = os.path.getsize(a)
        lines.append(f"{sha}  {os.path.basename(a)}")
        print(f"{os.path.basename(a)}  {size/1024:.0f} KB  sha256={sha[:16]}…")

    # 解包复扫
    check_dir = os.path.join("/tmp", name + "-check")
    if os.path.exists(check_dir):
        shutil.rmtree(check_dir)
    os.makedirs(check_dir)
    with tarfile.open(tgz, "r:gz") as tar:
        tar.extractall(check_dir)
    hits2 = scan_secrets(check_dir)
    if hits2:
        print("✗ 产物解压后仍检出密钥，删除产物：", hits2)
        for a in artifacts:
            os.remove(a)
        return 3
    print("✓ 产物解压复扫通过：无密钥")

    # 确认包里确实没有 .env(真) 和 data
    extracted = os.path.join(check_dir, name)
    bad = []
    if os.path.exists(os.path.join(extracted, "data")):
        bad.append("data/ 竟被打进包")
    envp = os.path.join(extracted, ".env")
    if os.path.exists(envp):
        c = open(envp, encoding="utf-8").read()
        if re.search(r"AMAP_JS_KEY=\s*[0-9a-f]{16,}", c):
            bad.append(".env 含真 key")
    if bad:
        print("✗", bad)
        return 4
    print("✓ 包结构安全：无 data/、.env 不含真 key")

    # ---------- 9. 写校验和文件 ----------
    sha_file = os.path.join(DIST, f"{name}.SHA256")
    with open(sha_file, "w") as f:
        f.write("\n".join(lines) + "\n")

    print(f"\n✅ 打包完成：")
    for a in artifacts:
        print(f"   {a}")
    print(f"   {sha_file}")
    print(f"\n暂存目录：{stage}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
