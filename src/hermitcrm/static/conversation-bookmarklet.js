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

// "Hermit: conversation", as capture.conversation_bookmarklet() compacts it
// into one line. A bookmark's javascript: address is percent-decoded and
// stripped of line breaks before it runs, so: whole-line comments only (they
// are dropped), every statement ends in ";", no percent sign anywhere (so no
// modulo), and no // after code. Read the rules in
// docs/superpowers/specs/linkedin-conversation-dom.md before changing a selector.
//
// It reads the conversation the person is looking at, in their own tab, and
// hands it to Hermit's tab (the one this opens) with postMessage. Terms of
// Service rules, each tested in tests/test_capture.py:
//   * only what is already rendered: no scrolling, no clicks, no fetch;
//   * one thread per click, started by the person: no timers beyond the
//     handshake wait, no listener that outlives it;
//   * nothing is requested from LinkedIn and nothing goes in a URL.
// Dumb client, smart server: it sends raw pieces (sender text, time text, day
// heading, message text, the header's profile link); conversation.py reads them.
(function () {
  var B = '__BASE__', d = document, W = window;
  var say = function (s) { W.alert('Hermit: ' + s); };
  // Every open shadow root and every frame of our own site, recursively: the chat
  // bubble on a profile page lives in a shadow root, the full Messaging page in an
  // iframe (seen 2026-11-06), and a plain querySelector looks inside neither.
  var roots = [d];
  var dig = function (root) {
    root.querySelectorAll('*').forEach(function (el) {
      if (el.shadowRoot) { roots.push(el.shadowRoot); dig(el.shadowRoot); }
      if (el.tagName === 'IFRAME') {
        var inner = null;
        try { inner = el.contentDocument; } catch (e) { inner = null; }
        // A frame from another site is closed to us (null): only ours can be read.
        if (inner && inner.documentElement) { roots.push(inner); dig(inner); }
      }
    });
  };
  dig(d);
  var lists = [];
  roots.forEach(function (r) {
    r.querySelectorAll('ul.msg-s-message-list-content').forEach(function (u) { lists.push(u); });
  });
  if (!lists.length) {
    say('no open conversation found on this page. Open the conversation (the Messaging page, or the chat bubble from the Message button on a profile) and click the bookmark again.');
    return;
  }
  var list = lists[0];
  if (lists.length > 1) {
    // More than one conversation is open: the one the person has selected text in.
    // A selection inside a shadow root is invisible to window.getSelection(),
    // hence getComposedRanges (newer browsers) and the shadow root's own getSelection.
    var spot = [];
    try {
      var sel = W.getSelection();
      if (sel && sel.getComposedRanges) {
        var shadows = roots.filter(function (r) { return !!r.host; });
        sel.getComposedRanges({ shadowRoots: shadows }).forEach(function (r) { spot.push(r.startContainer); });
      }
    } catch (e) { /* older browser: the other way below */ }
    roots.forEach(function (r) {
      try {
        var s = r.getSelection ? r.getSelection() : null;
        if (s && s.rangeCount) { spot.push(s.getRangeAt(0).startContainer); }
      } catch (e) { /* no selection API here */ }
    });
    var hit = lists.filter(function (u) {
      return spot.some(function (n) { return n && u.contains(n); });
    });
    if (hit.length !== 1) {
      say('more than one conversation is open. Close the others, or select a little of the text in the one you want, and click the bookmark again.');
      return;
    }
    list = hit[0];
  }
  // The other person, from the header of the conversation this list belongs to.
  // Walk outwards from the list, out of its shadow root or its frame when it has one.
  var HEADER = 'h2.msg-overlay-bubble-header__title a, a.msg-thread__link-to-profile';
  var outer = function (n) {
    if (n.parentElement) { return n.parentElement; }
    var top = n.getRootNode ? n.getRootNode() : null;
    if (top && top.host) { return top.host; }
    var win = top && top.defaultView;
    return win && win.frameElement ? win.frameElement : null;
  };
  var link = null, up = outer(list);
  while (up && !link) {
    link = up.querySelector(HEADER);
    up = outer(up);
  }
  if (!link) {
    // The header may sit beside the frame, not above it: take it when it is the only one.
    var heads = [];
    roots.forEach(function (r) { r.querySelectorAll(HEADER).forEach(function (a) { heads.push(a); }); });
    if (heads.length === 1) { link = heads[0]; }
  }
  var nameOf = function (el) {
    var n = el.querySelector('.msg-entity-lockup__entity-title-wrapper, .hoverable-link-text');
    return ((n || el).innerText || '').trim().split('\n')[0];
  };
  var other = link ? { name: nameOf(link), href: link.getAttribute('href') || '' } : { name: '', href: '' };
  var items = [], who = '', whoHref = '', clock = '', day = '';
  var strangers = {};
  list.querySelectorAll('li.msg-s-message-list__event').forEach(function (li) {
    var ev = li.querySelector('.msg-s-event-listitem');
    var heading = li.querySelector('time.msg-s-message-list__time-heading');
    var name = li.querySelector('.msg-s-message-group__name');
    var stamp = li.querySelector('time.msg-s-message-group__timestamp');
    // A heading or a sender on a row with no text still applies to the next row.
    if (heading) { day = heading.textContent.trim(); }
    var fresh = !!(name || stamp);
    if (name) {
      who = name.textContent.trim();
      var a = name.closest('a');
      whoHref = a ? (a.getAttribute('href') || '') : '';
    }
    if (stamp) { clock = stamp.textContent.trim(); }
    var body = li.querySelector('p.msg-s-event-listitem__body');
    var text = body ? body.innerText : '';
    if (!text.trim()) {
      var file = li.querySelector('.msg-s-event-listitem__message-bubble [class*="attachment"], .msg-s-event-listitem__message-bubble a[download]');
      if (!file) { return; }
      text = '[attachment]';
    }
    var theirs = ev && ev.classList.contains('msg-s-event-listitem--other');
    var sent = li.querySelector('.msg-s-event-with-indicator__sending-indicator--sent');
    if (theirs) { strangers[whoHref || who] = 1; }
    items.push({
      urn: ev ? (ev.getAttribute('data-event-urn') || '') : '',
      is_other: !!theirs, who: who, who_href: whoHref,
      day: day, time: clock, inherited: !fresh,
      sent_title: sent ? (sent.getAttribute('title') || '') : '', text: text
    });
    day = '';
  });
  if (Object.keys(strangers).length > 1) {
    say('this looks like a group conversation. Hermit imports one-to-one conversations only.');
    return;
  }
  var n = new Date(), two = function (v) { return ('0' + v).slice(-2); };
  var payload = {
    v: 1, url: W.location.href, layout: list.getRootNode().host ? 'bubble' : 'page',
    other: other, lang: d.documentElement.lang || '',
    now_local: n.getFullYear() + '-' + two(n.getMonth() + 1) + '-' + two(n.getDate()) + 'T' + two(n.getHours()) + ':' + two(n.getMinutes()),
    tz_min: n.getTimezoneOffset(), items: items
  };
  // Hermit's tab asks ('ready') once it has loaded; only that tab, from Hermit's
  // own origin, gets the conversation. The listener goes after one answer, or
  // after the wait.
  var tab = W.open(B + '/extension/conversation', '_blank');
  if (!tab) {
    say('could not open its window. Allow pop-ups for this site and click the bookmark again.');
    return;
  }
  var answer = function (e) {
    if (e.source !== tab || e.origin !== B || e.data !== 'ready') { return; }
    W.removeEventListener('message', answer);
    tab.postMessage(payload, B);
  };
  W.addEventListener('message', answer);
  W.setTimeout(function () { W.removeEventListener('message', answer); }, 30000);
})();
