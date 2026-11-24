"""The family tree as a web page anyone can open in a browser, phones included.

- `single_file` writes one .html file holding everything (people, a family chart, search,
  small photos). Sent by email or chat, it opens with nothing to install. With a password,
  the family data inside is encrypted (AES-256-GCM, key from the password with PBKDF2-SHA256)
  and the browser decrypts it with its own Web Crypto; without the password the file
  shows nothing about the family.
- `LiveShare` serves the same page on this computer's network while the program is open,
  at an address with a random part, so only someone given the address (or the QR code)
  can open it. It stops when sharing is stopped or the program closes.

The tree passed in must already be made safe for sharing (privacy.shareable).
"""
import base64
import datetime
import html
import json
import os
import secrets
import socket
import threading
import unicodedata
from pathlib import Path

from model import (
    FOLD_LETTERS, date_input_text, fact_details, family_marriage, fold_text, person_events, person_names, person_story,
    tree_sources,
)
from strings import t

PHOTO_PX = 260
PBKDF2_ROUNDS = 600_000


def encryption_available():
    """Whether the encryption library is installed (it may be missing on a phone)."""
    import importlib.util
    try:
        return importlib.util.find_spec("cryptography.hazmat.primitives.ciphers.aead") is not None
    except ImportError:
        return False


def _photo_data(path):
    """A small JPEG of a portrait as a data: URL, or ""."""
    if not path:
        return ""
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
    from PySide6.QtGui import QImage
    image = QImage(str(path))
    if image.isNull():
        return ""
    image = image.scaled(PHOTO_PX, PHOTO_PX, Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "JPEG", 82)
    return "data:image/jpeg;base64," + base64.b64encode(bytes(data)).decode("ascii")


def _fact_text(fact):
    parts = [date_input_text(fact.get("date", "")) if fact.get("date") else "", fact.get("place", ""),
             fact.get("text", "")]
    return ", ".join(part for part in parts if part)


def site_data(tree, home=None, photo_path=None, title=""):
    """Everything the page shows, as plain data. `photo_path(stored)` gives a portrait's
    file, or None to leave photos out. Nothing changes the tree meanwhile, so every family
    lookup shares one index (7.9 s -> 0.08 s on 2,000 people)."""
    with tree.looking():
        return _site_data(tree, home, photo_path, title)


def _site_data(tree, home, photo_path, title):
    sources = {k: ", ".join(v[key] for key in ("title", "author", "repository") if v[key]) or t("source_untitled")
               for k, v in tree_sources(tree).items()}
    people = {}
    for person in tree.people.values():
        facts = []
        for label, fact in ((t("fact_birth"), person.birth), (t("fact_death"), person.death)):
            if fact and _fact_text(fact):
                facts.append([label, _fact_text(fact)])
        for event in person_events(person):
            if _fact_text(event):
                facts.append([t(f"event_{event['type']}"), _fact_text(event)])
        parents = [p for f, link in tree.parent_families(person.id) for p in f.partners if p in tree.people]
        partners, children = [], []
        for family in tree.families_of(person.id):
            marriage = family_marriage(family)
            for partner in family.partners:
                if partner != person.id and partner in tree.people:
                    when = _fact_text(marriage)
                    partners.append([partner, when])
            children += [c for c in family.child_ids if c in tree.people and c not in children]
        siblings = []
        for family, _link in tree.parent_families(person.id):
            siblings += [c for c in family.child_ids if c != person.id and c in tree.people and c not in siblings]
        cited = []
        marriages = [family_marriage(family) for family in tree.families_of(person.id)]
        for fact in [person.birth, person.death, *person_events(person), *marriages, *person_names(person)]:
            for citation in fact_details(fact).get("citations", []) if fact else []:
                text = sources.get(citation["source"], "")
                if citation.get("page"):
                    text += f", {citation['page']}"
                if text and text not in cited:
                    cited.append(text)
        people[person.id] = {
            "name": person.full_name, "years": person.years_label(), "sex": person.sex,
            "photo": _photo_data(photo_path(person.photo)) if photo_path and person.photo else "",
            "facts": facts, "parents": parents, "partners": partners, "children": children,
            "siblings": siblings, "story": person_story(person), "notes": person.notes,
            "names": [f"{n['given']} {n['surname']}".strip() for n in person_names(person)],
            "sources": cited, "search": fold_text(" ".join([person.display_name, person.full_name, person.birth_surname] + [
                f"{n['given']} {n['surname']}" for n in person_names(person)])),
        }
    words = {key: t(key) for key in (
        "web_search", "web_parents", "web_partners", "web_children", "web_siblings", "web_story", "web_notes",
        "web_other_names", "web_sources", "web_everyone", "web_password", "web_open", "web_wrong_password",
        "web_made", "web_back_to_chart")}
    words["web_made"] = t("web_made", date=datetime.date.today().strftime("%d.%m.%Y"))
    import strings
    return {"title": title or t("window_title"), "home": home if home in people else next(iter(people), None),
            "people": people, "words": words, "lang": strings.LANGUAGE.replace("_", "-"),
            "rtl": strings.right_to_left()}


def encrypt(data, password):
    """AES-256-GCM with a key made from the password (PBKDF2-SHA256, random salt)."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    salt, iv = os.urandom(16), os.urandom(12)
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=PBKDF2_ROUNDS).derive(
        unicodedata.normalize("NFC", password).encode("utf-8"))  # "Š" typed either way opens it.
    sealed = AESGCM(key).encrypt(iv, data, None)
    return {"salt": base64.b64encode(salt).decode(), "iv": base64.b64encode(iv).decode(),
            "rounds": PBKDF2_ROUNDS, "data": base64.b64encode(sealed).decode()}


def decrypt(payload, password):
    """The reverse of encrypt, for tests and for opening a page again."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=base64.b64decode(payload["salt"]),
                     iterations=payload["rounds"]).derive(password.encode("utf-8"))
    return AESGCM(key).decrypt(base64.b64decode(payload["iv"]), base64.b64decode(payload["data"]), None)


def page(data, password=None):
    """The whole page as one HTML text."""
    content = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    if password:
        payload = {"locked": encrypt(content.encode("utf-8"), password)}
        title = t("web_locked_title")
    else:
        payload = {"open": data}
        title = data["title"]
    # Every "<" as \u003c: then no text in the tree ("</script>", or "<!--" with a later
    # "<script") can end or bend the page's own script. Valid in JSON and in JavaScript.
    blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    words = json.dumps({key: t(key) for key in ("web_password", "web_open", "web_wrong_password", "web_locked")},
                       ensure_ascii=False)
    import branding
    return (TEMPLATE.replace("__TITLE__", html.escape(title)).replace("__ICON__", branding.small_icon_uri())
            .replace("__LANG__", html.escape(data.get("lang", "en")))
            .replace("__DIR__", "rtl" if data.get("rtl") else "ltr")
            .replace("__FOLD__", json.dumps(FOLD_LETTERS, ensure_ascii=False))
            .replace("__WORDS__", words.replace("<", "\\u003c"))
            .replace("__DATA__", blob))


def single_file(path, data, password=None):
    from storage import atomic_write
    path = Path(path)
    atomic_write(path, page(data, password))  # A unique temporary file, removed on failure.
    return path.stat().st_size


class LiveShare:
    """Serves the page on this computer's network until stopped. Only the address with the
    random token answers; everything else is "not found". Nothing is ever received or saved."""

    def __init__(self, data, port=0):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        self.token = secrets.token_urlsafe(9)
        self.views = 0
        body = page(data).encode("utf-8")
        share = self

        self.stopped = False
        self.connections = set()

        class Handler(BaseHTTPRequestHandler):
            timeout = 15  # A device that connects and says nothing is let go.

            def setup(self):
                super().setup()
                share.connections.add(self.connection)

            def finish(self):
                share.connections.discard(self.connection)
                try:
                    super().finish()
                except OSError:
                    pass  # The phone hung up: nothing to tell anyone.

            def do_GET(self):  # noqa: N802 - the name http.server calls.
                if share.stopped or self.path.split("?")[0] != f"/{share.token}":
                    self.send_error(404)
                    return
                share.views += 1
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass  # Nothing written to the console or to files.

        self.server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
        self.server.handle_error = lambda request, address: None  # No tracebacks for dropped phones.
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def addresses(self):
        """This computer's addresses other devices can reach: home network first."""
        from PySide6.QtNetwork import QAbstractSocket, QNetworkInterface
        found = []
        for address in QNetworkInterface.allAddresses():
            if address.protocol() != QAbstractSocket.NetworkLayerProtocol.IPv4Protocol or address.isLoopback():
                continue
            text = address.toString()
            private = text.startswith(("192.168.", "10.")) or (text.startswith("172.") and 16 <= int(text.split(".")[1]) <= 31)
            tailscale = text.startswith("100.") and 64 <= int(text.split(".")[1]) <= 127
            if private or tailscale:
                found.append((0 if private else 1, f"http://{text}:{self.port}/{self.token}"))
        return [url for _rank, url in sorted(found)]

    def stop(self):
        """Safe to call more than once."""
        self.stopped = True  # A request still on its way is refused, not answered.
        if self.thread is not None:
            self.server.shutdown()
            self.server.server_close()
            self.thread = None
        for connection in list(self.connections):  # Connections already open end now too.
            try:
                connection.shutdown(socket.SHUT_RDWR)
                connection.close()
            except OSError:
                pass
        self.connections.clear()


def qr_png(text, scale=6):
    """A QR code for an address as PNG bytes (whole pixels per square, so no seams that
    upset phone cameras), or b"" when the QR library isn't there."""
    try:
        import segno
    except ImportError:
        return b""
    import io
    buffer = io.BytesIO()
    segno.make(text, error="m").save(buffer, kind="png", scale=scale, border=3, dark="#000", light="#fff")
    return buffer.getvalue()


TEMPLATE = r"""<!doctype html>
<html lang="__LANG__" dir="__DIR__"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>__TITLE__</title>
<link rel="icon" href="__ICON__">
<style>
:root { --bg:#f6f4ef; --card:#fff; --ink:#1f2328; --soft:#5b616b; --line:#c9c4b8; --accent:#2f6fd1; --mark:#e0a020; }
@media (prefers-color-scheme: dark) { :root { --bg:#1b1d20; --card:#26292d; --ink:#e8e8e8; --soft:#a8acb3; --line:#4a4e55; --accent:#7fb2ff; } }
* { box-sizing: border-box; }
body { margin:0; font:16px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; background:var(--bg); color:var(--ink); }
header { position:sticky; top:0; background:var(--bg); padding:10px 16px; border-bottom:1px solid var(--line); display:flex; gap:10px; align-items:center; flex-wrap:wrap; z-index:2; }
header h1 { font-size:18px; margin:0; flex:1 1 auto; display:flex; align-items:center; gap:10px; }
.mark { width:28px; height:28px; flex:none; }
footer { display:flex; align-items:center; gap:8px; justify-content:center; color:var(--soft); font-size:13px; padding:20px 16px; }
footer .mark { width:18px; height:18px; }
input[type=search], input[type=password] { font:inherit; padding:8px 10px; border:1px solid var(--line); border-radius:8px; background:var(--card); color:var(--ink); min-width:0; width:240px; max-width:100%; }
main { max-width:1100px; margin:0 auto; padding:16px; }
.chart { overflow-x:auto; background:var(--card); border:1px solid var(--line); border-radius:12px; padding:12px; }
.row { display:flex; gap:10px; justify-content:center; margin:6px 0; flex-wrap:nowrap; }
.label { text-align:center; color:var(--soft); font-size:13px; margin-top:8px; }
.p { background:var(--bg); border:1px solid var(--line); border-radius:10px; padding:6px 8px; width:120px; text-align:center; cursor:pointer; flex:none; }
.p img { width:64px; height:80px; object-fit:cover; border-radius:6px; display:block; margin:0 auto 4px; }
.p .n { font-weight:600; font-size:14px; } .p .y { color:var(--soft); font-size:12px; }
.p.me { border:2px solid var(--accent); }
.detail { margin-top:16px; background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px; display:grid; grid-template-columns: 180px 1fr; gap:16px; }
.detail img { width:100%; border-radius:8px; }
.detail.single { grid-template-columns:1fr; }
.detail h2 { margin:0 0 4px; } .soft { color:var(--soft); }
table { border-collapse:collapse; } td { padding:2px 12px 2px 0; vertical-align:top; } td:first-child { color:var(--soft); white-space:nowrap; }
a { color:var(--accent); cursor:pointer; text-decoration:none; } a:hover { text-decoration:underline; }
h3 { margin:14px 0 4px; font-size:15px; }
.list a { display:inline-block; margin:2px 10px 2px 0; }
#results { background:var(--card); border:1px solid var(--line); border-radius:10px; margin-top:8px; padding:6px 10px; }
footer { color:var(--soft); font-size:12px; text-align:center; padding:20px; }
.lock { max-width:360px; margin:15vh auto; background:var(--card); border:1px solid var(--line); border-radius:12px; padding:20px; text-align:center; }
.lock button { font:inherit; padding:8px 16px; margin-top:10px; border-radius:8px; border:1px solid var(--accent); background:var(--accent); color:#fff; }
@media (max-width:640px) { .detail { grid-template-columns:1fr; } .detail img { max-width:180px; } .p { width:96px; } .p img { width:52px; height:64px; } }
</style></head><body>
<div id="app"></div>
<script>
"use strict";
const WORDS = __WORDS__;
const ICON = (document.querySelector("link[rel=icon]") || {}).href || "";
const PAYLOAD = __DATA__;
const app = document.getElementById("app");
function el(tag, attrs, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "onclick") node.addEventListener("click", v); else node.setAttribute(k, v);
  }
  for (const kid of kids) if (kid !== null && kid !== undefined) node.append(kid);
  return node;
}
function b64(text) { return Uint8Array.from(atob(text), c => c.charCodeAt(0)); }
async function unlock(password) {
  const sealed = PAYLOAD.locked;
  const material = await crypto.subtle.importKey("raw", new TextEncoder().encode(password.normalize("NFC")), "PBKDF2", false, ["deriveKey"]);
  const key = await crypto.subtle.deriveKey({name: "PBKDF2", salt: b64(sealed.salt), iterations: sealed.rounds, hash: "SHA-256"},
                                            material, {name: "AES-GCM", length: 256}, false, ["decrypt"]);
  const plain = await crypto.subtle.decrypt({name: "AES-GCM", iv: b64(sealed.iv)}, key, b64(sealed.data));
  return JSON.parse(new TextDecoder().decode(plain));
}
function askPassword() {
  const field = el("input", {type: "password", autofocus: "", autocomplete: "current-password"});
  const message = el("div", {class: "soft"});
  const open = async () => {
    message.textContent = "";
    try { start(await unlock(field.value)); } catch (e) { message.textContent = WORDS.web_wrong_password; }
  };
  field.addEventListener("keydown", e => { if (e.key === "Enter") open(); });
  app.replaceChildren(el("div", {class: "lock"}, el("p", {}, WORDS.web_locked), el("label", {}, WORDS.web_password), el("br"),
                         field, el("br"), el("button", {onclick: open}, WORDS.web_open), message));
  field.focus();
}
let DATA = null;
function person(id) { return Object.prototype.hasOwnProperty.call(DATA.people, id) ? DATA.people[id] : undefined; }
function card(id, me) {
  const p = person(id); if (!p) return null;
  return el("div", {class: "p" + (me ? " me" : ""), onclick: () => go(id), title: p.name},
            p.photo ? el("img", {src: p.photo, alt: ""}) : null, el("div", {class: "n"}, p.name), el("div", {class: "y"}, p.years));
}
function row(ids, label, me) {
  const cards = ids.map(id => card(id, id === me)).filter(Boolean);
  if (!cards.length) return null;
  return el("div", {}, label ? el("div", {class: "label"}, label) : null, el("div", {class: "row"}, ...cards));
}
function links(ids) { return el("div", {class: "list"}, ...ids.filter(person).map(id => el("a", {onclick: () => go(id)}, person(id).name))); }
function show(id) {
  const p = person(id); if (!p) return;
  const w = DATA.words;
  const grandparents = p.parents.flatMap(x => (person(x) || {parents: []}).parents);
  const chart = el("div", {class: "chart"},
    row(grandparents, null), row(p.parents, w.web_parents),
    row([...p.siblings, id, ...p.partners.map(x => x[0])], null, id), row(p.children, w.web_children));
  const facts = el("table", {}, ...p.facts.map(([k, v]) => el("tr", {}, el("td", {}, k), el("td", {}, v))));
  const text = (heading, body) => body ? el("div", {}, el("h3", {}, heading), ...body.split(/\n\n+/).map(par => el("p", {}, par))) : null;
  const info = el("div", {},
    el("h2", {}, p.name), el("div", {class: "soft"}, p.years), facts,
    p.names.length ? el("div", {}, el("h3", {}, w.web_other_names), p.names.join(", ")) : null,
    p.parents.length ? el("div", {}, el("h3", {}, w.web_parents), links(p.parents)) : null,
    p.partners.length ? el("div", {}, el("h3", {}, w.web_partners),
      el("div", {class: "list"}, ...p.partners.filter(x => person(x[0])).map(([x, when]) =>
        el("span", {}, el("a", {onclick: () => go(x)}, person(x).name), when ? " (" + when + ")  " : "  ")))) : null,
    p.children.length ? el("div", {}, el("h3", {}, w.web_children), links(p.children)) : null,
    p.siblings.length ? el("div", {}, el("h3", {}, w.web_siblings), links(p.siblings)) : null,
    text(w.web_story, p.story), text(w.web_notes, p.notes),
    p.sources.length ? el("div", {}, el("h3", {}, w.web_sources), el("ol", {}, ...p.sources.map(s => el("li", {}, s)))) : null);
  const detail = p.photo ? el("div", {class: "detail"}, el("img", {src: p.photo, alt: ""}), info)
                         : el("div", {class: "detail single"}, info);
  document.getElementById("view").replaceChildren(chart, detail);
  window.scrollTo(0, 0);
}
function go(id) { location.hash = encodeURIComponent(id); }
function route() {
  let id = location.hash.slice(1);
  try { id = decodeURIComponent(id); } catch (error) { id = ""; }  // "#%" typed by hand: just go home.
  show(person(id) ? id : DATA.home);
}
const FOLD = __FOLD__;
function fold(text) {
  text = text.toLowerCase();
  for (const [letter, plain] of Object.entries(FOLD)) text = text.split(letter).join(plain);
  return text.normalize("NFKD").replace(/[\u0300-\u036f]/g, "");
}
function start(data) {
  DATA = data;
  document.title = data.title;
  const w = data.words;
  const results = el("div", {id: "results", hidden: ""});
  const search = el("input", {type: "search", placeholder: w.web_search, "aria-label": w.web_search});
  search.addEventListener("input", () => {
    const words = fold(search.value).split(/\s+/).filter(Boolean);
    if (!words.length) { results.hidden = true; return; }
    const found = Object.entries(DATA.people).filter(([, p]) => words.every(x => p.search.includes(x))).slice(0, 30);
    results.replaceChildren(...found.map(([id, p]) => el("div", {}, el("a", {onclick: () => { results.hidden = true; search.value = ""; go(id); }}, p.name + (p.years ? "  (" + p.years + ")" : "")))));
    results.hidden = !found.length;
  });
  app.replaceChildren(
    el("header", {}, el("h1", {}, el("img", {src: ICON, alt: "", class: "mark"}), data.title),
       el("a", {onclick: () => go(DATA.home)}, w.web_back_to_chart), search),
    el("main", {}, results, el("div", {id: "view"})),
    el("footer", {}, el("img", {src: ICON, alt: "", class: "mark"}), w.web_made));
  window.addEventListener("hashchange", route);
  route();
}
if (PAYLOAD.locked) askPassword(); else start(PAYLOAD.open);
</script></body></html>
"""
