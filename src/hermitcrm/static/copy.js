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

/* One click copies a short text. A button with data-copy-text="..." (an email
 * address next to its mailto link) puts that text on the clipboard and says
 * "copied" for a moment. The page works without this script: the address is
 * still a link you can click or select.
 * No dependencies. */
(function () {
  "use strict";

  function copy(text, done) {
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(function () { done(true); },
                                               function () { done(false); });
      return;
    }
    var area = document.createElement("textarea");
    area.value = text;
    document.body.appendChild(area);
    area.select();
    var ok = false;
    try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
    area.remove();
    done(ok);
  }

  document.addEventListener("click", function (event) {
    var button = event.target.closest && event.target.closest("[data-copy-text]");
    if (!button) return;
    event.preventDefault();
    var idle = button.dataset.idleText || button.textContent;
    button.dataset.idleText = idle;
    copy(button.getAttribute("data-copy-text"), function (ok) {
      button.textContent = ok ? "copied" : "copy failed";
      setTimeout(function () { button.textContent = idle; }, 1500);
    });
  });
})();
