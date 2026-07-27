# Changelog

All notable changes to **ArchRenderAgent**. The app UI stays bilingual (中 / EN); this file and the GitHub‑facing docs are English.

## [1.2.6] — 2026-07-27
- **New (fidelity‑check summary at a glance):** every process‑image card now shows a one‑line summary between the round badge and the collapsible "Fidelity‑check details" — a colored **status light** (Tampered / Needs refinement / Minor flaws / Passed / Check incomplete / Checked), a **severity tally** (`Severe×n Medium×n Minor×n`), and the one‑sentence verdict. Previously the card's summary line relied on the director emitting a `<结论>` tag; when it didn't (common), the line was blank and the whole result was buried inside the `<details>`. The summary is now **derived client‑side from the `<分析>` list** — a deterministic count of `[严重/中等/轻微]` tags (tolerant of full‑width `【】`) — with the verdict sentence falling back to the first analysis line when `<结论>` is missing. i18n gains 10 `EXACT` entries (incl. `检查未完成`) so the status light never leaks Chinese in English mode; `test_i18n_dynamic.py` pins the new runtime strings. Full suite 180 green.

## Lessons learned (do not repeat)
- **Derive UI state from the stable data source, not the flaky one.** The summary line depended on the model's *optional* `<结论>` tag and silently went blank whenever the model skipped it. The `<分析>` list is a fixed `[severity] description` format — always present and countable — so the status light is computed from that, and `<结论>` is demoted to a secondary display detail. Same principle as the `aria‑busy` completion fix: trust the deterministic signal, not the one the model may or may not produce.

## [1.2.5] — 2026-07-27
- **Fix (Gemini director — the "it errors on the very first prompt" bug):** in Gemini‑does‑everything mode the director's text turn (understanding / first prompt, and every fidelity check) was being **killed by a mid‑generation page reload**. `gemini_client._wait_reply_done`'s phase‑1 stall guard reloaded the page after `RELOAD_INTERVAL` seconds of "no reply container yet" — but during Gemini **Pro's thinking phase** there is no stop button and often no `aria-busy` element to detect, so a long think looked like a hang. Reloading a thinking Gemini turns the answer into an empty **"你已让系统停止这条回答" (you stopped this response)**, which then failed to parse → `导演对话两次都没给出可用的英文提示词` at startup, and empty QC analysis mid‑task. The text path now **never auto‑reloads a *live* page** (a live‑but‑slow page = Gemini thinking; only a genuinely dead page is recovered, with a bounded `AUTO_RELOAD_CAP`), requires the reply to be **non‑empty and stable** before returning, explicitly detects the stop‑message via `_looks_stopped()` and raises so `send()` retries cleanly instead of returning it. Mirrors the protections `chatgpt_client` already had. Root cause confirmed from `logs/gemini_dump_20260727_094829.html`.
- **Fix (fidelity check showed "（未解析出分析内容）"):** when the director's reply couldn't be parsed into the structured `<分析>` tags, the result card showed a useless placeholder. It now falls back to the director's **raw reply** (`prompt_engine.analysis_for_display`), so the architect always sees the actual words. `parse_director_reply` also tolerates full‑width `＜标签＞` brackets.
- **Fix (English UI — "make it comprehensive"):** result‑card labels and status‑log lines that are rendered dynamically by JS (so the static‑HTML i18n scan never saw them) leaked Chinese in English mode — e.g. `本轮后的提示词`, `Gemini 已是「…」，无需切换。`, engine/connect/reconnect logs. Added ~20 `EXACT` entries and ~23 `DYNAMIC` patterns; a new `test_i18n_dynamic.py` pins the runtime strings so they can't regress.
- Since 1.2.4 (also folded into this release): a new **"detail · must‑preserve" reference role** (multi‑reference, strong‑fidelity single output) with per‑image QC; the Gemini "director empty reply" diagnostics (DOM dumps) and the `aria‑busy` completion‑detection fix; and the roles switch back in the UI.

## Lessons learned (do not repeat)
- **Reloading the page is destructive for a *text* turn.** For image generation, refreshing a stuck tab and redrawing is a valid recovery; for text reasoning it (1) interrupts an in‑progress "thinking" turn — which Gemini records as *you stopped this response* — and (2) throws away the conversation context. Gate any stall‑reload on `expect_image`, and treat a **live** page as "still working," not "hung."
- **A "stopped/interrupted" placeholder is not an answer.** `你已让系统停止这条回答` parses to empty and cascades into misleading "prompt missing / no analysis" errors upstream. Detect these sentinel replies explicitly and retry, never return them.
- **The static‑HTML i18n scan misses JS‑rendered strings.** Anything a `<script>` composes at runtime (result cards, status‑log lines from the backend) is invisible to a DOM‑text scan of the template. Cover them with runtime‑string tests, not just the static sweep.

## [1.2.4] — 2026-07-21
- **Fix (image capture):** generating an image could crash a whole session with `SecurityError: Failed to execute 'toDataURL' on 'HTMLCanvasElement': Tainted canvases may not be exported`. Gemini/ChatGPT generated images are served from a **cross‑origin CDN** (`*.googleusercontent.com`) and painted into an `<img>` without `crossOrigin`, so the in‑page fallback tainted the canvas and `toDataURL()` threw — and the exception escaped `download_last_image`, turning a *recoverable* "couldn't grab the image" into a fatal error. Image bytes are now pulled with Playwright's own `page.request` (browser‑process fetch that shares the login cookies and is subject to neither CORS nor canvas taint); only `blob:` / `data:` URLs keep an in‑page path. Any failure now degrades to a clean retry instead of crashing. Applies to both `gemini_client.py` and `chatgpt_client.py`.

## Lessons learned (do not repeat)
- **Never read a cross‑origin image's pixels inside the page's JS sandbox.** In‑page `fetch(img.src)` is blocked by CORS and `canvas.drawImage(img)+toDataURL()` throws on a tainted canvas. Use the driver's own request context (`page.request.get`) — it runs in the browser process, carries the session cookies, and bypasses both restrictions. The canvas fallback was pure liability: it *always* threw for cross‑origin images and was redundant for same‑origin/blob ones.
- **A helper with a `-> bool` failure contract must not let exceptions escape.** `download_last_image` was supposed to return `False` on failure (the caller turns that into a graceful retry). An unhandled in‑page JS throw bypassed that contract and killed the round. Wrap the whole body so failures return `False`.

## [1.2.3] — 2026-07-16
- **Fix (macOS / Linux):** the in‑app "Launch Chrome to sign in" button (`/api/launch_chrome`) could not find Chrome on native macOS/Linux — it only knew Windows and WSL paths — so the button silently did nothing. It now detects `/Applications/Google Chrome.app` and `google-chrome` / `chromium` on `PATH`. Windows behavior is unchanged.

## [1.2.2] — 2026-07-16
- **Consistency:** the Prompt Assistant page now shows the same dismissible "can't reach the internet" modal as the main page. Offline local‑vision mode needs no network and stays quiet.

## [1.2.1] — 2026-07-16
- **Fix:** the connectivity check falsely reported "can't connect" when a proxy/VPN in *system‑proxy mode* was active. The probe now tunnels through the system proxy and completes a TLS handshake — the same path the browser uses — so there are no more false alarms.
- **New:** a clear, dismissible modal prompts you when the internet isn't reachable, with one click to configure the VPN or test the connection.

## [1.2.0] — 2026-07-16 · superseded by 1.2.1 (GitHub Release removed)
- First proxy‑aware connectivity check and the source + native release pipeline (GitHub Actions).
- This build's probe used only an HTTP `CONNECT` and could false‑positive; fixed in 1.2.1. The Release was deleted to keep the list clean — **this entry is the trace**.

## Lessons learned (do not repeat)
- **A connectivity probe must use the same path the real client uses.** The original probe opened a raw TCP socket to `chatgpt.com:443`, which ignores the system proxy. Behind a system‑proxy VPN (e.g. 土星通讯 in rule mode) the raw socket is blocked while the browser — which honors the system proxy — works fine, producing a false "can't connect". Probe *through* the proxy, like the browser does.
- **`HTTP CONNECT 200` does not mean the upstream host is reachable.** Many proxies return `200 Connection established` for *any* host (even nonexistent ones) before checking the upstream. Confirm reachability with a TLS handshake to the real host, not the `CONNECT` status alone.
- **Run the full test suite before tagging a release.** The false‑positive above was caught by an existing test (`test_probe_never_raises_on_bad_host`) only *after* 1.2.0 had already been published. Tag after green tests, never before.
