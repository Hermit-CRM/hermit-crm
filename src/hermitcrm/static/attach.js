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

/* Files on a note. A form with data-attach (the note and interaction forms)
 * takes files dropped on it or pasted into it, lists what is chosen with a
 * remove button each, and hands them to its own file input, so submitting is
 * the ordinary multipart form post. An entry in a timeline (li[data-drop-url])
 * takes a dropped file and uploads it to that entry at once.
 * The page works without this script: the file input is a plain picker.
 * No dependencies. */
(function () {
  "use strict";
  if (!window.DataTransfer || !window.File) return;

  var GENERIC = /^(image|screenshot|unnamed|untitled)\.(png|jpe?g|gif|webp)$/i;

  function human(n) {
    if (n < 1024) return n + " B";
    if (n < 1048576) return (n / 1024).toFixed(1) + " KB";
    return (n / 1048576).toFixed(1) + " MB";
  }

  function hasFiles(event) {
    var types = event.dataTransfer && event.dataTransfer.types;
    return !!types && Array.prototype.indexOf.call(types, "Files") !== -1;
  }

  // A pasted screenshot arrives called "image.png": give it a name worth keeping.
  function named(file) {
    if (!GENERIC.test(file.name)) return file;
    var stamp = new Date().toISOString().replace(/[-:]/g, "").slice(0, 13).replace("T", "-");
    var ext = file.name.slice(file.name.lastIndexOf("."));
    return new File([file], "pasted-" + stamp + ext, { type: file.type });
  }

  function setup(form) {
    var input = form.querySelector('input[type="file"][name="files"]');
    var box = form.querySelector(".attach-box");
    if (!input || !box) return;
    var list = box.querySelector(".attach-list");
    var note = box.querySelector(".attach-note");
    var max = (parseFloat(box.getAttribute("data-max-mb")) || 25) * 1048576;
    var chosen = [];

    function render() {
      list.textContent = "";
      chosen.forEach(function (file, i) {
        var item = document.createElement("li");
        var label = document.createElement("span");
        label.textContent = file.name + " (" + human(file.size) + ") ";
        var remove = document.createElement("button");
        remove.type = "button";
        remove.textContent = "remove";
        remove.setAttribute("aria-label", "Remove " + file.name);
        remove.addEventListener("click", function () { chosen.splice(i, 1); sync(); });
        item.appendChild(label);
        item.appendChild(remove);
        list.appendChild(item);
      });
    }

    function sync() {
      var transfer = new DataTransfer();
      chosen.forEach(function (file) { transfer.items.add(file); });
      input.files = transfer.files;   // setting files does not fire "change"
      render();
    }

    function add(files) {
      var skipped = [];
      Array.prototype.forEach.call(files, function (file) {
        if (!file.size) return;
        if (file.size > max) { skipped.push(file.name); return; }
        chosen.push(named(file));
      });
      note.textContent = skipped.length
        ? skipped.join(", ") + (skipped.length > 1 ? " are" : " is") + " over " + (max / 1048576) +
          " MB and was not added."
        : "";
      sync();
    }

    input.addEventListener("change", function () { add(Array.prototype.slice.call(input.files)); });
    form.addEventListener("reset", function () { chosen = []; setTimeout(sync, 0); });

    form.addEventListener("dragover", function (event) {
      if (!hasFiles(event)) return;
      event.preventDefault();
      form.classList.add("dragging");
    });
    form.addEventListener("dragleave", function (event) {
      if (!form.contains(event.relatedTarget)) form.classList.remove("dragging");
    });
    form.addEventListener("drop", function (event) {
      if (!hasFiles(event)) return;
      event.preventDefault();
      form.classList.remove("dragging");
      add(event.dataTransfer.files);
    });

    form.addEventListener("paste", function (event) {
      var data = event.clipboardData;
      if (!data || !data.files || !data.files.length) return;
      // A copy from a spreadsheet carries a picture and the text: the text wins.
      if (data.getData("text/plain")) return;
      event.preventDefault();
      add(data.files);
    });
  }

  function dropTarget(entry) {
    var url = entry.getAttribute("data-drop-url");
    entry.addEventListener("dragover", function (event) {
      if (!hasFiles(event)) return;
      event.preventDefault();
      entry.classList.add("dragging");
    });
    entry.addEventListener("dragleave", function (event) {
      if (!entry.contains(event.relatedTarget)) entry.classList.remove("dragging");
    });
    entry.addEventListener("drop", function (event) {
      if (!hasFiles(event)) return;
      event.preventDefault();
      entry.classList.remove("dragging");
      var data = new FormData();
      Array.prototype.forEach.call(event.dataTransfer.files, function (file) {
        data.append("files", file, file.name);
      });
      entry.classList.add("uploading");
      fetch(url, { method: "POST", body: data, headers: { Accept: "application/json" } })
        .then(function (response) { return response.json(); })
        .then(function (answer) {
          if (answer.ok) { location.reload(); return; }
          entry.classList.remove("uploading");
          window.alert(answer.error || "The file could not be attached.");
        })
        .catch(function () {
          entry.classList.remove("uploading");
          window.alert("The file could not be attached.");
        });
    });
  }

  Array.prototype.forEach.call(document.querySelectorAll("form[data-attach]"), setup);
  Array.prototype.forEach.call(document.querySelectorAll("li[data-drop-url]"), dropTarget);
})();
