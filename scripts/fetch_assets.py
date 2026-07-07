# -*- coding: utf-8 -*-
"""下载助手页「本地模式」所需资产：transformers.js 运行库 + Florence-2-large ONNX。

优先国内可直连的源（npmmirror / ModelScope），确保**无 VPN** 也能装。
已存在则跳过。任何一项失败都只让「本地模式」不可用，**不影响** ChatGPT 模式与其它功能。

用法：
    python scripts/fetch_assets.py
"""
import io
import os
import sys
import tarfile
import urllib.request

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENDOR = os.path.join(APP_DIR, "static", "vendor", "transformers")
MODEL_ROOT = os.path.join(APP_DIR, "models")
MODEL = os.path.join(MODEL_ROOT, "florence2-large")

# transformers.js（npm 包 @huggingface/transformers）的 npmmirror 元数据与 tarball。
# 从 tarball 里取出 dist/ 下的浏览器 ESM 包，放到 static/vendor/transformers/。
NPM_META = "https://registry.npmmirror.com/@huggingface/transformers"
# 助手页 import 的固定文件名（loadFlorence 里用 /vendor/transformers/transformers.min.js）
WANT_DIST = "transformers.min.js"

# Florence-2-large ONNX 在 ModelScope 的仓库（onnx-community 版镜像）
MODELSCOPE_REPO = "onnx-community/Florence-2-large"


def _get(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "ara-fetch/1.0"})
    return urllib.request.urlopen(req, timeout=timeout)


def fetch_transformers_js() -> bool:
    """从 npmmirror 拉 @huggingface/transformers tarball，提取 dist 到 VENDOR。"""
    target = os.path.join(VENDOR, WANT_DIST)
    if os.path.isfile(target) and os.path.getsize(target) > 10000:
        print(f"跳过（已存在）: {target}")
        return True
    os.makedirs(VENDOR, exist_ok=True)
    try:
        import json
        meta = json.load(_get(NPM_META, timeout=30))
        latest = meta["dist-tags"]["latest"]
        tarball = meta["versions"][latest]["dist"]["tarball"]
        # 强制走 npmmirror 域，避免回落到需要 VPN 的 registry.npmjs.org
        tarball = tarball.replace("registry.npmjs.org", "registry.npmmirror.com")
        print(f"下载 transformers.js v{latest}：{tarball}")
        raw = _get(tarball, timeout=120).read()
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tf:
            members = [m for m in tf.getmembers() if "/dist/" in m.name]
            for m in members:                       # 把整个 dist 摊平到 VENDOR
                data = tf.extractfile(m)
                if not data:
                    continue
                out = os.path.join(VENDOR, os.path.basename(m.name))
                with open(out, "wb") as f:
                    f.write(data.read())
        if os.path.isfile(target) and os.path.getsize(target) > 10000:
            print(f"  ✓ transformers.js 就位：{target}")
            return True
        print(f"[需手动] tarball 里没找到 {WANT_DIST}（包结构可能变了），"
              f"请从 https://www.npmmirror.com/package/@huggingface/transformers 手动取 dist 放到 {VENDOR}/")
        return False
    except Exception as e:
        print(f"[需手动] transformers.js 自动下载失败（{e}）。"
              f"可从 npmmirror 下载 @huggingface/transformers 的 dist/{WANT_DIST} 放到 {VENDOR}/")
        return False


def fetch_florence() -> bool:
    """用 ModelScope SDK 拉 Florence-2-large 到 MODEL；无 SDK/失败则给手动指引。"""
    if os.path.isdir(MODEL) and os.listdir(MODEL):
        print(f"跳过（已存在）: {MODEL}")
        return True
    os.makedirs(MODEL_ROOT, exist_ok=True)
    try:
        from modelscope import snapshot_download
        print(f"从 ModelScope 下载 {MODELSCOPE_REPO}（约 1.5GB，首次较慢）…")
        snapshot_download(MODELSCOPE_REPO, local_dir=MODEL)
        return bool(os.listdir(MODEL))
    except ImportError:
        print("[需手动] 未安装 modelscope。可 `pip install modelscope` 后重跑本脚本，"
              f"或从 https://modelscope.cn/models/{MODELSCOPE_REPO} 手动下载 ONNX 版到 {MODEL}/")
        return False
    except Exception as e:
        print(f"[需手动] Florence-2 自动下载失败（{e}）。"
              f"请从 https://modelscope.cn/models/{MODELSCOPE_REPO} 手动下载到 {MODEL}/")
        return False


def main() -> int:
    print("=== 助手页本地模式资产检查 ===")
    ok_js = fetch_transformers_js()
    ok_model = fetch_florence()
    if ok_js and ok_model:
        print("完成：本地模式已就绪。")
        return 0
    print("提示：本地模式暂不可用（见上「需手动」项），但 ChatGPT 模式与其它功能不受影响。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
