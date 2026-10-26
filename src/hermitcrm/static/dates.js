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

/* Date fields. They are text boxes in the date format chosen in Settings (the
 * browser's own <input type="date"> follows its language instead), and this
 * adds a calendar button to each one. The button opens the browser's picker on
 * a hidden native field and writes the pick back in the chosen format. Without
 * this script a date is typed, which the server accepts either way.
 * No dependencies. */
(function () {
  "use strict";

  var STYLES = {
    "iso": { order: "ymd", sep: "-" },
    "dmy-dash": { order: "dmy", sep: "-" },
    "dmy": { order: "dmy", sep: "/" },
    "mdy": { order: "mdy", sep: "/" }
  };
  var style = STYLES[document.documentElement.getAttribute("data-date-style")] || STYLES.iso;

  function pad(n, width) { var s = String(n); while (s.length < width) s = "0" + s; return s; }

  /* "26/10/2026 14:30" (or just the date) -> {y, m, d, time}, or null. */
  function parse(text) {
    var parts = text.trim().split(/[ T]+/);
    var bits = parts[0].split(style.sep);
    if (bits.length !== 3 || !bits.every(function (b) { return /^\d+$/.test(b); })) return null;
    var got = {};
    for (var i = 0; i < 3; i++) got[style.order[i]] = parseInt(bits[i], 10);
    var day = new Date(got.y, got.m - 1, got.d);
    if (day.getFullYear() !== got.y || day.getMonth() !== got.m - 1 || day.getDate() !== got.d) return null;
    var time = /^\d{1,2}:\d{2}/.test(parts[1] || "") ? parts[1].slice(0, 5) : "";
    return { y: got.y, m: got.m, d: got.d, time: time.length === 4 ? "0" + time : time };
  }

  function show(y, m, d) {
    var by = { y: pad(y, 4), m: pad(m, 2), d: pad(d, 2) };
    return style.order.split("").map(function (k) { return by[k]; }).join(style.sep);
  }

  function upgrade(box) {
    var withTime = box.hasAttribute("data-time");
    var native = document.createElement("input");
    native.type = withTime ? "datetime-local" : "date";
    native.tabIndex = -1;
    native.setAttribute("aria-hidden", "true");
    native.className = "date-native";
    var button = document.createElement("button");
    button.type = "button";
    button.className = "date-pick";
    button.title = "Pick from a calendar";
    button.setAttribute("aria-label", "Pick from a calendar");
    button.innerHTML = '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><rect x="2" y="3" width="12" height="11" rx="2" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M2 7h12M5 1.5v3M11 1.5v3" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>';
    var wrap = document.createElement("span");
    wrap.className = "date-wrap";
    box.parentNode.insertBefore(wrap, box);
    wrap.appendChild(box);
    wrap.appendChild(button);
    wrap.appendChild(native);

    button.addEventListener("click", function () {
      var got = parse(box.value);
      native.value = got ? pad(got.y, 4) + "-" + pad(got.m, 2) + "-" + pad(got.d, 2) +
        (withTime ? "T" + (got.time || "00:00") : "") : "";
      if (native.showPicker) { try { native.showPicker(); } catch (e) { native.focus(); } }
      else native.focus();
    });
    native.addEventListener("change", function () {
      var v = native.value;
      if (!v) return;
      var day = v.slice(0, 10).split("-");
      box.value = show(parseInt(day[0], 10), parseInt(day[1], 10), parseInt(day[2], 10)) +
        (withTime ? " " + (v.slice(11, 16) || "00:00") : "");
      box.dispatchEvent(new Event("input", { bubbles: true }));
      box.dispatchEvent(new Event("change", { bubbles: true }));
      box.focus();
    });
  }

  function init() { Array.prototype.forEach.call(document.querySelectorAll("input.date-input"), upgrade); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
