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

/* Make it yours: the Ask · Adjust tabs, and the handoff to the user's own agent.
 *
 * The prompt, the deep link and the shell command are built here while the
 * user types, exactly as hermitcrm/adjust.py's handoff() builds them; the tests
 * run both on the same inputs. Over the byte limit a link agent gets Copy
 * instead of Open, because a long deep link fails silently on macOS. The page
 * says which agent, which folder and which page in data attributes, so nothing
 * here knows about the server. No dependencies. */
(function () {
  "use strict";

  // The whitespace adjust.py's _SPACE collapses: JavaScript's \s, spelled out.
  var SPACE = /[\t\n\v\f\r \u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]+/g;

  function oneLine(text) {
    return String(text || "").replace(SPACE, " ").replace(/^ | $/g, "");
  }

  function promptFor(agent, request, title, path) {
    request = oneLine(request);
    title = oneLine(title);
    var asked = "";
    if (path) asked = title ? "Asked on " + title + " (" + path + "): " : "Asked on " + path + ": ";
    if (agent === "claude") return "/hermit " + asked + request;
    return 'Run "hermitcrm help adjust" first and follow it. ' + asked + request;
  }

  function byteSize(text) {
    return new TextEncoder().encode(text).length;
  }

  // Python's shlex.quote.
  function shellQuote(s) {
    if (!s) return "''";
    if (!/[^\w@%+=:,.\/-]/.test(s)) return s;
    return "'" + s.replace(/'/g, "'\"'\"'") + "'";
  }

  function handoff(agent, folder, request, title, path, limit) {
    var known = ["claude", "cursor", "codex", "gemini", "copy"];
    if (known.indexOf(agent) === -1) agent = "copy";
    var prompt = promptFor(agent, request, title, path);
    var size = byteSize(prompt);
    var out = {agent: agent, prompt: prompt, bytes: size, link: "", command: "", too_long: false};
    if (agent === "claude" || agent === "cursor") {
      if (size > limit) out.too_long = true;
      else if (agent === "claude") {
        out.link = "claude-cli://open?cwd=" + encodeURIComponent(folder) + "&q=" + encodeURIComponent(prompt);
      } else {
        out.link = "cursor://anysphere.cursor-deeplink/prompt?text=" + encodeURIComponent(prompt);
      }
    } else if (agent === "codex") {
      out.command = "cd " + shellQuote(folder) + " && codex " + shellQuote(prompt);
    } else if (agent === "gemini") {
      out.command = "cd " + shellQuote(folder) + " && gemini -i " + shellQuote(prompt);
    }
    return out;
  }

  var api = {oneLine: oneLine, promptFor: promptFor, byteSize: byteSize,
             shellQuote: shellQuote, handoff: handoff};
  if (typeof module === "object" && module.exports) {  // the tests, under node
    module.exports = api;
    return;
  }

  // ------------------------------------------------------------------ the page

  function copyText(text, done) {
    function fallback() {
      var area = document.createElement("textarea");
      area.value = text;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      var ok = false;
      try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
      area.remove();
      done(ok);
    }
    // The clipboard API needs a secure context: 127.0.0.1 is one, a phone on
    // the network reaching http://<this machine> is not.
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(function () { done(true); }, fallback);
    } else {
      fallback();
    }
  }

  function fill(area, text) {
    area.value = text;
    area.dispatchEvent(new Event("input"));
    area.focus();
    // Select the first [placeholder], so typing replaces it.
    var start = text.indexOf("[");
    var end = start === -1 ? -1 : text.indexOf("]", start);
    if (end !== -1) area.setSelectionRange(start, end + 1);
  }

  function wire(box) {
    var area = box.querySelector("[data-request]");
    if (!area) return;
    var open = box.querySelector("[data-open]");
    var copyPrompt = box.querySelector('[data-copy="prompt"]');
    var tooLong = box.querySelector("[data-too-long]");
    var hint = box.querySelector("[data-link-hint]");
    var sentAs = box.querySelector("[data-sent-as]");
    var status = box.querySelector("[data-copied]");
    var limit = parseInt(box.dataset.limit, 10) || 500;
    var current = null;

    function update() {
      current = handoff(box.dataset.agent, box.dataset.folder, area.value,
                        box.dataset.pageTitle, box.dataset.path, limit);
      var empty = !oneLine(area.value);
      if (open) {
        open.hidden = current.too_long;
        open.href = current.link || "#";
        if (empty) open.setAttribute("aria-disabled", "true");
        else open.removeAttribute("aria-disabled");
        if (copyPrompt) copyPrompt.classList.toggle("primary", current.too_long);
      }
      if (tooLong) tooLong.hidden = !current.too_long;
      if (hint) hint.hidden = current.too_long;
      if (sentAs) sentAs.textContent = empty ? "(type a request first)" : current.prompt;
      if (status) status.textContent = "";
    }

    function say(text) {
      if (status) status.textContent = text;
    }

    area.addEventListener("input", update);
    if (open) {
      open.addEventListener("click", function (e) {
        if (!oneLine(area.value)) {
          e.preventDefault();
          say("Type a request first.");
          area.focus();
        }
      });
    }
    box.querySelectorAll("[data-copy]").forEach(function (button) {
      button.addEventListener("click", function () {
        if (!oneLine(area.value)) {
          say("Type a request first.");
          area.focus();
          return;
        }
        var text = button.dataset.copy === "command" ? current.command : current.prompt;
        copyText(text, function (ok) {
          say(ok ? (button.dataset.copy === "command" ? "Command copied." : "Prompt copied.")
                 : "Could not copy: select the text under What your agent receives.");
        });
      });
    });
    update();
  }

  document.querySelectorAll(".handoff").forEach(wire);

  // A starter (the Adjust tab) or "Use this" (the hub) puts its text in a box.
  document.querySelectorAll("[data-starter]").forEach(function (button) {
    button.addEventListener("click", function () {
      var area = document.getElementById(button.dataset.target);
      if (!area) return;
      document.querySelectorAll("[data-starter].picked").forEach(function (b) {
        b.classList.remove("picked");
      });
      button.classList.add("picked");
      fill(area, button.dataset.starter);
    });
  });
  document.querySelectorAll("a[data-use]").forEach(function (link) {
    link.addEventListener("click", function (e) {
      var area = document.getElementById("describe-request");
      if (!area) return;   // not on the hub: the link itself goes there
      e.preventDefault();
      document.getElementById("describe").scrollIntoView({block: "start"});
      fill(area, link.dataset.use);
    });
  });

  // The hub's family chips filter the idea cards in place.
  document.querySelectorAll("[data-chips]").forEach(function (chips) {
    chips.querySelectorAll("a[data-family]").forEach(function (chip) {
      chip.addEventListener("click", function (e) {
        e.preventDefault();
        var family = chip.dataset.family;
        chips.querySelectorAll("a[data-family]").forEach(function (c) {
          c.classList.toggle("on", c === chip);
        });
        document.querySelectorAll(".recipe[data-family]").forEach(function (card) {
          card.hidden = Boolean(family) && card.dataset.family !== family;
        });
      });
    });
  });

  // Ask · Adjust: two tabs in one panel; the last one used opens next time.
  var KEY = "hermitcrm.askTab";
  function remembered() {
    try { return localStorage.getItem(KEY) === "adjust" ? "adjust" : "ask"; }
    catch (e) { return "ask"; }
  }
  function remember(name) {
    try { localStorage.setItem(KEY, name); } catch (e) { /* private window */ }
  }
  document.querySelectorAll("details[data-ask]").forEach(function (details) {
    var tablist = details.querySelector("[role=tablist]");
    var tabs = details.querySelectorAll("[data-tab]");
    if (!tablist || !tabs.length) return;
    tablist.hidden = false;
    function show(name) {
      tabs.forEach(function (tab) {
        var on = tab.dataset.tab === name;
        tab.classList.toggle("on", on);
        tab.setAttribute("aria-selected", on ? "true" : "false");
        document.getElementById(tab.getAttribute("aria-controls")).hidden = !on;
      });
    }
    tabs.forEach(function (tab) {
      tab.addEventListener("click", function () {
        show(tab.dataset.tab);
        remember(tab.dataset.tab);
        var panel = document.getElementById(tab.getAttribute("aria-controls"));
        var box = panel.querySelector("textarea");
        if (box) box.focus();
      });
    });
    show(remembered());
  });
})();
