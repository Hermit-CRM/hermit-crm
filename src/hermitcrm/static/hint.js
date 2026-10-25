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

/* A hint's tip (the "?" macro) hangs from its "?". Where the "?" ends a long line
 * the tip would run past the right edge of the window, so on hover or focus it is
 * shifted left just far enough to fit, and stays under the "?". On a phone the tip
 * is a sheet along the bottom and is left alone. The hints work without this script.
 * No dependencies. */
(function () {
  "use strict";

  var GUTTER = 12;

  function fit(hint) {
    var tip = hint.querySelector(".tip");
    if (!tip) return;
    tip.style.left = "";
    if (getComputedStyle(tip).position === "fixed") return;
    var shown = tip.style.display;
    tip.style.display = "block";   // measured while still hidden, then handed back to the stylesheet
    var over = tip.getBoundingClientRect().right - (document.documentElement.clientWidth - GUTTER);
    tip.style.display = shown;
    if (over > 0) tip.style.left = -over + "px";
  }

  function enter(event) {
    var hint = event.target.closest && event.target.closest(".hint");
    if (hint && !(event.relatedTarget && hint.contains(event.relatedTarget))) fit(hint);
  }

  document.addEventListener("mouseover", enter);
  document.addEventListener("focusin", enter);
})();
