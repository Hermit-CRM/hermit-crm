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

// The bookmarklet, as capture.bookmarklet() compacts it into one line.
// A bookmark's javascript: address is percent-decoded and stripped of line
// breaks before it runs, so: whole-line comments only (they are dropped),
// every statement ends in ";", and no percent sign anywhere.
//
// Anywhere but a LinkedIn profile it sends the address only, as it always has.
// On a profile it also sends pieces of the page you are looking at, read in
// your own logged-in tab (v=2), and the app reads those instead of fetching:
//   h1    the name           top  the top card's text   exp  Experience's text
//   (no <h1>: top is the page's whole text, and the app takes the name
//   from the tab's title)
//   co    "href|label" for each link to a company page in those two
//   (no <h1>: each one from the Experience heading on)
//   lab   aria-labels in the top card that say something ("Current company: X")
//   mail  the address in an open Contact info dialog
// v=3 adds two more, for "Add to research" on someone who is already saved:
//   about  the About section's text
//   act    the text of the posts and comments by the person in Activity
//   (the likes, reposts and other people's posts it shows are left out)
// Each piece is cut to a budget of encoded characters, because the app
// refuses a request head over 16 KB. Together they are held to LIMIT: when
// they are over it, act shrinks first, then about, then exp.
(function () {
  var B = '__BASE__', d = document, L = location.href, E = encodeURIComponent;
  var q = 'url=' + E(L);
  if (/^https:[/][/][a-z.]*linkedin[.]com[/]in[/]/.test(L)) {
    var cut = function (s, n) {
      var c = Array.from(String(s || '').replace(/[ \t ]+/g, ' ').replace(/ *\n\s*/g, '\n').trim());
      var e = E(c.join(''));
      while (e.length > n) { c = c.slice(0, Math.floor(c.length * 0.8)); e = E(c.join('')); }
      return e;
    };
    var text = function (el) { return el ? el.innerText : ''; };
    var main = d.querySelector('main') || d.body;
    if (!main.querySelector('h1') && text(main).length < 200) { main = d.body; }
    var h = main.querySelector('h1');
    var top = h ? (h.closest('section') || h.parentElement) : null;
    var x = d.getElementById('experience');
    var exp = x ? (x.closest('section') || x.parentElement) : null;
    var all = text(main);
    // A layout without those hooks: the page's own text, top card first, and
    // Experience from its heading on (the app knows these words too).
    var at = all.search(/(^|\n) *(Experience|Ervaring|Berufserfahrung|Erfahrung|Exp\u00e9rience) *\n/i);
    var topText = top ? text(top) : all;
    var expText = exp ? text(exp) : (at < 0 ? '' : all.slice(at));
    // Company links, there: from the Experience heading on, since Activity,
    // Featured and Interests come first and link other companies. The
    // heading is a text node with only that word, in an h2 or h3 if one is.
    var xh = [];
    if (!top) {
      var w = d.createTreeWalker(main, NodeFilter.SHOW_TEXT);
      while (w.nextNode()) {
        if (/^\s*(Experience|Ervaring|Berufserfahrung|Erfahrung|Exp\u00e9rience)\s*$/i.test(w.currentNode.nodeValue)) { xh.push(w.currentNode.parentElement); }
      }
      xh = xh.filter(function (e) { return e.closest('h2,h3'); }).concat(xh);
    }
    var co = [], lab = [];
    (top ? [top, exp] : [main]).forEach(function (s) {
      if (!s) { return; }
      s.querySelectorAll('a[href*="/company/"]').forEach(function (a) {
        if (!top && !(xh[0] && xh[0].compareDocumentPosition(a) & Node.DOCUMENT_POSITION_FOLLOWING)) { return; }
        var img = a.querySelector('img');
        var t = (a.innerText || '').trim() || (img ? img.alt : '') || a.getAttribute('aria-label') || '';
        if (co.length < 8) { co.push(a.href.split('?')[0] + '|' + t.replace(/\s+/g, ' ')); }
      });
    });
    // Only "Label: value" (the app reads nothing else), so the rest of a
    // whole page cannot use up the six places.
    (top || main).querySelectorAll('[aria-label]').forEach(function (b) {
      var t = b.getAttribute('aria-label') || '';
      if (/^[^:\n]{2,40}:/.test(t) && lab.length < 6) { lab.push(t); }
    });
    var m = d.querySelector('[role=dialog] a[href^="mailto:"]');
    // About and Activity: the section if the page has the hooks, else the text
    // between its heading and the next one (a heading is a line of only that word).
    var HEAD = '(About|Info|Over|\u00dcber|\u00c0 propos|Acerca de|Activity|Activiteit|Aktivit\u00e4t|Activit\u00e9|Featured|Uitgelicht|Hervorgehoben|Experience|Ervaring|Berufserfahrung|Erfahrung|Exp\u00e9rience|Education|Opleiding|Ausbildung|Formation|Skills|Vaardigheden|Kenntnisse|Comp\u00e9tences|Interests|Interesses|Interessen|Int\u00e9r\u00eats)';
    var between = function (names) {
      var a = all.search(new RegExp('(^|\\n) *' + names + ' *\\n', 'i'));
      if (a < 0) { return ''; }
      var rest = all.slice(a).replace(/^\s+/, '').split('\n').slice(1).join('\n');
      var z = rest.search(new RegExp('\\n *' + HEAD + ' *\\n', 'i'));
      return z < 0 ? rest : rest.slice(0, z);
    };
    var ab = d.getElementById('about');
    var aboutText = ab ? text(ab.closest('section') || ab.parentElement) : between('(About|Info|Over|\u00dcber|\u00c0 propos|Acerca de)');
    var ac = d.getElementById('content_collections');
    var actItems = ac ? Array.from((ac.closest('section') || ac.parentElement).querySelectorAll('li')).map(text) : between('(Activity|Activiteit|Aktivit\u00e4t|Activit\u00e9)').split(/\n\s*\n/);
    // Only what the person wrote: a post or comment of theirs, not a reaction
    // ("... likes this"), a repost or a post of someone else's they reacted to.
    var REACTED = /(^|\n)[^\n]{0,80}\b(likes|celebrates|supports|loves|finds this|reposted|curious about|liked|gefeliciteerd|gef\u00e4llt|aime|recommande)\b/i;
    var actText = actItems.filter(function (t) { return t && t.trim() && !REACTED.test(t.slice(0, 200)); }).slice(0, 6).join('\n\n');
    var LIMIT = 12500, left = LIMIT - q.length;
    var base = '&v=3&h1=' + cut(text(h), 300) + '&title=' + cut(d.title, 300);
    base += '&co=' + cut(co.join('\n'), 1500) + '&lab=' + cut(lab.join('\n'), 1000);
    base += m ? '&mail=' + cut(m.getAttribute('href'), 200) : '';
    base += '&top=' + cut(topText, 3000);
    left -= base.length;
    var ex = cut(expText, Math.max(0, Math.min(3000, left)));
    left -= ex.length;
    var ba = cut(aboutText, Math.max(0, Math.min(1500, left)));
    left -= ba.length;
    var ba2 = cut(actText, Math.max(0, Math.min(3000, left)));
    q += base + '&exp=' + ex + '&about=' + ba + '&act=' + ba2;
  }
  window.open(B + '/extension/new?' + q, '_blank');
})();
