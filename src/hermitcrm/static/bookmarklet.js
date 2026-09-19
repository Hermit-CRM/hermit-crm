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
//   lab   aria-labels in the top card that say something ("Current company: X")
//   mail  the address in an open Contact info dialog
// Each piece is cut to a budget of encoded characters, because the app
// refuses a request head over 16 KB.
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
    var co = [], lab = [];
    (top ? [top, exp] : [main]).forEach(function (s) {
      if (!s) { return; }
      s.querySelectorAll('a[href*="/company/"]').forEach(function (a) {
        var img = a.querySelector('img');
        var t = (a.innerText || '').trim() || (img ? img.alt : '') || a.getAttribute('aria-label') || '';
        if (co.length < 8) { co.push(a.href.split('?')[0] + '|' + t.replace(/\s+/g, ' ')); }
      });
    });
    (top || main).querySelectorAll('[aria-label]').forEach(function (b) {
      var t = b.getAttribute('aria-label') || '';
      if (t.indexOf(':') > 0 && lab.length < 6) { lab.push(t); }
    });
    var m = d.querySelector('[role=dialog] a[href^="mailto:"]');
    q += '&v=2&h1=' + cut(text(h), 300) + '&title=' + cut(d.title, 300);
    q += '&top=' + cut(topText, 3000) + '&exp=' + cut(expText, 3000);
    q += '&co=' + cut(co.join('\n'), 1500) + '&lab=' + cut(lab.join('\n'), 1000);
    q += m ? '&mail=' + cut(m.getAttribute('href'), 200) : '';
  }
  window.open(B + '/extension/new?' + q, '_blank');
})();
