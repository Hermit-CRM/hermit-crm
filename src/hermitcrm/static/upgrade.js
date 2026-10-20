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

/* One-click upgrade, the browser's half (upgrade.py has the server's).
 *
 * A form marked data-upgrade (the nav's "Upgrade now" and "Restart now", and
 * the same buttons on Settings) is sent with fetch instead of navigating, and a
 * panel over the page follows it: installing, checking, restarting. The server
 * goes away for a moment and comes back as a new process; every process has its
 * own `boot` id, and the page tells "the same server" from "a new one" by it.
 * When the new one answers, the panel asks you to reload. It does not reload by
 * itself: the page you are on was drawn by the old version.
 *
 * Every other tab does the same when it becomes visible again, so none of them
 * keeps forms whose tokens died with the old process.
 * Without this script the forms post normally and land on /upgrade, a plain
 * page that refreshes itself. No dependencies; text is set with textContent. */
(function () {
  "use strict";

  var root = document.documentElement;
  var boot = root.getAttribute("data-boot") || "";
  var version = root.getAttribute("data-version") || "";
  var BUSY = { installing: 1, verifying: 1, restarting: 1 };
  var GIVE_UP_AFTER = 120000;   // ms of silence before we say it did not come back
  var panel = null, timer = null, silentSince = 0, shown = "";

  function node(tag, className, text) {
    var n = document.createElement(tag);
    if (className) n.className = className;
    if (text) n.textContent = text;
    return n;
  }

  function show(title, lines, buttons, working) {
    // Polling calls this every second; rebuilding a live region makes a screen
    // reader read it out again, so repaint only when the words change.
    var key = [title, lines.join("|"), (buttons || []).map(function (b) { return b.label; }).join("|"),
               working ? "w" : ""].join("\n");
    if (panel && key === shown) return;
    shown = key;
    if (!panel) {
      panel = node("div", "upgrade-overlay");
      panel.setAttribute("role", "alertdialog");
      panel.setAttribute("aria-live", "assertive");
      document.body.appendChild(panel);
    }
    var box = node("div", "upgrade-box-dialog");
    box.appendChild(node("h2", "", title));
    lines.forEach(function (line) { box.appendChild(node("p", "", line)); });
    if (working) box.appendChild(node("div", "upgrade-bar"));
    var row = node("div", "upgrade-actions");
    (buttons || []).forEach(function (b) {
      var button = node("button", b.primary ? "primary" : "", b.label);
      button.type = "button";
      button.addEventListener("click", b.run);
      row.appendChild(button);
    });
    if (row.childNodes.length) box.appendChild(row);
    panel.textContent = "";
    panel.appendChild(box);
    var first = panel.querySelector("button");
    if (first) first.focus();
  }

  function close() {
    clearTimeout(timer);
    if (panel) panel.remove();
    panel = null;
    shown = "";
  }

  function reload() { window.location.reload(); }

  function failed(message) {
    clearTimeout(timer);
    show("The upgrade did not finish", [message || "Something went wrong."],
         [{ label: "Close", primary: true, run: close }]);
  }

  function done(status) {
    clearTimeout(timer);
    var upgraded = status.version && status.version !== version;
    show(upgraded ? "Upgraded to v" + status.version : "Hermit CRM restarted",
         ["Reload this page to use it. What you have open was drawn by the old version."],
         [{ label: "Reload", primary: true, run: reload }]);
  }

  function ask() {
    return fetch("/upgrade/status", { cache: "no-store", headers: { "Accept": "application/json" } })
      .then(function (r) { return r.json(); });
  }

  // Follow an upgrade until a new process answers, it fails, or nothing answers for 2 minutes.
  function follow() {
    ask().then(function (status) {
      silentSince = 0;
      if (status.boot !== boot) return done(status);
      if (status.state === "failed") return failed(status.error);
      show("Upgrading Hermit CRM", [status.detail || "Working..."], [], true);
      timer = setTimeout(follow, 1000);
    }, function () {
      // The server is between processes, which is expected for a few seconds.
      silentSince = silentSince || Date.now();
      if (Date.now() - silentSince > GIVE_UP_AFTER) {
        return failed("Hermit CRM did not come back. Its log (the serve log, or the " +
                      "terminal it runs in) says why; then start it again.");
      }
      show("Upgrading Hermit CRM", ["Restarting Hermit CRM..."], [], true);
      timer = setTimeout(follow, 1000);
    });
  }

  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form || !form.hasAttribute || !form.hasAttribute("data-upgrade")) return;
    event.preventDefault();
    show("Upgrading Hermit CRM", ["Starting..."], [], true);
    fetch(form.action, {
      method: "POST",
      body: new URLSearchParams(new FormData(form)),
      headers: { "Accept": "application/json" }
    }).then(function (r) {
      return r.json().then(function (body) { return { ok: r.ok, body: body }; });
    }).then(function (result) {
      if (!result.ok) return failed(result.body.error || result.body.detail);
      follow();
    }, function () { failed("Could not reach Hermit CRM."); });
  });

  // A tab that was not the one clicked: tell it when the server was replaced, or
  // when an upgrade started in another tab is under way.
  function watch() {
    if (document.visibilityState !== "visible" || panel) return;
    ask().then(function (status) {
      if (panel) return;
      if (status.boot !== boot) return done(status);
      if (BUSY[status.state]) follow();
    }, function () { /* down or restarting: the next focus asks again */ });
  }
  document.addEventListener("visibilitychange", watch);
  window.addEventListener("focus", watch);
})();
