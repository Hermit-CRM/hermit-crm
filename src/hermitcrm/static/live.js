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
