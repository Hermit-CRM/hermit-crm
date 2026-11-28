// Copyright 2026 Gijs Bos
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

/* The command palette and the global keys.
 *
 * Cmd-K (Ctrl-K off a Mac) anywhere, or "/" when no field has focus, opens the
 * palette in #palette-root: a search box over /search.json (search.py) whose answers
 * are links (a company, a person, a message on its timeline, a task, a page, a help
 * topic) and actions that open an existing page or form ("New company", "Log a call
 * with ...", "Ask Hermit: ..." fills the Ask box). Nothing here writes: every entry
 * navigates, and Ask still waits for its own button.
 *
 * Keyboard: Up/Down choose, Enter opens, Ctrl/Cmd-Enter opens the full results page,
 * Esc closes and puts focus back where it was; Tab stays inside the dialog. For a
 * screen reader the box is a combobox over a listbox, the dialog is modal, and the
 * number of results is announced in a live region. Typing is debounced (150 ms) and
 * an answer that arrives after a newer question is dropped.
 *
 * Global keys, only when no field has focus and no modifier is held: "g" then h, p,
 * t, c or o (Home, Pipeline, Tasks, Companies, Outreach), "n" (new company), "?"
 * (the list of keys, in the palette). Listed in help/search.md.
 *
 * Without this script the top bar's search box is a plain form to /search. No
 * dependencies. */
(function () {
  "use strict";

  var root = document.getElementById("palette-root");
  if (!root || !window.fetch || !window.JSON) return;

  var DEBOUNCE_MS = 150;
  var CHORD_MS = 1500;        // how long "g" waits for its second key
  var MAC = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || "");
  var MOD = MAC ? "⌘" : "Ctrl";
  var GO = { h: "/", p: "/pipeline", t: "/tasks", c: "/companies", o: "/outreach" };
  var KEYS = [
    // [what you press, what it does, where it goes ("" = this palette)]
    [MOD + " K", "Search and commands, from anywhere", ""],
    ["/", "Search and commands", ""],
    ["g h", "Go to Home", "/"],
    ["g p", "Go to Pipeline", "/pipeline"],
    ["g t", "Go to Tasks", "/tasks"],
    ["g c", "Go to Companies", "/companies"],
    ["g o", "Go to Outreach", "/outreach"],
    ["n", "New company", "/companies/new"],
    ["?", "This list of keys", ""]
  ];

  var dialog, input, list, status, entries = [], active = -1;
  var seq = 0, timer = null, returnTo = null;
  var lastQuery = null;   // the last text asked for
  var shown = null;       // the text whose answer is on screen

  // ------------------------------------------------------------------- building

  function el(tag, attrs, text) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (key) { node.setAttribute(key, attrs[key]); });
    if (text != null) node.textContent = text;
    return node;
  }

  function build() {
    if (dialog) return;
    var backdrop = el("div", { "class": "palette-backdrop" });
    backdrop.addEventListener("click", close);
    dialog = el("div", { "class": "palette", role: "dialog", "aria-modal": "true",
                         "aria-labelledby": "palette-title" });
    dialog.appendChild(el("h2", { id: "palette-title", "class": "visually-hidden" },
                          "Search and commands"));
    var head = el("div", { "class": "palette-head" });
    input = el("input", {
      id: "palette-input", type: "text", role: "combobox", "aria-expanded": "true",
      "aria-controls": "palette-list", "aria-autocomplete": "list",
      "aria-describedby": "palette-help", autocomplete: "off", spellcheck: "false",
      placeholder: "Search, or type what you want to do"
    });
    var shut = el("button", { type: "button", "class": "palette-close",
                              "aria-label": "Close search" }, "Esc");
    shut.addEventListener("click", close);
    head.appendChild(input);
    head.appendChild(shut);
    list = el("ul", { id: "palette-list", role: "listbox", "aria-label": "Results" });
    status = el("p", { "class": "palette-status small", role: "status",
                       "aria-live": "polite" });
    var foot = el("p", { id: "palette-help", "class": "palette-foot small" });
    foot.appendChild(document.createTextNode(
      "↑ ↓ choose · Enter opens · " + MOD + " Enter: all results · Esc closes · "));
    var keys = el("a", { href: "/help/search#keyboard" }, "Keys");
    keys.addEventListener("click", function (e) { e.preventDefault(); showKeys(); });
    foot.appendChild(keys);
    dialog.appendChild(head);
    dialog.appendChild(list);
    dialog.appendChild(status);
    dialog.appendChild(foot);
    root.appendChild(backdrop);
    root.appendChild(dialog);

    input.addEventListener("input", function () { schedule(input.value); });
    input.addEventListener("keydown", onKey);
    dialog.addEventListener("keydown", trapTab);
    // Choosing with the mouse must not take focus out of the box first.
    list.addEventListener("mousedown", function (e) { e.preventDefault(); });
    list.addEventListener("mousemove", function (e) {
      var li = e.target.closest ? e.target.closest("[role=option]") : null;
      if (li) select(Number(li.dataset.index), false);
    });
    list.addEventListener("click", function (e) {
      var li = e.target.closest ? e.target.closest("[role=option]") : null;
      if (li) run(entries[Number(li.dataset.index)], e);
    });
  }

  // ------------------------------------------------------------ open and close

  function isOpen() { return !root.hidden; }

  function open(text, keys) {
    build();
    if (!isOpen()) {
      var focused = document.activeElement;
      returnTo = focused && focused !== document.body ? focused : null;
      root.hidden = false;
      document.documentElement.classList.add("palette-open");
    }
    input.value = text || "";
    input.focus();
    input.select();
    if (keys) showKeys(); else ask(input.value);
  }

  function close() {
    if (!isOpen()) return;
    clearTimeout(timer);
    seq++;                       // an answer still on its way is no longer wanted
    root.hidden = true;
    document.documentElement.classList.remove("palette-open");
    list.textContent = "";
    status.textContent = "";
    entries = [];
    active = -1;
    lastQuery = null;
    shown = null;
    input.removeAttribute("aria-activedescendant");
    var back = returnTo;
    returnTo = null;
    if (back && document.contains(back) && back.focus) back.focus();
  }

  // Tab and Shift-Tab go round the dialog's own controls, never behind it.
  function trapTab(e) {
    if (e.key !== "Tab") return;
    var stops = Array.prototype.filter.call(
      dialog.querySelectorAll("input, button, a[href]"),
      function (node) { return node.offsetParent !== null || node === input; });
    if (!stops.length) return;
    var first = stops[0], last = stops[stops.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }

  // --------------------------------------------------------------- asking

  function schedule(text) {
    clearTimeout(timer);
    timer = setTimeout(function () { ask(text); }, DEBOUNCE_MS);
  }

  function ask(text) {
    var q = String(text || "").trim();
    if (q === lastQuery) return;
    lastQuery = q;
    var mine = ++seq;
    fetch("/search.json?q=" + encodeURIComponent(q), {
      credentials: "same-origin", headers: { Accept: "application/json" }
    }).then(function (r) {
      if (!r.ok) throw new Error(String(r.status));
      return r.json();
    }).then(function (data) {
      if (mine === seq && isOpen()) show(data, q);   // a newer question won
    }).catch(function () {
      if (mine !== seq || !isOpen()) return;
      lastQuery = null;
      showEntries([], q);
      shown = null;
      status.textContent = "Search did not answer. Press Enter for the full results page.";
    });
  }

  // ---------------------------------------------------------------- showing

  // The answer as one flat list of entries (what Up/Down walk), in groups:
  // the results first, then the actions, then "all results".
  function show(data, q) {
    var flat = [];
    (data.groups || []).forEach(function (group) {
      group.hits.forEach(function (hit, i) {
        flat.push({ group: group.label, first: i === 0, title: hit.title, url: hit.url,
                    detail: hit.detail, snippet: hit.snippet, kind: "go" });
      });
    });
    (data.actions || []).forEach(function (action, i) {
      flat.push({ group: q ? "Actions" : "Go to or start", first: i === 0,
                  title: action.label, url: action.url, kind: action.kind,
                  question: action.question });
    });
    if (q) {
      flat.push({ group: "", first: true, kind: "all", url: allUrl(q),
                  title: "All results for “" + q + "”", detail: "the full page" });
    }
    showEntries(flat, q);
    shown = q;
    var hits = (data.groups || []).reduce(function (n, g) { return n + g.hits.length; }, 0);
    status.textContent = !q ? "Type to search. " + flat.length + " commands."
      : hits ? hits + (hits === 1 ? " result" : " results") + " for " + q + "."
      : "Nothing found for " + q + ". " + (flat.length - 1) + " actions.";
  }

  function showKeys() {
    lastQuery = null;
    input.value = "";
    input.focus();
    var flat = KEYS.map(function (k, i) {
      return { group: "Keyboard", first: i === 0, title: k[1], keys: k[0], url: k[2],
               kind: k[2] ? "go" : "stay" };
    });
    showEntries(flat, "");
    shown = "";
    status.textContent = "Keyboard keys: " + KEYS.length + ".";
  }

  function showEntries(flat, q) {
    entries = flat;
    list.textContent = "";
    var groupList = null;
    flat.forEach(function (entry, i) {
      if (entry.first) {
        var group = el("li", { role: "group", "class": "palette-group" });
        if (entry.group) {
          var id = "palette-g-" + i;
          group.setAttribute("aria-labelledby", id);
          group.appendChild(el("div", { id: id, "class": "palette-group-label" }, entry.group));
        }
        groupList = el("ul", { role: "none" });
        group.appendChild(groupList);
        list.appendChild(group);
      }
      var li = el("li", { id: "palette-opt-" + i, role: "option", "aria-selected": "false",
                          "class": "palette-option" });
      li.dataset.index = String(i);
      var line = el("span", { "class": "palette-line" });
      line.appendChild(el("span", { "class": "palette-title" }, entry.title));
      if (entry.keys) {
        var keys = el("span", { "class": "palette-keys" });
        entry.keys.split(" ").forEach(function (key) { keys.appendChild(el("kbd", {}, key)); });
        line.insertBefore(keys, line.firstChild);
        // "g p" is two keys in turn; "Ctrl K" is two at once.
        var spoken = /^g /.test(entry.keys) ? entry.keys.replace(" ", " then ") : entry.keys;
        li.setAttribute("aria-label", spoken + ": " + entry.title);
      }
      if (entry.detail) line.appendChild(el("span", { "class": "palette-detail" }, entry.detail));
      li.appendChild(line);
      if (entry.snippet && entry.snippet.length) {
        var snip = el("span", { "class": "palette-snippet" });
        entry.snippet.forEach(function (part) {
          snip.appendChild(part[1] ? el("mark", {}, part[0]) : document.createTextNode(part[0]));
        });
        li.appendChild(snip);
      }
      groupList.appendChild(li);
    });
    if (!flat.length && q) {
      list.appendChild(el("li", { role: "none", "class": "palette-empty" },
                          "Press Enter for the full results page."));
    }
    active = -1;
    select(flat.length ? 0 : -1, false);
  }

  function select(index, scroll) {
    if (index === active && scroll !== true) return;
    var old = document.getElementById("palette-opt-" + active);
    if (old) { old.setAttribute("aria-selected", "false"); old.classList.remove("on"); }
    active = index;
    var now = document.getElementById("palette-opt-" + active);
    if (now) {
      now.setAttribute("aria-selected", "true");
      now.classList.add("on");
      input.setAttribute("aria-activedescendant", now.id);
      if (scroll !== false && now.scrollIntoView) now.scrollIntoView({ block: "nearest" });
    } else {
      input.removeAttribute("aria-activedescendant");
    }
  }

  // ---------------------------------------------------------------- choosing

  function allUrl(q) { return "/search?q=" + encodeURIComponent(q); }

  function onKey(e) {
    var n = entries.length;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (n) select(((active + (e.key === "ArrowDown" ? 1 : -1)) % n + n) % n, true);
    } else if (e.key === "Enter" && !e.isComposing) {
      e.preventDefault();
      var q = input.value.trim();
      if ((e.metaKey || e.ctrlKey) && q) { go(allUrl(q)); return; }
      // Enter before the answer to what was typed arrived opens the full page,
      // never an entry that belongs to an older question.
      if (q !== shown || active < 0) { if (q) go(allUrl(q)); return; }
      run(entries[active], e);
    } else if (e.key === "Escape") {
      e.preventDefault();
      close();
    }
  }

  function run(entry, e) {
    if (!entry) return;
    if (entry.kind === "ask") { askHermit(entry.question || ""); return; }
    if (entry.kind === "stay") { input.focus(); return; }
    if (entry.url && entry.url.charAt(0) === "/") {
      if (e && (e.metaKey || e.ctrlKey) && e.type === "click") { window.open(entry.url); return; }
      go(entry.url);
    }
  }

  function go(url) {
    returnTo = null;
    close();
    location.assign(url);
  }

  // "Ask Hermit: ..." puts the question in the top bar's Ask box and opens it.
  // The question is only asked when the person presses Ask.
  function askHermit(question) {
    var details = document.querySelector("details[data-ask]");
    var box = document.getElementById("ask-question");
    if (!details || !box) { go("/ask?page=" + encodeURIComponent(location.pathname)); return; }
    returnTo = null;
    close();
    details.open = true;
    var tab = document.getElementById("ask-tab-ask");
    if (tab && tab.getAttribute("aria-selected") !== "true" && !tab.closest("[hidden]")) tab.click();
    box.value = question;
    box.dispatchEvent(new Event("input", { bubbles: true }));
    box.focus();
  }

  // ------------------------------------------------------------ global keys

  function typing(node) {
    if (!node || node === document.body) return false;
    if (node.isContentEditable) return true;
    var tag = node.tagName;
    if (tag === "TEXTAREA" || tag === "SELECT") return true;
    if (tag !== "INPUT") return false;
    return !/^(button|submit|reset|checkbox|radio|range|color|file|image)$/i.test(node.type || "text");
  }

  function modalOpen() {
    var modal = document.querySelector(".modal-backdrop");
    return Boolean(modal && modal.offsetParent !== null);
  }

  var chord = 0;   // when "g" was pressed; 0 when it was not

  document.addEventListener("keydown", function (e) {
    if (e.defaultPrevented || e.isComposing || modalOpen()) return;
    var key = e.key || "";
    if ((MAC ? e.metaKey : e.ctrlKey) && !e.altKey && !e.shiftKey && key.toLowerCase() === "k") {
      e.preventDefault();
      if (isOpen()) close(); else open("");
      return;
    }
    if (isOpen() || e.metaKey || e.ctrlKey || e.altKey) return;
    if (typing(document.activeElement)) { chord = 0; return; }
    if (chord && Date.now() - chord < CHORD_MS && GO[key.toLowerCase()]) {
      e.preventDefault();
      chord = 0;
      location.assign(GO[key.toLowerCase()]);
      return;
    }
    chord = 0;
    if (key === "g" && !e.shiftKey) { chord = Date.now(); return; }
    if (key === "/") { e.preventDefault(); open(""); return; }
    if (key === "?") { e.preventDefault(); open("", true); return; }
    if (key === "n" && !e.shiftKey) { e.preventDefault(); location.assign("/companies/new"); }
  });
})();
