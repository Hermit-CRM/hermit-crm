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

/* Background jobs (jobs.py). Loaded on every page by base.html.

   1. The top-bar badge (#jobs-badge): asks /jobs/active.json once on load; while
      a job runs it asks again every second, and says "ready" when one finished
      that nobody has opened yet. Nothing running: one request per page, then quiet.
   2. A page showing one job ([data-job], the job page and Ask's answer page) asks
      /jobs/<id>.json every second, fills in the progress line, and reloads once
      when the job is finished, so the server draws the result.
   Without JavaScript neither happens: the badge stays hidden and the job page
   refreshes itself with a <meta refresh> inside <noscript>. */
(function () {
  "use strict";
  var POLL_MS = 1000;
  var ACTIVE = { queued: true, running: true };

  function getJSON(url) {
    return fetch(url, { headers: { Accept: "application/json" }, cache: "no-store",
                        credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .catch(function () { return null; });
  }

  function steps(job) { return job.steps ? " · " + job.steps : ""; }

  // ------------------------------------------------------------------ one job

  var here = document.querySelector("[data-job]");
  var hereId = here ? here.getAttribute("data-job") : "";

  function setText(sel, text) {
    var el = here.querySelector(sel);
    if (el && el.textContent !== text) el.textContent = text;
  }

  function watchHere() {
    getJSON("/jobs/" + encodeURIComponent(hereId) + ".json").then(function (job) {
      if (!job) { window.setTimeout(watchHere, POLL_MS * 3); return; }
      if (!ACTIVE[job.state]) { window.location.reload(); return; }
      setText("[data-job-state]", job.state === "queued" ? "Waiting to start" : "Working");
      setText("[data-job-steps]", job.steps || "");
      setText("[data-job-progress]", job.progress || "");
      window.setTimeout(watchHere, POLL_MS);
    });
  }

  if (here && here.hasAttribute("data-job-active")) window.setTimeout(watchHere, POLL_MS);

  // -------------------------------------------------------------------- badge

  var badge = document.getElementById("jobs-badge");
  if (!badge) return;

  function draw(jobs) {
    // The job this page already shows is not repeated in the badge.
    jobs = jobs.filter(function (j) { return j.id !== hereId; });
    var running = jobs.filter(function (j) { return ACTIVE[j.state]; });
    var ready = jobs.filter(function (j) { return !ACTIVE[j.state]; });
    var first = running[0] || ready[ready.length - 1];
    if (!first) { badge.hidden = true; badge.textContent = ""; return false; }
    var word = ACTIVE[first.state] ? "Working" :
      first.state === "done" ? "Ready" : first.state === "failed" ? "Failed" : "Interrupted";
    var more = running.length + ready.length - 1;
    var a = badge.querySelector("a") || document.createElement("a");
    a.href = first.url;
    a.className = "jobs-badge-link jobs-" + (ACTIVE[first.state] ? "running" : first.state);
    a.textContent = word + ": " + first.label + (ACTIVE[first.state] ? steps(first) : "") +
      (more > 0 ? " (+" + more + ")" : "");
    a.title = first.progress || first.label;
    if (!a.parentNode) badge.appendChild(a);
    badge.hidden = false;
    return running.length > 0;
  }

  function poll() {
    getJSON("/jobs/active.json").then(function (data) {
      if (!data || !data.jobs) return;
      if (draw(data.jobs)) window.setTimeout(poll, POLL_MS);
    });
  }

  poll();
})();
