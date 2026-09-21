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

/* The "Show me around" tour: a bubble pointing at each part of the screen.
 *
 * It only runs when the address has ?tour, so it never gets in the way of
 * ordinary use, and it anchors to data-tour attributes rather than to CSS
 * classes, so restyling the page cannot silently point it at the wrong thing.
 * A stop whose anchor is not on the page is skipped instead of breaking the
 * tour. No dependencies. */
(function () {
  "use strict";
  var params = new URLSearchParams(location.search);
  if (!params.has("tour")) return;
  // Never on top of the one-time disclaimer: accepting it starts the tour.
  if (document.querySelector(".modal-backdrop")) return;

  var STOPS = [
    ["home", "Home", "This walkthrough, until every step is ticked or you turn it off. Then: what needs doing this week, the replies you owe, and last month's numbers."],
    ["pipeline", "Pipeline", "Every open deal as a card, in the column of the stage it has reached."],
    ["calendar", "Calendar", "Next steps and tasks on their due date, and the form to add a task."],
    ["companies", "Companies", "Every account as a table. Each column has a filter: !text means “does not contain”; the ? next to Filter lists the rest."],
    ["contacts", "Contacts", "Every person, with the company they belong to."],
    ["messages", "Messages", "What you sent, and whether it was answered."],
    ["capture", "Extension", "The bookmarklet: save the page you are on as a company, or a LinkedIn profile as a contact."],
    ["search", "Search", "Names, tags and people, from any page."],
    ["ask", "Ask the Hermit", "A question in plain words, about this page or the whole CRM."],
    ["settings", "Settings", "Mail and calendar capture, fields of your own, and the AI."]
  ];

  var stops = STOPS.filter(function (s) {
    return document.querySelector('[data-tour="' + s[0] + '"]');
  });
  if (!stops.length) return;

  var index = 0;
  var target = null;
  var bubble = document.createElement("div");
  bubble.className = "tour-bubble";
  bubble.setAttribute("role", "dialog");
  bubble.setAttribute("aria-live", "polite");
  document.body.appendChild(bubble);

  function end() {
    if (target) target.classList.remove("tour-target");
    bubble.remove();
    document.removeEventListener("keydown", onKey);
    window.removeEventListener("resize", place);
    params.delete("tour");
    var q = params.toString();
    history.replaceState(null, "", location.pathname + (q ? "?" + q : "") + location.hash);
  }

  function place() {
    if (!target) return;
    var r = target.getBoundingClientRect();
    var b = bubble.getBoundingClientRect();
    var top = r.bottom + 10;
    if (top + b.height > window.innerHeight - 8) top = Math.max(8, r.top - b.height - 10);
    var left = Math.min(Math.max(8, r.left), window.innerWidth - b.width - 8);
    bubble.style.top = (top + window.scrollY) + "px";
    bubble.style.left = (left + window.scrollX) + "px";
  }

  function show(i) {
    index = i;
    if (target) target.classList.remove("tour-target");
    var stop = stops[i];
    target = document.querySelector('[data-tour="' + stop[0] + '"]');
    target.classList.add("tour-target");
    target.scrollIntoView({block: "nearest"});
    bubble.innerHTML = "";
    var h = document.createElement("strong");
    h.textContent = stop[1];
    var p = document.createElement("p");
    p.textContent = stop[2];
    var nav = document.createElement("div");
    nav.className = "tour-nav";
    var count = document.createElement("span");
    count.className = "small";
    count.textContent = (i + 1) + " of " + stops.length;
    nav.appendChild(count);
    if (i > 0) nav.appendChild(button("Back", function () { show(i - 1); }));
    nav.appendChild(i < stops.length - 1
      ? button("Next", function () { show(i + 1); })
      : button("Done", end));
    nav.appendChild(button("Close", end, "tour-close"));
    bubble.append(h, p, nav);
    place();
    // Focus goes forward (Next, or Done on the last stop), so Enter moves on.
    var forward = bubble.querySelectorAll("button:not(.tour-close)");
    forward[forward.length - 1].focus();
  }

  function button(label, action, cls) {
    var el = document.createElement("button");
    el.type = "button";
    el.textContent = label;
    if (cls) el.className = cls;
    el.addEventListener("click", action);
    return el;
  }

  function onKey(e) {
    if (e.key === "Escape") end();
    else if (e.key === "ArrowRight" && index < stops.length - 1) show(index + 1);
    else if (e.key === "ArrowLeft" && index > 0) show(index - 1);
  }

  document.addEventListener("keydown", onKey);
  window.addEventListener("resize", place);
  show(0);
})();
