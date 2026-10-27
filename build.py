#!/usr/bin/env python3
"""Build the dapple.ie website.

Edit the site in src/site.html (content and design) and src/pages.json
(page addresses, titles, descriptions, form key), then run:

    python3 build.py

That writes one ready-to-publish page per address (index.html,
pattern/index.html, ...), plus 404.html and sitemap.xml. Each page is also
"pre-rendered": a plain-HTML copy of its content is baked in so Google and
link previews can read it without running JavaScript. Pre-rendering needs
Playwright (pip install playwright && playwright install chromium); without
it the pages still work, they just skip that step.
"""
import functools
import html
import json
import os
import re
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "src")
cfg = json.load(open(os.path.join(SRC, "pages.json"), encoding="utf-8"))
body = open(os.path.join(SRC, "site.html"), encoding="utf-8").read()
SITE = cfg["site"].rstrip("/")
PAGES = cfg["pages"]
MARK = "<!--PRERENDER-->"


def head(page, noindex=False):
    e = lambda s: html.escape(s, quote=True)
    routes = {p["id"]: p["path"] for p in PAGES}
    titles = {p["id"]: p["title"] for p in PAGES}
    url = SITE + page["path"]
    noindex = noindex or page.get("noindex", False)  # e.g. the client login page: kept out of search results
    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(page["title"])}</title>
<meta name="description" content="{e(page["description"])}">
{'<meta name="robots" content="noindex">' if noindex else f'<link rel="canonical" href="{e(url)}">'}
<meta property="og:type" content="website">
<meta property="og:site_name" content="Dapple">
<meta property="og:title" content="{e(page["title"])}">
<meta property="og:description" content="{e(page["description"])}">
<meta property="og:url" content="{e(url)}">
<link rel="icon" type="image/png" href="/assets/favicon.png">
<link rel="preload" href="/assets/archivo-latin.woff2" as="font" type="font/woff2" crossorigin>
<link rel="preload" href="/assets/b8228762-95c7-4845-9ab0-efac643f4cd8.woff2" as="font" type="font/woff2" crossorigin>
<style>x-dc{{display:none}} #prerender{{visibility:hidden}} html:not([data-fonts]) #dc-root{{visibility:hidden}}
html:not([data-fonts]), html:not([data-fonts]) body{{background:#171717}}</style>
<script>
// The page shows only once its fonts are in (or after 1.5s at most), so a refresh never draws the text in a
// stand-in font and then re-wraps it. The pre-rendered copy is for search engines and is never shown: it is a
// finished snapshot, so showing it and then swapping in the live page would replay the hero's animations.
// Until then the screen is the heroes' charcoal, not the light page colour, so there's no white flash.
// The runtime adds the font rules again when it draws the page, and the browser loads them afresh once the
// page's text is laid out, so this waits for that load to start and then to finish.
(function () {{
  var show = function () {{ document.documentElement.setAttribute('data-fonts', ''); }};
  if (!document.fonts || !document.fonts.addEventListener) return show();
  setTimeout(show, 1500);
  var started = function () {{
    document.fonts.removeEventListener('loading', started);
    document.fonts.ready.then(function () {{ requestAnimationFrame(show); }}, show);
  }};
  document.addEventListener('DOMContentLoaded', function () {{ document.fonts.addEventListener('loading', started); }});
}})();
window.DAPPLE_FORM_KEY = {json.dumps(cfg.get("formAccessKey", ""))};
window.DAPPLE_LINKEDIN = {json.dumps(cfg.get("linkedin", ""))};
window.DAPPLE_DASHBOARD_URL = {json.dumps(cfg.get("dashboardUrl", ""))};
window.DAPPLE_ROUTES = {json.dumps(routes)};
window.DAPPLE_TITLES = {json.dumps(titles)};
window.__resources = {{
  "https://unpkg.com/react@18.3.1/umd/react.production.min.js": "/assets/react.production.min.js",
  "https://unpkg.com/react-dom@18.3.1/umd/react-dom.production.min.js": "/assets/react-dom.production.min.js"
}};
window.dapplePageFromPath = function () {{
  var p = location.pathname.replace(/index\\.html$/, "");
  if (p.slice(-1) !== "/") p += "/";
  for (var id in window.DAPPLE_ROUTES) if (window.DAPPLE_ROUTES[id] === p) return id;
  return "home";
}};
window.dappleSetPage = function (id, push) {{
  var path = window.DAPPLE_ROUTES[id] || "/";
  if (push && location.pathname !== path) history.pushState({{}}, "", path);
  if (window.DAPPLE_TITLES[id]) document.title = window.DAPPLE_TITLES[id];
}};
</script>
<script src="/assets/dc-runtime.js"></script>
</head>
"""


def out_path(page):
    rel = page["path"].strip("/")
    return os.path.join(ROOT, rel, "index.html") if rel else os.path.join(ROOT, "index.html")


def inert(src):
    # The page markup for all seven pages sits in <x-dc>. Left as live HTML, the browser would download every
    # page's images and videos on every visit, so everything after <helmet> (which holds the styles and fonts,
    # and must stay live) goes in an inert <template>. The runtime reads x-dc's innerHTML, so it is handed the
    # same text it would have read.
    src = src.replace("</helmet>", '</helmet>\n<template id="dc-tpl">', 1)
    return src.replace("</x-dc>", "</template>\n</x-dc>\n<script>(function () {\n"
                       "  var dc = document.querySelector('x-dc'), tpl = document.getElementById('dc-tpl'), helmet = dc.querySelector('helmet');\n"
                       "  Object.defineProperty(dc, 'innerHTML', { get: function () { return (helmet ? helmet.outerHTML : '') + tpl.innerHTML; } });\n"
                       "})();</script>", 1)


def render_shell(page, noindex=False):
    # The pre-rendered copy goes first in <body>; the live app replaces it.
    return head(page, noindex) + inert(body).replace("<body>", "<body>\n" + MARK, 1)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w", encoding="utf-8").write(text)


def prerender():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright not installed: skipping pre-render (site still works).")
        return {}
    class Quiet(SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def handle(self):
            try:
                super().handle()
            except (ConnectionResetError, BrokenPipeError):
                pass

    handler = functools.partial(Quiet, directory=ROOT)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    labels = {"Pattern": "benchmark", "Focus": "tracking", "Plans": "plans", "Method": "method",
              "About us": "about", "About": "about", "Let's talk": "contact", "Home": "home", "Privacy": "privacy",
              "Login": "login"}
    routes = {p["id"]: p["path"] for p in PAGES}
    snaps = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, reduced_motion="reduce")
        for page in PAGES:
            tab = ctx.new_page()
            tab.goto(base + page["path"], wait_until="load")
            tab.wait_for_selector("#dc-root h1, #dc-root h2", timeout=20000)
            tab.wait_for_timeout(1500)
            snap = tab.evaluate(
                """(args) => {
                  const [labels, routes] = args;
                  const root = document.getElementById('dc-root').cloneNode(true);
                  root.removeAttribute('id');
                  root.id = 'prerender';
                  root.querySelectorAll('script').forEach(s => s.remove());
                  // turn text navigation into real links crawlers can follow
                  root.querySelectorAll('span, div, button').forEach(el => {
                    const t = el.textContent.replace(/[\\s→]+$/, '').trim();
                    if (el.children.length > 1 || !(t in labels)) return;
                    const a = document.createElement('a');
                    a.href = routes[labels[t]];
                    for (const at of el.attributes) a.setAttribute(at.name, at.value);
                    a.style.textDecoration = 'none';
                    a.style.color = a.style.color || 'inherit';
                    a.innerHTML = el.innerHTML;
                    el.replaceWith(a);
                  });
                  return root.outerHTML;
                }""",
                [labels, routes],
            )
            snaps[page["id"]] = snap
            tab.close()
        browser.close()
    srv.shutdown()
    return snaps


def main():
    shells = {p["id"]: render_shell(p) for p in PAGES}
    for p in PAGES:
        write(out_path(p), shells[p["id"]].replace(MARK, ""))
    snaps = {} if "--no-prerender" in sys.argv else prerender()
    for p in PAGES:
        write(out_path(p), shells[p["id"]].replace(MARK, snaps.get(p["id"], "")))
    home = next(p for p in PAGES if p["id"] == "home")
    write(os.path.join(ROOT, "404.html"),
          render_shell(dict(home, title="Page not found | Dapple"), noindex=True).replace(MARK, ""))
    urls = "".join(f"  <url><loc>{SITE}{p['path']}</loc></url>\n" for p in PAGES if not p.get("noindex"))
    write(os.path.join(ROOT, "sitemap.xml"),
          '<?xml version="1.0" encoding="UTF-8"?>\n'
          '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + urls + "</urlset>\n")
    print(f"Built {len(PAGES)} pages" + (" (pre-rendered)" if snaps else ""))


if __name__ == "__main__":
    main()
