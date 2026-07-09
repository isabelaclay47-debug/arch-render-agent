# -*- coding: utf-8 -*-
"""本地 AI 后处理：Swin2SR 超分（画质/8K）+ LaMa 去水印（去 Gemini nano-banana 水印）。
全部用 onnxruntime 本地跑、离线、免 API key。模型按需下载到 models/；未就绪则优雅跳过。

对外主入口：
  enhance_file(path, quality="1k", dewatermark=False, engine="chatgpt", log=print)
    就地把 path 处理成目标画质（并按需去水印），返回 dict 说明做了什么。
"""
import os
import threading

import numpy as np

APP_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(APP_DIR, "models")

# 模型：hf-mirror 国内友好源在前，huggingface 官方兜底
MODELS = {
    "swin2sr_x4": {
        "file": "swin2sr_realworld_x4.onnx",
        "urls": [
            "https://hf-mirror.com/Xenova/swin2SR-realworld-sr-x4-64-bsrgan-psnr/resolve/main/onnx/model.onnx",
            "https://huggingface.co/Xenova/swin2SR-realworld-sr-x4-64-bsrgan-psnr/resolve/main/onnx/model.onnx",
        ],
        "size": 52772645,
    },
    "lama": {
        "file": "lama_fp32.onnx",
        "urls": [
            "https://hf-mirror.com/Carve/LaMa-ONNX/resolve/main/lama_fp32.onnx",
            "https://huggingface.co/Carve/LaMa-ONNX/resolve/main/lama_fp32.onnx",
        ],
        "size": 208044816,
    },
}

# 画质档位 → 目标长边像素（0 = 原生、不放大）
QUALITY_TARGET = {"1k": 0, "2k": 2048, "4k": 3840, "8k": 7680}

_sessions = {}
_load_lock = threading.Lock()


def _model_path(key):
    return os.path.join(MODELS_DIR, MODELS[key]["file"])


def model_ready(key):
    p = _model_path(key)
    return os.path.isfile(p) and os.path.getsize(p) > MODELS[key]["size"] * 0.9


def all_ready(need_lama=True):
    return model_ready("swin2sr_x4") and (model_ready("lama") if need_lama else True)


def _session(key):
    import onnxruntime as ort
    with _load_lock:
        if key not in _sessions:
            _sessions[key] = ort.InferenceSession(
                _model_path(key), providers=["CPUExecutionProvider"])
        return _sessions[key]


# ---------------- Swin2SR ×4 超分（分块 + 余弦羽化，防爆内存/防拼缝）----------------
def _sr_x4_tiled(bgr, tile=224, overlap=24, log=print):
    import cv2
    sess = _session("swin2sr_x4")
    scale = 4
    H, W = bgr.shape[:2]
    out = np.zeros((H * scale, W * scale, 3), np.float32)
    acc = np.zeros((H * scale, W * scale, 1), np.float32)
    step = max(16, tile - overlap)
    ys = list(range(0, max(1, H - overlap), step))
    xs = list(range(0, max(1, W - overlap), step))
    total = len(ys) * len(xs)
    done = 0
    for y in ys:
        for x in xs:
            y1, x1 = y, x
            y2, x2 = min(y + tile, H), min(x + tile, W)
            patch = bgr[y1:y2, x1:x2]
            ph, pw = patch.shape[:2]
            rgb = cv2.cvtColor(patch, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
            inp = np.transpose(rgb, (2, 0, 1))[None]
            res = sess.run(None, {"pixel_values": inp})[0][0]
            res = np.clip(res, 0, 1).transpose(1, 2, 0)[:, :, ::-1]  # →BGR, ×4
            # 余弦羽化窗
            ov = overlap * scale
            wy = np.ones((ph * scale, 1), np.float32)
            wx = np.ones((1, pw * scale), np.float32)
            if ov > 0:
                r = np.linspace(0, 1, ov, dtype=np.float32)
                if y1 > 0:
                    wy[:ov, 0] *= r
                if y2 < H:
                    wy[-ov:, 0] *= r[::-1]
                if x1 > 0:
                    wx[0, :ov] *= r
                if x2 < W:
                    wx[0, -ov:] *= r[::-1]
            w = (wy @ wx)[..., None]
            oy, ox = y1 * scale, x1 * scale
            out[oy:oy + ph * scale, ox:ox + pw * scale] += res[:ph * scale, :pw * scale] * w
            acc[oy:oy + ph * scale, ox:ox + pw * scale] += w
            done += 1
            log(f"超分中… {done}/{total} 块")
    acc[acc == 0] = 1
    return np.clip(out / acc, 0, 1) * 255


def upscale(bgr, target_long_edge, log=print):
    """先 Swin2SR ×4 补真实细节，再 Lanczos 缩到目标长边。target=0 时原样返回。"""
    import cv2
    if not target_long_edge:
        return bgr
    H, W = bgr.shape[:2]
    if max(H, W) >= target_long_edge:      # 已够大：直接高质量缩放，不必超分
        s = target_long_edge / max(H, W)
        return cv2.resize(bgr, (round(W * s), round(H * s)), interpolation=cv2.INTER_LANCZOS4)
    sr = _sr_x4_tiled(bgr, log=log)        # ×4
    Hs, Ws = sr.shape[:2]
    s = target_long_edge / max(Hs, Ws)
    interp = cv2.INTER_AREA if s < 1 else cv2.INTER_LANCZOS4
    return cv2.resize(sr.astype(np.uint8), (round(Ws * s), round(Hs * s)), interpolation=interp)


# ---------------- LaMa 去水印（Gemini nano-banana 右下角 ✦）----------------
def _gemini_wm_mask(H, W):
    """Gemini 生成图水印在右下区域（实测 ~中心 0.89W,0.84H 的大块半透明 ✦）。
    给一个宽松矩形 mask 交给 LaMa 智能补全——LaMa 对大块生成式补全很稳，不像传统 inpaint 会糊。"""
    import cv2
    m = np.zeros((H, W), np.uint8)
    cx, cy = int(0.89 * W), int(0.845 * H)
    hw, hh = int(0.075 * W), int(0.085 * H)
    cv2.rectangle(m, (cx - hw, cy - hh), (min(W, cx + hw), min(H, cy + hh)), 255, -1)
    return m


def dewatermark(bgr, log=print):
    """LaMa 修补掉 Gemini 水印区域。模型未就绪则原样返回。"""
    import cv2
    sess = _session("lama")
    H, W = bgr.shape[:2]
    mask = _gemini_wm_mask(H, W)
    # LaMa 输入需为 8 的倍数；缩到不超过 1024 长边处理再贴回，省内存
    proc = 1024
    s = min(1.0, proc / max(H, W))
    ph, pw = int(round(H * s)), int(round(W * s))
    ph8, pw8 = (ph + 7) // 8 * 8, (pw + 7) // 8 * 8
    img_r = cv2.resize(bgr, (pw8, ph8), interpolation=cv2.INTER_AREA)
    msk_r = cv2.resize(mask, (pw8, ph8), interpolation=cv2.INTER_NEAREST)
    rgb = cv2.cvtColor(img_r, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    img_in = np.transpose(rgb, (2, 0, 1))[None]
    msk_in = (msk_r > 0).astype(np.float32)[None, None]
    out = sess.run(None, {"image": img_in, "mask": msk_in})[0][0]
    out = np.clip(out.transpose(1, 2, 0), 0, 1)[:, :, ::-1] * 255  # →BGR
    out = cv2.resize(out.astype(np.uint8), (W, H), interpolation=cv2.INTER_LANCZOS4)
    # 只把 mask 区域贴回原图，mask 外保持原样（避免整图被 LaMa 轻微改动）
    m3 = cv2.merge([mask, mask, mask]) > 0
    res = bgr.copy()
    res[m3] = out[m3]
    log("已去除 Gemini 水印区域")
    return res


# ---------------- 对外主入口 ----------------
def enhance_file(path, quality="1k", dewatermark_wm=False, log=print):
    """就地增强：按需去水印 + 按档位超分。返回做了什么的说明。缺模型则跳过对应步骤。"""
    import cv2
    result = {"dewatermark": False, "upscaled_to": None, "skipped": []}
    target = QUALITY_TARGET.get(quality, 0)
    if not dewatermark_wm and not target:
        return result                       # 1k 原生 + 不去水印：什么都不用做
    img = cv2.imread(path)
    if img is None:
        result["skipped"].append("读图失败")
        return result

    if dewatermark_wm:
        if model_ready("lama"):
            try:
                img = dewatermark(img, log=log); result["dewatermark"] = True
            except Exception as e:
                result["skipped"].append(f"去水印失败:{e}")
        else:
            result["skipped"].append("去水印模型未下载")

    if target:
        if model_ready("swin2sr_x4"):
            try:
                img = upscale(img, target, log=log)
                result["upscaled_to"] = f"{img.shape[1]}x{img.shape[0]}"
            except Exception as e:
                result["skipped"].append(f"超分失败:{e}")
        else:
            result["skipped"].append("超分模型未下载")

    cv2.imwrite(path, img)
    return result
