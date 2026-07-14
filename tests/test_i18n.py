"""Bilingual UI coverage for the two browser pages."""

import re
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HAN = re.compile(r"[\u3400-\u9fff]")


class _VisibleChinese(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hidden_depth = 0
        self.values: set[str] = set()

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden_depth += 1
        for name, value in attrs:
            if name in {"title", "placeholder", "aria-label", "alt"} and value and HAN.search(value):
                self.values.add(" ".join(value.split()))

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.hidden_depth:
            self.hidden_depth -= 1

    def handle_data(self, data):
        if self.hidden_depth:
            return
        value = " ".join(data.split())
        if value and HAN.search(value):
            self.values.add(value)


def test_both_pages_load_the_shared_language_layer():
    for page in ("index.html", "helper.html"):
        html = (ROOT / "templates" / page).read_text(encoding="utf-8")
        assert '<script src="/static/i18n.js"></script>' in html


def test_visible_static_chinese_has_an_english_dictionary_entry():
    dictionary = (ROOT / "static" / "i18n.js").read_text(encoding="utf-8")
    missing: dict[str, list[str]] = {}
    for page in ("index.html", "helper.html"):
        parser = _VisibleChinese()
        parser.feed((ROOT / "templates" / page).read_text(encoding="utf-8"))
        uncovered = sorted(value for value in parser.values if value not in dictionary)
        if uncovered:
            missing[page] = uncovered
    assert not missing, missing


def test_language_choice_is_top_level_persistent_and_used_for_inserted_presets():
    i18n = (ROOT / "static" / "i18n.js").read_text(encoding="utf-8")
    index = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    helper = (ROOT / "static" / "helper.js").read_text(encoding="utf-8")

    assert 'const STORAGE_KEY = "archrender.lang"' in i18n
    assert 'position:fixed;top:12px;right:16px' in i18n
    assert 'data-lang-choice="zh"' in i18n
    assert 'data-lang-choice="en"' in i18n
    assert "I18N.t(text)" in index
    assert "I18N.t(PRESETS[+el.value][1])" in helper


def test_flask_serves_both_pages_and_the_language_asset():
    import app as app_module

    client = app_module.app.test_client()
    for route in ("/", "/helper"):
        response = client.get(route)
        assert response.status_code == 200
        assert b'/static/i18n.js' in response.data

    script = client.get("/static/i18n.js")
    assert script.status_code == 200
    assert b"archrender.lang" in script.data
