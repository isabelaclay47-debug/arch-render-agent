# ArchRenderAgent

**English · [中文](README.zh-CN.md)**

![License](https://img.shields.io/badge/license-MIT-blue)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)

**Turn a rough massing screenshot into a photorealistic architectural render — automatically, faithfully, and on your own ChatGPT or Gemini quota.**

ArchRenderAgent drives a Chrome tab you're already logged into and runs the full loop for you: understand the brief → write a professional prompt → generate → compare against your base image for tampering → refine. You stay in control: confirm the prompt before any credits are spent, mark up regions to fix by hand, steer with feedback, or export at any time.

> **A local, bring-your-own-ChatGPT tool.** It attaches to a Chrome running on *your* machine and uses *your* ChatGPT subscription to generate images — nothing is uploaded to a third‑party server and no account is shared. To let others use it, they clone this repo and run it on their own computer with their own ChatGPT login (so there is **no** shared public URL). Image generation needs an account that can create images on the ChatGPT web app (typically Plus/Pro).

---

## Why it's different

- **🎯 Faithful by design.** Every round is compared against your original base image. Building form, floor count, windows, straight lines and text are locked down — the model improves materials, light and entourage, not your geometry.
- **💸 Quota‑saving dual‑path iteration.** Local flaws are fixed by an *incremental edit on the previous render* (everything else kept pixel‑identical) instead of re‑rolling a full image every time. It only redraws from the base when the form actually drifts. Defects converge instead of reappearing.
- **🧭 Confirm gate before spending credits.** The AI first explains, in your language, what it understood, and shows an editable prompt. Approve or adjust — *then* it starts generating.
- **🗣️ Chinese in, English out.** You work in Chinese in the UI; the prompt actually sent to ChatGPT is English (image models are more reliable in English).
- **🖌️ Hands‑on region edits.** Mark exactly what to change with freehand, straight line, rectangle, polygon lasso, smear, or eraser — the AI edits only inside the mark and leaves everything else untouched.
- **🧱 A curated ArchViz prompt library** with precise material vocabulary (board‑formed concrete, Shou Sugi Ban, Corten, zinc standing seam…), lighting scenarios, camera guidance and categorized negative prompts — always topped with a non‑negotiable quality/faithfulness baseline.
- **🎨 Two image engines, your subscription.** Generate with **ChatGPT** or with **Gemini's nano‑banana** — both drive a browser you're logged into and use your own subscription, no API key. Text reasoning (understanding, prompts, faithfulness checks) always runs on ChatGPT.
- **🔍 Offline vision, no account.** The Prompt Assistant can read your image with a **local Ollama vision model** — fully offline, no account and no VPN — or with ChatGPT when you prefer.
- **🖼️ Local quality boost.** Final deliverables can be upscaled to 2K/4K/8K with a local super‑resolution model (Swin2SR) and de‑watermarked locally — offline, only on the final image.
- **🌐 Bilingual UI (中 / EN).** A persistent ZH/EN toggle translates the whole interface; your choice is remembered. Model‑facing prompts stay English regardless.
- **🛡️ Resilient.** Both engines auto‑recover when the web UI stalls: a generated image that hasn't finished decoding is no longer mistaken for a freeze, and genuinely stuck pages refresh and retry — one hiccup no longer kills the whole run.

> Note: model‑facing prompts are always English; the operator UI can switch between Chinese and English.

---

## Quick start

**Prerequisites:** Python 3.10+, Google Chrome, and a ChatGPT account that can generate images on the web app.

### Windows — one double‑click
Double‑click **`双击启动.bat`** ("start" launcher). It checks Python, installs dependencies, opens a dedicated Chrome, starts the server and opens http://127.0.0.1:5001. First run takes 1–3 minutes and asks you to **log into `chatgpt.com` once** in the Chrome window it opens (keep that window open, you can minimize it).
> No Python? The script opens the download page — install Python 3.10+ (tick **"Add Python to PATH"**), then double‑click again.

### macOS — one double‑click
Double‑click **`双击启动-Mac.command`** (if macOS blocks it the first time: right‑click → Open → Open). It sets everything up, opens Chrome for you to log into `chatgpt.com`, and launches the app.

### Linux / manual
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Launch a dedicated Chrome with the debug port, then log into chatgpt.com (keep it open):
google-chrome --remote-debugging-port=9333 --user-data-dir="$PWD/chrome-profile" \
  --no-first-run --no-default-browser-check https://chatgpt.com/

# In another terminal:
source .venv/bin/activate && python app.py   # open http://127.0.0.1:5001
```
> Playwright only *attaches* to your Chrome over CDP — no `playwright install` browser download needed.

---

## How to use

1. Describe what you want, upload a **base image** (kept faithful) and optional **reference images** (mood/material/light only). Pick quality, aspect ratio, and **how many images between check‑ins** (default: 1 — most economical).
2. **Confirm gate:** the AI paraphrases your intent and shows an editable prompt. Approve, or tweak it and let the AI re‑sync. (Genuine ambiguities are asked back first — none of this spends image credits.)
3. **Auto‑iterate:** generate → tamper/quality check vs. the base → *refine the previous render* or *redraw from base*. Pauses every N images for your review.
4. At each pause you can: leave feedback and continue, one‑click paste the AI's own review into the feedback box, open the **region editor** to mark and fix a spot, finish and export to Desktop, or stop early.
5. Every intermediate image and prompt is saved under `workspace/<timestamp>/`.

---

## How it works

A single **director chat** (one ChatGPT conversation) understands the brief, writes the prompt from an ArchiPrompt framework + a professional library, and after each render compares the output to your base image to catch tampering and drive revisions. Generation runs in a fresh chat each round; localized fixes are applied as incremental edits on the previous render, while a faithfulness check against the *original* base triggers a from‑scratch redraw whenever drift is detected. A fixed English baseline (don't alter the building, keep lines straight, maximize quality, no garbled text, categorized negatives) is appended to every generation instruction.

## FAQ

- **"Can't connect to the Chrome debug port"** — the dedicated Chrome (launched with `--remote-debugging-port=9333`) isn't running.
- **"Can't find the input box"** — that Chrome isn't logged into chatgpt.com, or a captcha is showing.
- **Generation is slow / never returns** — ChatGPT image generation takes 1–3 min each; if you're out of quota it never returns.
- **ChatGPT changed its UI** — update the `SEL` selectors at the top of `chatgpt_client.py`.

## License

[MIT](LICENSE) — free to use, modify and sell; keep the copyright notice.
