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

/* Saved questions for Ask the Hermit.
 *
 * The saved list is on the page as JSON (#ask-saved-data), so nothing is fetched to
 * suggest. While you type in a question box, the saved questions that contain every
 * word you typed are listed under it; Up/Down choose, Enter or Tab fills the box, Esc
 * closes. An empty box opens the whole list on Down. The chips (adjust.js fills the box)
 * only need this script to carry a question's scope: a question saved as "whole CRM"
 * sets the scope that goes with the Ask button.
 *
 * Save keeps the question without leaving the page (an answer that took minutes is not on
 * a URL). Without this script the Save button is an ordinary form post to /ask/saved.
 * No dependencies. */
(function () {
  "use strict";

  var MAX_SUGGESTIONS = 6;
  var saved = [];
  var data = document.getElementById("ask-saved-data");
  if (data) {
    try { saved = JSON.parse(data.textContent) || []; } catch (e) { saved = []; }
  }

  function words(text) {
    return String(text || "").toLowerCase().split(/\s+/).filter(Boolean);
  }

  function same(a, b) {
    return words(a).join(" ") === words(b).join(" ");
  }

  // Saved questions containing every word typed, those that start with it first.
  // An empty box lists them all, but only when asked (Down).
  function matches(value, all) {
    var typed = words(value);
    if (!typed.length) return all ? saved.slice(0, MAX_SUGGESTIONS) : [];
    var joined = typed.join(" ");
    var starts = [], rest = [];
    saved.forEach(function (item) {
      var hay = words(item.text).join(" ");
      if (hay === joined) return;   // already what is typed
      if (!typed.every(function (w) { return hay.indexOf(w) !== -1; })) return;
      (hay.indexOf(joined) === 0 ? starts : rest).push(item);
    });
    return starts.concat(rest).slice(0, MAX_SUGGESTIONS);
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
    var shown = [];
    var active = -1;

    function close() {
      list.hidden = true;
      list.textContent = "";
      shown = [];
      active = -1;
      area.removeAttribute("aria-activedescendant");
    }

    function mark() {
      Array.prototype.forEach.call(list.children, function (li, i) {
        li.classList.toggle("on", i === active);
        li.setAttribute("aria-selected", i === active ? "true" : "false");
      });
      if (active >= 0) area.setAttribute("aria-activedescendant", list.children[active].id);
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

    function open(all) {
      shown = matches(area.value, all);
      list.textContent = "";
      active = -1;
      if (!shown.length) { close(); return; }
      shown.forEach(function (item, i) {
        var li = document.createElement("li");
        li.id = list.id + "-" + i;
        li.setAttribute("role", "option");
        li.textContent = item.text;
        if (item.scope === "crm") {
          var tag = document.createElement("span");
          tag.className = "tag";
          tag.textContent = "whole CRM";
          li.appendChild(tag);
        }
        // mousedown, not click: the box must not lose focus (and close the list) first.
        li.addEventListener("mousedown", function (e) { e.preventDefault(); pick(item); });
        list.appendChild(li);
      });
      list.hidden = false;
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

  function remember(item) {
    saved = [item].concat(saved.filter(function (s) { return s.id !== item.id; }));
  }

  function post(form) {
    var body = new URLSearchParams(new FormData(form));
    return fetch("/ask/saved", {
      method: "POST",
      headers: {"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
      credentials: "same-origin",
      body: body.toString()
    }).then(function (r) {
      return r.json().catch(function () { return {ok: false, error: "Could not save."}; });
    });
  }

  document.querySelectorAll("[data-save-question]").forEach(function (button) {
    var form = button.form;
    var status = form && form.querySelector("[data-save-status]");
    var timer = null;

    function say(text) {
      if (!status) return;
      status.textContent = text;
      clearTimeout(timer);
      timer = setTimeout(function () { status.textContent = ""; }, 4000);
    }

    button.addEventListener("click", function (e) {
      if (!window.fetch || !window.URLSearchParams || !window.FormData) return;   // plain post
      e.preventDefault();
      if (!form.reportValidity()) return;
      post(form).then(function (result) {
        if (result.ok) { remember(result.saved); say("Saved ✓"); }
        else say(result.error || "Could not save.");
      }, function () { say("Could not save."); });
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
