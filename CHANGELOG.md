# Changelog

All notable changes to **ArchRenderAgent**. The app UI stays bilingual (中 / EN); this file and the GitHub‑facing docs are English.

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
