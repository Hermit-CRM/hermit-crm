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

/* Saved and recent questions for Ask the Hermit.
 *
 * Both lists are on the page as JSON (#ask-data), so nothing is fetched to suggest. The
 * saved list arrives most used first. While you type in a question box, the saved
 * questions that contain every word you typed are listed under it, then a "Recent" group
 * of the questions you asked lately and did not save, each with a Save button; Up/Down
 * choose, Enter or Tab fills the box, Esc closes. An empty box opens both lists on Down.
 * The chips (adjust.js fills the box) only need this script to carry a question's scope:
 * a question saved as "whole CRM" sets the scope that goes with the Ask button.
 *
 * Save keeps the question without leaving the page (an answer that took minutes is not on
 * a URL). Without this script the Save button is an ordinary form post to /ask/saved.
 * No dependencies. */
(function () {
  "use strict";

  var MAX_SAVED = 6;
  var MAX_RECENT = 4;
  var saved = [];
  var recent = [];
  var data = document.getElementById("ask-data");
  if (data) {
    try {
      var parsed = JSON.parse(data.textContent) || {};
      saved = parsed.saved || [];
      recent = parsed.recent || [];
    } catch (e) { saved = []; recent = []; }
  }

  function words(text) {
    return String(text || "").toLowerCase().split(/\s+/).filter(Boolean);
  }

  function same(a, b) {
    return words(a).join(" ") === words(b).join(" ");
  }

  // Of a list, the questions containing every word typed, those that start with it first
  // (the order inside each half is the list's own). An empty box lists the first few, but
  // only when asked (Down).
  function filter(list, value, all, limit) {
    var typed = words(value);
    if (!typed.length) return all ? list.slice(0, limit) : [];
    var joined = typed.join(" ");
    var starts = [], rest = [];
    list.forEach(function (item) {
      var hay = words(item.text).join(" ");
      if (hay === joined) return;   // already what is typed
      if (!typed.every(function (w) { return hay.indexOf(w) !== -1; })) return;
      (hay.indexOf(joined) === 0 ? starts : rest).push(item);
    });
    return starts.concat(rest).slice(0, limit);
  }

  function matches(value, all) {
    return {
      saved: filter(saved, value, all, MAX_SAVED),
      recent: filter(recent, value, all, MAX_RECENT)
    };
  }

  function setScope(form, scope) {
    var control = form.querySelector("[data-ask-scope]");
    if (control) {
      if (control.type === "checkbox") control.checked = scope === "crm";
      else control.value = scope === "crm" ? "crm" : "auto";
    }
    var note = form.querySelector("[data-ask-scope-note]");
    if (note) note.hidden = scope !== "crm";
  }

  document.querySelectorAll("[data-ask-scope-reset]").forEach(function (button) {
    button.addEventListener("click", function () {
      setScope(button.closest("form"), "auto");
    });
  });

  // A chip or "Use": adjust.js puts the text in the box, this carries the scope.
  document.querySelectorAll("[data-ask-saved]").forEach(function (button) {
    button.addEventListener("click", function () {
      var area = document.getElementById(button.dataset.target);
      if (area && area.form) setScope(area.form, button.dataset.scope);
    });
  });

  function suggest(area) {
    var form = area.form;
    var list = form && form.querySelector("[data-ask-suggest]");
    if (!list) return;
    var shown = [];     // the items offered, in the order Up/Down walk them
    var options = [];   // their <li>s (the headings are not in it)
    var active = -1;

    function close() {
      list.hidden = true;
      list.textContent = "";
      shown = [];
      options = [];
      active = -1;
      area.removeAttribute("aria-activedescendant");
    }

    function mark() {
      options.forEach(function (li, i) {
        li.classList.toggle("on", i === active);
        li.setAttribute("aria-selected", i === active ? "true" : "false");
      });
      if (active >= 0) area.setAttribute("aria-activedescendant", options[active].id);
      else area.removeAttribute("aria-activedescendant");
    }

    function pick(item) {
      area.value = item.text;
      setScope(form, item.scope);
      close();
      area.focus();
      var start = item.text.indexOf("[");
      var end = start === -1 ? -1 : item.text.indexOf("]", start);
      if (end !== -1) area.setSelectionRange(start, end + 1);   // type over the [placeholder]
      else area.setSelectionRange(item.text.length, item.text.length);
    }

    function heading(text) {
      var li = document.createElement("li");
      li.className = "head";
      li.setAttribute("role", "presentation");
      li.textContent = text;
      list.appendChild(li);
    }

    function row(item, recentRow) {
      var li = document.createElement("li");
      li.id = list.id + "-" + options.length;
      li.setAttribute("role", "option");
      var text = document.createElement("span");
      text.className = "text";
      text.textContent = item.text;
      li.appendChild(text);
      if (item.scope === "crm") {
        var tag = document.createElement("span");
        tag.className = "tag";
        tag.textContent = "whole CRM";
        li.appendChild(tag);
      }
      if (recentRow) {
        // Keep it without choosing it. Not a tab stop: the Save button next to Ask does
        // the same from the keyboard once the question is in the box.
        var keep = document.createElement("button");
        keep.type = "button";
        keep.className = "linklike keep";
        keep.tabIndex = -1;
        keep.textContent = "Save";
        keep.title = "Keep this question to ask again with one click";
        keep.addEventListener("mousedown", function (e) {
          e.preventDefault();
          e.stopPropagation();   // not a pick
          keepRecent(form, item, function () { open(false, true); });
        });
        li.appendChild(keep);
      }
      // mousedown, not click: the box must not lose focus (and close the list) first.
      li.addEventListener("mousedown", function (e) { e.preventDefault(); pick(item); });
      list.appendChild(li);
      options.push(li);
      shown.push(item);
    }

    function open(all, keepActive) {
      var found = matches(area.value, all);
      var before = keepActive ? active : -1;
      list.textContent = "";
      shown = [];
      options = [];
      active = -1;
      if (!found.saved.length && !found.recent.length) { close(); return; }
      if (found.saved.length && found.recent.length) heading("Saved");
      found.saved.forEach(function (item) { row(item, false); });
      if (found.recent.length) heading("Recent");
      found.recent.forEach(function (item) { row(item, true); });
      list.hidden = false;
      active = Math.min(before, options.length - 1);
      mark();
    }

    area.addEventListener("input", function () { open(false); });
    area.addEventListener("blur", close);
    area.addEventListener("keydown", function (e) {
      var visible = !list.hidden;
      if (e.key === "ArrowDown" && !visible && !area.value.trim()) {
        e.preventDefault();
        open(true);
      } else if (visible && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
        e.preventDefault();
        var step = e.key === "ArrowDown" ? 1 : -1;
        // Positions are -1 ("none") to the last one, wrapping.
        active = (active + 1 + step + shown.length + 1) % (shown.length + 1) - 1;
        mark();
      } else if (visible && active >= 0 && (e.key === "Enter" || e.key === "Tab")) {
        e.preventDefault();
        pick(shown[active]);
      } else if (visible && e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        close();
      }
    });
  }

  document.querySelectorAll("textarea[data-ask-box]").forEach(suggest);

  // ----------------------------------------------------------------- saving

  // A question just saved moves from "Recent" to the top of the saved list (after a reload
  // the page orders it by use again).
  function remember(item) {
    saved = [item].concat(saved.filter(function (s) { return s.id !== item.id; }));
    recent = recent.filter(function (r) { return r.id !== item.id; });
  }

  // The form's own fields (csrf_token, page, scope), with the question and scope replaced
  // when it is a recent one being kept.
  function post(form, question) {
    var body = new URLSearchParams(new FormData(form));
    body.delete("tier");
    if (question) {
      body.set("question", question.text);
      body.set("scope", question.scope === "crm" ? "crm" : "auto");
    }
    return fetch("/ask/saved", {
      method: "POST",
      headers: {"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
      credentials: "same-origin",
      body: body.toString()
    }).then(function (r) {
      return r.json().catch(function () { return {ok: false, error: "Could not save."}; });
    });
  }

  function say(form, text) {
    var status = form && form.querySelector("[data-save-status]");
    if (!status) return;
    status.textContent = text;
    clearTimeout(status.hideTimer);
    status.hideTimer = setTimeout(function () { status.textContent = ""; }, 4000);
  }

  // "Save" on a recent question in the type-ahead.
  function keepRecent(form, item, done) {
    if (!window.fetch || !window.URLSearchParams || !window.FormData) return;
    post(form, item).then(function (result) {
      if (result.ok) { remember(result.saved); say(form, "Saved ✓"); }
      else say(form, result.error || "Could not save.");
      done();
    }, function () { say(form, "Could not save."); done(); });
  }

  document.querySelectorAll("[data-save-question]").forEach(function (button) {
    var form = button.form;

    button.addEventListener("click", function (e) {
      if (!window.fetch || !window.URLSearchParams || !window.FormData) return;   // plain post
      e.preventDefault();
      if (!form.reportValidity()) return;
      post(form).then(function (result) {
        if (result.ok) { remember(result.saved); say(form, "Saved ✓"); }
        else say(form, result.error || "Could not save.");
      }, function () { say(form, "Could not save."); });
    });
  });

  // "Save this question" under an answer.
  document.querySelectorAll("form[data-save-form]").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      if (!window.fetch || !window.URLSearchParams || !window.FormData) return;
      e.preventDefault();
      post(form).then(function (result) {
        var mark = document.createElement("span");
        mark.className = "small ask-saved-mark";
        if (result.ok) {
          remember(result.saved);
          mark.textContent = "Saved ✓";
        } else {
          mark.textContent = result.error || "Could not save.";
        }
        form.replaceWith(mark);
      }, function () {
        var note = document.createElement("span");
        note.className = "small";
        note.textContent = "Could not save.";
        form.appendChild(note);
      });
    });
  });
})();
