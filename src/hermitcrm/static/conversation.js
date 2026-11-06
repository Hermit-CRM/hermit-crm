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

// The page the "Hermit: conversation" bookmark opens (/extension/conversation).
//
// The bookmark ran in the person's own LinkedIn tab and opened this one. This
// page asks that tab for the conversation (postMessage 'ready'), takes the
// answer only when it comes from https://www.linkedin.com and from the tab that
// opened this one, and keeps it in a variable. Nothing is put in a URL, in
// storage or in a cookie, and the server keeps nothing between requests: every
// preview and the import send the conversation again and the server reads it
// afresh. The review is server-rendered HTML (everything escaped there), put on
// the page by parsing it, never by assigning markup to an element.
(function () {
  'use strict';
  var LINKEDIN = 'https://www.linkedin.com';
  var WAIT_MS = 6000;
  var root = document.getElementById('conversation');
  var status = document.getElementById('conversation-status');
  var review = document.getElementById('conversation-review');
  if (!root || !status || !review) { return; }
  var PREVIEW = root.dataset.preview;
  var IMPORT = root.dataset.import;
  var CSRF = root.dataset.csrf;

  var NOTHING = 'Hermit did not receive the conversation. Go back to the LinkedIn tab with the ' +
    'conversation open and click the “Hermit: conversation” bookmark again. ' +
    'This page only works when that bookmark opens it. If you have not taken the bookmark ' +
    'yet, or it stopped working, take it again from the Extension page.';

  var state = null;       // the conversation and the person's answers so far
  var received = false;
  var timer = null;
  var latest = 0;         // a slow answer to an older request must not replace a newer one

  function say(text) {
    status.textContent = text;
    status.hidden = !text;
  }

  function post(url, body) {
    return fetch(url, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
  }

  function request() {
    return {
      payload: state.payload, contact: state.contact, dates: state.dates,
      directions: state.directions, ticks: state.ticks
    };
  }

  function reason(text) {
    try {
      var found = JSON.parse(text);
      if (found && typeof found.detail === 'string') { return found.detail; }
    } catch (e) { /* plain text */ }
    return text;
  }

  function refresh() {
    var mine = ++latest;
    post(PREVIEW, request()).then(function (response) {
      return response.text().then(function (text) {
        return { ok: response.ok, status: response.status, text: text };
      });
    }).then(function (answer) {
      if (mine !== latest) { return; }
      if (!answer.ok) {
        say(answer.status === 413
          ? 'This conversation is too big for Hermit to take in at once.'
          : 'Hermit could not show this conversation: ' + reason(answer.text));
        return;
      }
      show(answer.text);
    }).catch(function () {
      say('Hermit could not be reached. Is it still running?');
    });
  }

  function show(html) {
    var parsed = new DOMParser().parseFromString(html, 'text/html');
    review.replaceChildren.apply(review, Array.prototype.slice.call(parsed.body.childNodes));
    say('');
    var select = review.querySelector('#cv-contact');
    if (select && select.value) { state.contact = select.value; }
    count();
  }

  function boxes() {
    return Array.prototype.slice.call(review.querySelectorAll('.cv-tick'));
  }

  function count() {
    var button = review.querySelector('[data-action="import"]');
    if (!button) { return; }
    var n = boxes().filter(function (box) { return box.checked && !box.disabled; }).length;
    button.textContent = 'Import ' + n + (n === 1 ? ' message' : ' messages');
    button.disabled = n === 0;
  }

  function importNow(button) {
    var ticked = boxes().filter(function (box) { return box.checked && !box.disabled; })
      .map(function (box) { return Number(box.dataset.index); });
    var body = request();
    body.ticked = ticked;
    body.csrf_token = CSRF;
    delete body.ticks;
    button.disabled = true;
    say('Importing…');
    post(IMPORT, body).then(function (response) {
      if (response.ok && response.redirected &&
          response.url.indexOf(window.location.origin + '/') === 0) {
        window.location.assign(response.url);   // the contact, with the flash
        return null;
      }
      return response.text().then(function (text) {
        say('Nothing was imported: ' + reason(text));
        button.disabled = false;
      });
    }).catch(function () {
      say('Hermit could not be reached. Is it still running?');
      button.disabled = false;
    });
  }

  review.addEventListener('change', function (event) {
    var el = event.target;
    if (!state || !el) { return; }
    if (el.id === 'cv-contact') {
      state.contact = el.value;
      state.ticks = {};
      refresh();
    } else if (el.dataset && el.dataset.heading !== undefined) {
      state.dates[el.dataset.heading] = el.value;
      refresh();
    } else if (el.classList && el.classList.contains('cv-tick')) {
      state.ticks[el.dataset.index] = el.checked;
      count();
    }
  });

  review.addEventListener('click', function (event) {
    var el = event.target && event.target.closest ? event.target.closest('button') : null;
    if (!state || !el || !el.dataset) { return; }
    if (el.dataset.set) {
      state.directions[el.dataset.index] = el.dataset.set;
      refresh();
    } else if (el.dataset.action === 'import') {
      importNow(el);
    } else if (el.dataset.action === 'again') {
      state.contact = '';
      state.ticks = {};
      refresh();
    }
  });

  window.addEventListener('message', function (event) {
    // Only the LinkedIn tab that opened this one, and only a conversation.
    if (received || event.origin !== LINKEDIN || event.source !== window.opener) { return; }
    var data = event.data;
    if (!data || typeof data !== 'object' || data.v !== 1) { return; }
    received = true;
    window.clearTimeout(timer);
    try { window.opener = null; } catch (e) { /* the tab stays reachable: harmless */ }
    state = { payload: data, contact: '', dates: {}, directions: {}, ticks: {} };
    say('Reading the conversation…');
    refresh();
  });

  if (window.opener) {
    window.opener.postMessage('ready', LINKEDIN);
    timer = window.setTimeout(function () {
      if (!received) { say(NOTHING); }
    }, WAIT_MS);
  } else {
    say(NOTHING);
  }
})();
