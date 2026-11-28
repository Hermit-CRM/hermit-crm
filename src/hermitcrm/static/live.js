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

/* Actions without a page reload. A form with data-live is sent with fetch
 * instead of a page load: the server answers as it always does (a 303 to the
 * page, or the page again with its error messages), and this script puts the
 * changed part of that answer in place of the same part of this page. It also
 * lets a card on the board be dragged to another stage (see the end).
 *
 *   data-live                      replaces <main>
 *   data-live="#tasks, .x"         replaces every element on this page that
 *                                  matches one of the selectors (the outermost
 *                                  ones), each with its twin in the answer;
 *                                  <main> when none of them is on this page
 *   data-live-change               a change to any field sends the form (the
 *                                  board's stage select): it stands in for an
 *                                  inline onchange="this.form.submit()"
 *
 * The answer's flash line becomes a toast in #toasts (with the Undo form under
 * that line, templates/undo_form.html, when it has one), the address bar shows the
 * answer's address without ?flash=, scroll and focus stay where they were, and
 * a "hermit:swap" event on document tells the other scripts to look at the new
 * part (event.detail.regions). It falls back to the ordinary page load whenever
 * it cannot do better: an answer for another page, a part the answer does not
 * have or that holds a <script>, a network failure or an answer that is not a
 * page. The route handlers know nothing of this, and without this script every
 * form is an ordinary form. No dependencies. */
(function () {
  "use strict";
  if (!window.fetch || !window.DOMParser || !window.FormData || !window.URLSearchParams ||
      !Element.prototype.closest) return;

  var TOAST_MS = 6000;      // how long a toast stays (paused while hovered or focused)
  var TOASTS_KEPT = 3;      // older ones go when a fourth arrives
  var skip = null;          // the form handed back to the browser, sent the ordinary way

  function reduced() {
    return !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  }

  /* ---------------------------------------------------------------- toasts */

  function toast(text, undo) {
    var box = document.getElementById("toasts");
    if (!box || !text) return;
    var item = document.createElement("div");
    item.className = "toast";
    var words = document.createElement("span");
    words.className = "toast-text";
    words.textContent = text;
    var close = document.createElement("button");
    close.type = "button";
    close.className = "toast-close";
    close.setAttribute("aria-label", "Dismiss");
    close.textContent = "\u00d7";
    item.appendChild(words);
    if (undo) {                         // sent like any data-live form; a page whose <main>
      undo.setAttribute("data-live", ""); // cannot be swapped loads in full, as for any other
      undo.removeAttribute("style");    // the spacing it has under the flash line
      item.appendChild(undo);
    }
    item.appendChild(close);
    var old = box.querySelectorAll(".toast");
    for (var i = 0; i <= old.length - TOASTS_KEPT; i++) old[i].remove();
    box.appendChild(item);

    var timer = null;
    function gone() { if (item.parentNode) item.remove(); }
    function leave() {
      if (reduced()) { gone(); return; }
      item.classList.add("is-leaving");
      setTimeout(gone, 250);    // the fade in live.css takes 200 ms
    }
    function arm() { clearTimeout(timer); timer = setTimeout(leave, TOAST_MS); }
    function hold() { clearTimeout(timer); item.classList.remove("is-leaving"); }
    item.addEventListener("mouseenter", hold);
    item.addEventListener("focusin", hold);
    item.addEventListener("mouseleave", function () { if (!item.contains(document.activeElement)) arm(); });
    item.addEventListener("focusout", function (event) {
      if (!item.contains(event.relatedTarget) && !item.matches(":hover")) arm();
    });
    close.addEventListener("click", function () { clearTimeout(timer); gone(); });
    arm();
  }

  /* --------------------------------------------------------------- regions */

  function selectors(form) {
    return (form.getAttribute("data-live") || "").split(",")
      .map(function (s) { return s.trim(); })
      .filter(Boolean);
  }

  function all(root, selector) {
    try { return Array.prototype.slice.call(root.querySelectorAll(selector)); }
    catch (e) { return []; }    // a selector the browser cannot read matches nothing
  }

  /* The parts of this page the form's answer replaces: [{el, sel, index}],
     outermost only, <main> when no selector matches. */
  function regions(form) {
    var found = [];
    selectors(form).forEach(function (sel) {
      all(document, sel).forEach(function (el, index) {
        if (!found.some(function (f) { return f.el === el; })) found.push({ el: el, sel: sel, index: index });
      });
    });
    found = found.filter(function (a) {
      return !found.some(function (b) { return b.el !== a.el && b.el.contains(a.el); });
    });
    if (!found.length) {
      var main = document.querySelector("main");
      if (main) found.push({ el: main, sel: "main", index: 0 });
    }
    return found;
  }

  // The same part in the answer: by id when it has one, else the n-th match.
  function twin(doc, region) {
    if (region.el.id) return doc.getElementById(region.el.id);
    return all(doc, region.sel)[region.index] || null;
  }

  // An inserted <script> does not run, so a part that holds one is not swapped.
  function hasScript(el) {
    return !!el.querySelector('script:not([type="application/json"])');
  }

  /* ----------------------------------------------------------------- focus */

  function attr(value) { return window.CSS && CSS.escape ? CSS.escape(value) : value.replace(/["\\]/g, "\\$&"); }

  // A form's fingerprint: its method, id, action and hidden fields (the task's
  // index and text), as several rows post to the same address and a filter
  // form can share it too.
  function signature(form) {
    return (form.getAttribute("method") || "get").toLowerCase() + " " + form.id + " " +
      (form.getAttribute("action") || "") + "|" +
      all(form, 'input[type="hidden"]').filter(function (i) { return i.name !== "back"; })
        .map(function (i) { return i.name + "=" + i.value; }).join("&");
  }

  // Where focus is (or, as Safari does not focus a clicked button, the button
  // that was pressed), described so its twin can be found in the new part.
  function describe(form, submitter) {
    var el = document.activeElement;
    if (!el || !form.contains(el)) el = submitter || form;    // focus elsewhere is not this form's
    var owner = el.tagName === "FORM" ? el : el.form || el.closest("form") || form;
    var action = owner.getAttribute("action") || "";
    return {
      id: el.id || "",
      action: action,
      sig: signature(owner),
      nth: all(document, 'form[action="' + attr(action) + '"]').indexOf(owner),
      name: el.tagName === "FORM" ? "" : el.getAttribute("name") || "",
      button: el.tagName === "BUTTON" || el.type === "submit"
    };
  }

  function focusable(el) {
    var shut = el.closest("details:not([open])");    // a folded-away field: its summary instead
    if (shut && !(el.tagName === "SUMMARY" && el.parentNode === shut)) return shut.querySelector("summary");
    return el;
  }

  function twinForm(was, fresh) {
    var forms = [];
    fresh.forEach(function (region) { forms = forms.concat(all(region, 'form[action="' + attr(was.action) + '"]')); });
    var same = forms.filter(function (f) { return signature(f) === was.sig; });
    if (same.length) return same[0];
    // The fields changed (an edited text, a task now done): the one in the same place.
    var everywhere = all(document, 'form[action="' + attr(was.action) + '"]');
    var nth = everywhere[was.nth];
    return nth && forms.indexOf(nth) !== -1 ? nth : forms[0] || null;
  }

  function refocus(was, fresh, error) {
    var spot = null;
    if (error) {
      fresh.some(function (region) {
        spot = region.querySelector('[role="alert"], .errors');
        return !!spot;
      });
      if (spot && !spot.hasAttribute("tabindex")) spot.setAttribute("tabindex", "-1");
    }
    if (!spot && was.id) spot = document.getElementById(was.id);
    if (!spot && was.action) {
      var form = twinForm(was, fresh);
      if (form) {
        spot = (was.name && form.querySelector('[name="' + attr(was.name) + '"]:not([type="hidden"])')) ||
          (was.button && form.querySelector('button[type="submit"], button:not([type]), input[type="submit"]')) ||
          form.querySelector('button, input:not([type="hidden"]), select, textarea');
      }
    }
    if (spot) spot = focusable(spot);
    if (spot) { try { spot.focus({ preventScroll: true }); } catch (e) { spot.focus(); } }
    if ((!spot || document.activeElement !== spot) && fresh.length) {
      spot = fresh[0];    // the form went (a deleted task): keep focus in the part, not on <body>
      if (!spot.hasAttribute("tabindex")) spot.setAttribute("tabindex", "-1");
      try { spot.focus({ preventScroll: true }); } catch (e) { spot.focus(); }
    }
  }

  /* ------------------------------------------------------------------ send */

  // Back to the browser: the form is sent the ordinary way, as if this script
  // were not here. Only for what has not reached the server, or was refused.
  function resubmit(form, submitter) {
    skip = form;
    if (form.requestSubmit) {
      try { form.requestSubmit(submitter && submitter.form === form ? submitter : undefined); return; }
      catch (e) { /* fall through */ }
    }
    form.submit();
  }

  function formData(form, submitter) {
    var data;
    try { data = new FormData(form, submitter || undefined); }
    catch (e) {
      data = new FormData(form);
      if (submitter && submitter.name) data.append(submitter.name, submitter.value);
    }
    return data;
  }

  function idle(form, parts) {
    form.classList.remove("live-busy");
    parts.forEach(function (p) { p.el.removeAttribute("aria-busy"); });
  }

  function send(form, submitter) {
    if (form.classList.contains("live-busy")) return;    // the first click is still on its way
    var method = ((submitter && submitter.getAttribute("formmethod")) || form.getAttribute("method") || "get").toUpperCase();
    var action = submitter && submitter.hasAttribute("formaction") ? submitter.formAction : form.action;
    var enctype = (submitter && submitter.getAttribute("formenctype")) || form.getAttribute("enctype") || "";
    var data = formData(form, submitter);
    var init = { method: method, credentials: "same-origin", headers: { Accept: "text/html" } };
    var url = action;
    if (method === "GET") {
      var u = new URL(action, location.href);
      u.search = new URLSearchParams(data).toString();
      url = u.href;
    } else if (enctype === "multipart/form-data") {
      init.body = data;
    } else {
      init.body = new URLSearchParams(data);
    }

    var parts = regions(form);
    if (!parts.length) { resubmit(form, submitter); return; }
    var state = { focus: describe(form, submitter), x: window.scrollX, y: window.scrollY };
    form.classList.add("live-busy");
    parts.forEach(function (p) { p.el.setAttribute("aria-busy", "true"); });

    fetch(url, init).then(function (response) {
      var type = response.headers.get("content-type") || "";
      if (type.indexOf("text/html") === -1) {
        idle(form, parts);
        // A redirect was followed, so the action is done: show where it went.
        if (response.redirected || method === "GET") location.assign(response.url);
        else resubmit(form, submitter);
        return null;
      }
      return response.text().then(function (html) {
        idle(form, parts);
        apply(form, submitter, response, html, parts, state);
      });
    }, function () {
      idle(form, parts);
      resubmit(form, submitter);    // the request did not get through: nothing was saved
    }).catch(function () {
      location.reload();            // a swap that broke half-way: show the page as it is now
    });
  }

  function apply(form, submitter, response, html, parts, state) {
    var doc = new DOMParser().parseFromString(html, "text/html");
    var sent = form.closest(".toast");    // its Undo was pressed: that toast has had its say
    if (sent && !(response.status >= 400)) sent.remove();
    var final = new URL(response.url || location.href);
    var error = response.status >= 400;
    // A success that lands on another page (a lost stage that needs its reason,
    // a move the stage rules refuse) is shown as that page.
    if (!error && final.pathname !== location.pathname) { location.assign(final.href); return; }

    var pairs = [];
    var whole = parts.every(function (p) {
      var fresh = twin(doc, p);
      if (!fresh || hasScript(fresh)) return false;
      pairs.push({ el: p.el, fresh: fresh });
      return true;
    });
    if (!whole) {
      // The page is fine but this script cannot show it in place.
      if (error) resubmit(form, submitter);    // refused, so nothing was saved: send it again for real
      else location.assign(final.href);
      return;
    }

    var flash = doc.querySelector("main p.flash");
    var message = flash ? flash.textContent.trim() : (final.searchParams.get("flash") || "");
    var undo = doc.querySelector("main form.flash-undo");
    all(document, "main p.flash, main form.flash-undo").forEach(function (p) { p.remove(); });    // an older message
    pairs.forEach(function (pair) {
      all(pair.fresh, "p.flash, form.flash-undo").forEach(function (p) { p.remove(); });
      var scrollers = all(pair.el, ".table-scroll, .board");
      var offsets = scrollers.map(function (s) { return [s.scrollLeft, s.scrollTop]; });
      var own = [pair.el.scrollLeft, pair.el.scrollTop];
      pair.el.replaceWith(pair.fresh);
      pair.fresh.scrollLeft = own[0];
      pair.fresh.scrollTop = own[1];
      all(pair.fresh, ".table-scroll, .board").forEach(function (s, i) {
        if (offsets[i]) { s.scrollLeft = offsets[i][0]; s.scrollTop = offsets[i][1]; }
      });
    });
    if (doc.title) document.title = doc.title;
    if (!error) {
      final.searchParams.delete("flash");
      history.replaceState(history.state, "", final.pathname + final.search + location.hash);
    }
    window.scrollTo(state.x, state.y);
    var fresh = pairs.map(function (p) { return p.fresh; });
    refocus(state.focus, fresh, error);
    if (message) toast(message, undo && message ? document.importNode(undo, true) : null);
    document.dispatchEvent(new CustomEvent("hermit:swap", {
      detail: { regions: fresh, url: location.href, status: response.status }
    }));
  }

  /* ---------------------------------------------------------------- events */

  // Bubble phase on document: busy.js and any form's own handler have had
  // their say, and a handler that stopped the submit is respected.
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (form === skip) { skip = null; return; }
    if (event.defaultPrevented || !form.matches || !form.matches("form[data-live]")) return;
    if (form.target && form.target !== "_self") return;
    event.preventDefault();
    send(form, event.submitter || null);
  });

  // data-live-change: the capture phase runs before the field's own inline
  // onchange (which would call form.submit() and load the page), so it is
  // stopped here and the form goes through the submit event above.
  document.addEventListener("change", function (event) {
    var field = event.target;
    var form = field && field.form;
    if (!form || !form.matches("form[data-live][data-live-change]")) return;
    event.stopPropagation();
    if (form.requestSubmit) form.requestSubmit();
    else send(form, null);
  }, true);

  /* ------------------------------------------------- board: drag and drop */

  // A card on the board can be dragged to another stage's column. The drop
  // only sets the card's own stage <select> and sends its form, the same way
  // as picking the stage from the list: the select stays the keyboard way,
  // and whatever the server answers (a reason needed, a move the stage rules
  // refuse) is shown as it would be then. No library.
  var dragged = null;

  function cardForm(card) { return card && card.querySelector("form.stage-form[data-live]"); }

  function makeDraggable() {
    all(document, ".board .card").forEach(function (card) {
      if (cardForm(card)) card.setAttribute("draggable", "true");
    });
  }

  function columnStage(column, select) {
    var stage = column.id.replace(/^col-/, "");
    var known = Array.prototype.some.call(select.options, function (o) { return o.value === stage; });
    return known ? stage : null;
  }

  function clearDrag() {
    all(document, ".board .is-drop-target").forEach(function (c) { c.classList.remove("is-drop-target"); });
    all(document, ".board.is-dragging").forEach(function (b) { b.classList.remove("is-dragging"); });
    if (dragged) dragged.classList.remove("is-dragged");
    dragged = null;
  }

  document.addEventListener("dragstart", function (event) {
    var card = event.target.closest && event.target.closest(".board .card[draggable]");
    if (!card || !cardForm(card)) return;
    dragged = card;
    event.dataTransfer.effectAllowed = "move";
    var name = card.querySelector("h3");
    event.dataTransfer.setData("text/plain", name ? name.textContent.trim() : "");
    card.classList.add("is-dragged");
    card.closest(".board").classList.add("is-dragging");
  });

  document.addEventListener("dragover", function (event) {
    if (!dragged) return;
    var column = event.target.closest && event.target.closest(".board .column[id^='col-']");
    all(document, ".board .is-drop-target").forEach(function (c) {
      if (c !== column) c.classList.remove("is-drop-target");
    });
    if (!column || column.contains(dragged)) return;
    event.preventDefault();               // this column takes the card
    event.dataTransfer.dropEffect = "move";
    column.classList.add("is-drop-target");
  });

  document.addEventListener("drop", function (event) {
    if (!dragged) return;
    var card = dragged;
    var column = event.target.closest && event.target.closest(".board .column[id^='col-']");
    clearDrag();
    if (!column || column.contains(card)) return;
    event.preventDefault();
    var form = cardForm(card);
    var select = form && form.querySelector("select[name='stage']");
    var stage = select && columnStage(column, select);
    if (!stage || stage === select.value) return;
    select.value = stage;
    column.appendChild(card);             // shown in its new place at once; the answer redraws the board
    if (form.requestSubmit) form.requestSubmit();
    else send(form, null);
  });

  document.addEventListener("dragend", clearDrag);

  makeDraggable();
  document.addEventListener("hermit:swap", makeDraggable);

  window.Hermit = window.Hermit || {};
  window.Hermit.toast = toast;    // for other scripts that want to say something briefly
})();

/* Live sync. Every change to the data folder is a git commit, whoever makes
 * it: the command line, an agent over MCP, the daily sync, an editor's commit.
 * So every POLL_MS while this tab is visible this asks /live/head.json what
 * HEAD is, and when that differs from what the page was shown at, and the
 * change was not a form sent from this tab, the page follows:
 *
 *   nothing on it is being edited   <main> is fetched again and put in place
 *                                   (scroll, open <details> and focus kept;
 *                                   "hermit:swap" with detail.sync is fired).
 *                                   A part that holds an inline <script> (the
 *                                   company page's record form) stays as it is
 *                                   while its fields are the same; when they
 *                                   are not, the page is loaded again
 *   a field in <main> differs from  a toast "This page changed underneath
 *   what the page came with, an     you" with a Refresh button; nothing on
 *   error is shown, or the page is  the page is touched
 *   the answer to a form sent the
 *   ordinary way (a preview its
 *   address cannot show again)
 *
 * Polling stops while the tab is hidden and asks at once when it is shown
 * again. The server reloads its records on the page request itself
 * (refresh_if_moved in web.py); /live/ is skipped by that sweep, so a poll
 * starts no process. Without fetch, nothing here runs and the sidebar's
 * Reload button does the job by hand. */
(function () {
  "use strict";
  if (!window.fetch || !window.DOMParser || !window.URL || !document.querySelector("main") ||
      typeof document.visibilityState === "undefined") return;

  var POLL_MS = 5000;
  var OWN_MS = 15000;         // after a form is sent from here, a new HEAD is that form's own for this long
  var POSTED_KEY = "hermit-posted";
  var known = null;           // the HEAD this page shows; null until the first answer
  var seq = 0;                // only the newest question's answer counts
  var timer = null;
  var ownUntil = 0;
  var refreshing = false;
  var notice = null;          // the "changed underneath you" toast while it is up
  var posted = wasPosted();

  function all(root, selector) { return Array.prototype.slice.call(root.querySelectorAll(selector)); }

  function address() {
    var url = new URL(location.href);
    url.searchParams.delete("flash");    // a message shown once, not again on every refresh
    return url.href;
  }

  /* A page that answers a POST sent the ordinary way (an import preview, a
     form shown again with its errors) cannot be fetched again by its address:
     the submit listener below notes where such a form went, and a page at
     that address reached without a redirect is that answer. */
  function wasPosted() {
    var note = null;
    try {
      note = JSON.parse(sessionStorage.getItem(POSTED_KEY) || "null");
      sessionStorage.removeItem(POSTED_KEY);
    } catch (e) { return false; }
    if (!note || typeof note.t !== "number" || Date.now() - note.t > 60000) return false;
    var timing = window.performance;
    var nav = timing && timing.getEntriesByType && timing.getEntriesByType("navigation")[0];
    if (nav && nav.redirectCount) return false;    // a 303 to a page: that page is an ordinary GET
    return note.path === location.pathname;
  }

  /* ------------------------------------------------- is anything edited */

  function selectChanged(select) {
    var options = Array.prototype.slice.call(select.options);
    if (select.multiple) return options.some(function (o) { return o.selected !== o.defaultSelected; });
    var start = -1;
    options.forEach(function (o, i) { if (o.defaultSelected) start = i; });
    return select.selectedIndex !== (start === -1 ? (options.length ? 0 : -1) : start);
  }

  function fieldChanged(field) {
    if (field.disabled) return false;
    var type = (field.type || "").toLowerCase();
    if (field.tagName === "SELECT") return selectChanged(field);
    if (/^(hidden|submit|button|reset|image)$/.test(type)) return false;
    if (type === "checkbox" || type === "radio") return field.checked !== field.defaultChecked;
    if (type === "file") return !!(field.files && field.files.length);
    return field.value !== field.defaultValue;
  }

  // Whether refreshing <main> could lose something: a changed field, or an
  // error message (a form shown again with what the user typed in it).
  function edited(main) {
    if (main.querySelector('[role="alert"], .errors')) return true;
    if (main.querySelector('[contenteditable="true"], [contenteditable=""]')) return true;
    return all(main, "input, textarea, select").some(fieldChanged);
  }

  /* ---------------------------------------------------------- following */

  function warn() {
    var box = document.getElementById("toasts");
    if (!box || (notice && notice.parentNode)) return;
    var item = document.createElement("div");
    item.className = "toast toast-sync";
    var words = document.createElement("span");
    words.className = "toast-text";
    words.textContent = "This page changed underneath you.";
    var again = document.createElement("button");
    again.type = "button";
    again.textContent = "Refresh";
    again.title = "Show the page as it is now; what you typed here is not kept";
    var close = document.createElement("button");
    close.type = "button";
    close.className = "toast-close";
    close.setAttribute("aria-label", "Dismiss");
    close.textContent = "×";
    item.appendChild(words);
    item.appendChild(again);
    item.appendChild(close);
    again.addEventListener("click", function () { location.assign(address()); });
    close.addEventListener("click", function () { item.remove(); });
    box.appendChild(item);    // it stays until it is answered: no timer
    notice = item;
  }

  var SCRIPT = 'script:not([type="application/json"])';

  function scripted(el) { return el.matches(SCRIPT) || !!el.querySelector(SCRIPT); }

  // A part's fields as the server wrote them. A script may have shown or
  // hidden things since, or added a helper field of its own (one without a
  // name, which a form never sends); it does not change these.
  function fieldsOf(el) {
    return all(el, "input[name], textarea[name], select[name]").map(function (f) {
      var type = (f.type || "").toLowerCase();
      if (f.tagName === "SELECT") {
        return f.name + "=" + Array.prototype.filter.call(f.options, function (o) { return o.defaultSelected; })
          .map(function (o) { return o.value; }).join("|");
      }
      if (type === "checkbox" || type === "radio") return f.name + "=" + f.value + ":" + f.defaultChecked;
      return f.name + "=" + f.defaultValue;
    }).join("\n");
  }

  /* What to put in place: [{el, fresh}]: the whole <main> when neither holds
     a script (an inserted one would not run), else each of its children that
     holds none. A child with a script stays when its fields are the same in
     both; when they are not, or the children do not line up, null. */
  function pairs(main, fresh) {
    if (!scripted(main) && !scripted(fresh)) return [{ el: main, fresh: fresh }];
    function kids(el) {    // an old message is not a part: the new page has none
      return Array.prototype.filter.call(el.children, function (c) { return !c.matches("p.flash"); });
    }
    var olds = kids(main), news = kids(fresh);
    all(main, ":scope > p.flash").forEach(function (p) { p.remove(); });
    if (olds.length !== news.length) return null;
    var out = [];
    for (var i = 0; i < olds.length; i++) {
      var a = olds[i], b = news[i];
      if (a.tagName !== b.tagName || a.id !== b.id) return null;
      if (scripted(a) || scripted(b)) {
        if (!scripted(a) || !scripted(b) || fieldsOf(a) !== fieldsOf(b)) return null;
        continue;    // the same fields: it stays, with what its script set up
      }
      out.push({ el: a, fresh: b });
    }
    return out;
  }

  function swap(parts, doc) {
    var x = window.scrollX, y = window.scrollY;
    var focused = document.activeElement;
    var lost = null;    // the new part that took the place of the one focus was in
    parts.forEach(function (pair) {
      all(pair.fresh, "p.flash").forEach(function (p) { p.remove(); });
      var offsets = all(pair.el, ".table-scroll, .board").map(function (s) { return [s.scrollLeft, s.scrollTop]; });
      var open = all(pair.el, "details").map(function (d) { return d.open; });
      if (pair.el.tagName === "DETAILS") open.unshift(pair.el.open);
      if (focused && focused !== document.body && pair.el.contains(focused)) lost = pair.fresh;
      pair.el.replaceWith(pair.fresh);
      var details = all(pair.fresh, "details");
      if (pair.fresh.tagName === "DETAILS") details.unshift(pair.fresh);
      if (details.length === open.length) details.forEach(function (d, i) { d.open = open[i]; });
      all(pair.fresh, ".table-scroll, .board").forEach(function (s, i) {
        if (offsets[i]) { s.scrollLeft = offsets[i][0]; s.scrollTop = offsets[i][1]; }
      });
    });
    if (doc.title) document.title = doc.title;
    window.scrollTo(x, y);
    if (lost) {    // what had focus was replaced: its twin, else the new part (never <body>)
      var spot = (focused.id && document.getElementById(focused.id)) || lost;
      if (spot === lost && !lost.hasAttribute("tabindex")) lost.setAttribute("tabindex", "-1");
      try { spot.focus({ preventScroll: true }); } catch (e) { spot.focus(); }
    }
    document.dispatchEvent(new CustomEvent("hermit:swap", {
      detail: { regions: parts.map(function (p) { return p.fresh; }), url: location.href, status: 200, sync: true }
    }));
  }

  function refresh(head) {
    if (refreshing) return;
    refreshing = true;
    fetch(address(), { credentials: "same-origin", headers: { Accept: "text/html" }, cache: "no-store" })
      .then(function (response) {
        var type = response.headers.get("content-type") || "";
        var same = new URL(response.url || location.href).pathname === location.pathname;
        return response.ok && same && type.indexOf("text/html") !== -1 ? response.text() : null;
      })
      .then(function (html) {
        refreshing = false;
        var main = document.querySelector("main");
        var doc = html === null ? null : new DOMParser().parseFromString(html, "text/html");
        var fresh = doc && doc.querySelector("main");
        known = head;
        // Not this page any more (gone, moved), or something typed while the
        // answer was on its way: say so, and leave the page alone.
        if (!main || !fresh || edited(main)) { warn(); return; }
        var parts = pairs(main, fresh);
        if (parts) { swap(parts, doc); return; }
        // A part with a script changed. Nothing here is edited, so nothing is
        // lost by loading the whole page again (the browser keeps the scroll).
        if (location.href === address()) location.reload();
        else location.replace(address());
      }, function () { refreshing = false; });    // no answer: the next poll tries again
  }

  function follow(head) {
    var main = document.querySelector("main");
    if (!main || posted || edited(main)) { known = head; warn(); return; }
    refresh(head);
  }

  function ask(adopt) {
    var mine = ++seq;
    fetch("/live/head.json", { credentials: "same-origin", headers: { Accept: "application/json" },
                               cache: "no-store" })
      .then(function (response) { return response.ok ? response.json() : null; })
      .then(function (data) {
        if (mine !== seq || !data || typeof data.head !== "string") return;
        if (known === null || adopt) { known = data.head; return; }
        if (data.head === known) return;
        // This tab's own change, its answer still on the way: the swap adopts it.
        if (Date.now() < ownUntil || document.querySelector("form.live-busy")) return;
        follow(data.head);
      })
      .catch(function () { /* the server is restarting (an upgrade): ask again next time */ });
  }

  /* ------------------------------------------------------------- timing */

  function stop() { clearTimeout(timer); timer = null; }

  function tick() {
    stop();
    if (document.visibilityState !== "visible") return;
    ask(false);
    timer = setTimeout(tick, POLL_MS);
  }

  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible") tick();
    else stop();
  });
  window.addEventListener("pagehide", stop);
  window.addEventListener("pageshow", function (event) { if (event.persisted) tick(); });

  // A form sent from this tab: the commit it makes is this tab's own. On
  // window, so it runs after live.js's own submit handler has had its say: a
  // data-live form stays on this page (defaultPrevented), any other POST
  // loads its answer, which wasPosted() then recognises.
  window.addEventListener("submit", function (event) {
    var form = event.target, submitter = event.submitter;
    var method = ((submitter && submitter.getAttribute("formmethod")) || form.getAttribute("method") || "get").toLowerCase();
    if (method !== "post") return;    // a search or a filter changes nothing
    ownUntil = Date.now() + OWN_MS;
    if (event.defaultPrevented) return;
    try {
      var action = submitter && submitter.hasAttribute("formaction") ? submitter.formAction : form.action;
      sessionStorage.setItem(POSTED_KEY, JSON.stringify({ path: new URL(action, location.href).pathname, t: Date.now() }));
    } catch (e) { /* no storage: such a page is refreshed like any other */ }
  });

  // A swap after this tab's own action shows the folder as it is now.
  document.addEventListener("hermit:swap", function (event) {
    if (event.detail && event.detail.sync) return;
    ownUntil = 0;
    ask(true);
  });

  ask(true);    // what this page shows
  timer = setTimeout(tick, POLL_MS);
  if (document.visibilityState !== "visible") stop();
})();
