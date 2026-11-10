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

// The Generate panel (Outreach, one contact): choosing an approach whose framework leads
// with a gap, for a contact whose notes already hold a fresh one, sets Research to
// "none" (the gap is in the notes; research cannot find one). Choosing another approach
// puts Research back, unless the person changed it themselves.
(function () {
  var approach = document.getElementById('gen-approach');
  var research = document.getElementById('gen-research');
  if (!approach || !research) return;
  var hint = document.getElementById('gen-research-hint');
  var warning = document.getElementById('gen-gap-warning');
  var gap = [];
  try { gap = JSON.parse(approach.getAttribute('data-gap-approaches') || '[]'); } catch (e) { gap = []; }
  var ready = approach.getAttribute('data-gap-ready') === '1';
  var before = null;      // what Research was before this script switched it
  var touched = false;    // the person picked a Research level themselves

  function showHint() {
    if (hint) hint.textContent = research.value === 'none'
      ? hint.getAttribute('data-none') : hint.getAttribute('data-scrape');
  }

  approach.addEventListener('change', function () {
    var needsGap = gap.indexOf(approach.value) !== -1;
    if (warning) warning.hidden = !(needsGap && !ready);
    if (!touched) {
      if (needsGap && ready && research.value !== 'none') {
        before = research.value;
        research.value = 'none';
      } else if (!needsGap && before !== null) {
        research.value = before;
        before = null;
      }
    }
    showHint();
  });

  research.addEventListener('change', function () {
    touched = true;
    before = null;
    showHint();
  });
})();
