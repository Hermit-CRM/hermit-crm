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

/* Say that something is happening. A button with data-busy="Reading your
 * website..." (the AI buttons, which take from seconds to minutes) shows a
 * spinner and that text once it is clicked, and cannot be clicked twice.
 * The page says so too: a bar along the top edge, wherever you have scrolled
 * to, and a note with the seconds that have passed.
 * The form still submits normally; without this script nothing changes.
 * No dependencies. */
(function () {
  "use strict";

  var root = document.documentElement;
  var timer = null;

  function clock(note, since) {
    var span = document.createElement("span");
    span.className = "busy-clock";
    span.setAttribute("aria-hidden", "true");   // the status text is read once, not every second
    note.appendChild(span);
    timer = setInterval(function () {
      span.textContent = " Waited " + Math.round((Date.now() - since) / 1000) + " s.";
    }, 1000);
  }

  function start(button) {
    if (button.classList.contains("is-busy")) return;
    button.classList.add("is-busy");
    button.setAttribute("aria-busy", "true");
    button.dataset.idleText = button.textContent;
    button.textContent = button.getAttribute("data-busy");
    var note = document.createElement("span");
    note.className = "busy-note small";
    note.setAttribute("role", "status");
    note.textContent = "This can take a minute. Keep this page open.";
    clock(note, Date.now());
    button.insertAdjacentElement("afterend", note);
    var bar = document.createElement("div");
    bar.className = "busy-bar";
    bar.setAttribute("aria-hidden", "true");
    document.body.appendChild(bar);
    root.classList.add("is-working");
  }

  function stop(button) {
    button.classList.remove("is-busy");
    button.removeAttribute("aria-busy");
    button.removeAttribute("aria-disabled");
    if (button.dataset.idleText) button.textContent = button.dataset.idleText;
    var next = button.nextElementSibling;
    if (next && next.classList.contains("busy-note")) next.remove();
    clearInterval(timer);
    document.querySelectorAll(".busy-bar").forEach(function (bar) { bar.remove(); });
    root.classList.remove("is-working");
  }

  document.addEventListener("submit", function (event) {
    var button = event.submitter;
    if (!button || !button.hasAttribute || !button.hasAttribute("data-busy")) return;
    if (button.classList.contains("is-busy")) { event.preventDefault(); return; }
    if (event.defaultPrevented) return;   // another handler stopped it: nothing is being sent
    start(button);
    // aria-disabled, not disabled: a disabled submitter can drop its own
    // formaction, and the click must still go through once.
    button.setAttribute("aria-disabled", "true");
  });

  // Back button or bfcache: the page comes back as it was when it left.
  window.addEventListener("pageshow", function () {
    document.querySelectorAll("button.is-busy").forEach(stop);
  });
})();
