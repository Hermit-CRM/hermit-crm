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

// The home page's only script. It is a file, not inline, so the site's
// Content-Security-Policy can say script-src 'self' (nginx.conf).

// Copy button: shown only when scripts run. "Copied" only when the copy
// worked; otherwise the message is selected and the button says how to copy.
document.querySelectorAll("[data-copy]").forEach(function (btn) {
  var label = btn.querySelector("span"), idle = label.textContent, timer;
  var message = document.getElementById("install-message");
  btn.hidden = false;
  function show(text, ms, state) {
    label.textContent = text;
    if (state) btn.dataset.state = state; else delete btn.dataset.state;
    clearTimeout(timer);
    timer = setTimeout(function () { label.textContent = idle; delete btn.dataset.state; }, ms);
  }
  function done() { show(btn.dataset.done, 2000, "done"); }
  function failed() {
    var range = document.createRange(), sel = window.getSelection();
    range.selectNodeContents(message); sel.removeAllRanges(); sel.addRange(range);
    show(btn.dataset.failed, 4000);
  }
  function fallback(text) {
    var t = document.createElement("textarea"), ok = false;
    t.value = text; t.setAttribute("readonly", ""); t.style.position = "fixed"; t.style.opacity = "0";
    document.body.appendChild(t); t.select();
    try { ok = document.execCommand("copy"); } catch (e) {}
    document.body.removeChild(t);
    ok ? done() : failed();
  }
  btn.addEventListener("click", function () {
    var text = btn.dataset.copy;
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(done, function () { fallback(text); });
    } else { fallback(text); }
  });
});
// Printing: open every answer, then put them back as they were.
var shut = [];
addEventListener("beforeprint", function () {
  shut = [].filter.call(document.querySelectorAll("details"), function (d) { return !d.open; });
  shut.forEach(function (d) { d.open = true; });
});
addEventListener("afterprint", function () { shut.forEach(function (d) { d.open = false; }); });
