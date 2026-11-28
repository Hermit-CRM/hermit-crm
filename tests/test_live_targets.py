# Copyright 2026 Gijs Bos
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""static/live.js sends a form[data-live] with fetch and replaces the part of the
page its data-live attribute names. A selector that names nothing makes live.js
fall back to <main>, and a part that holds an inline <script> is never swapped
(the script would not run again), so both fail quietly: the page still works,
just with a reload. These tests keep the selectors honest.

The first test reads the templates; the second renders the pages the marked
forms are on and applies live.js's own rule to the HTML: for each form, every
element matching one of its selectors (outermost only), or <main> when none
does. That part must exist, must hold the form, and must hold no <script>."""

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import CONFIG, FIXED_NOW
from hermitcrm import web

TEMPLATES = Path(web.__file__).parent / "templates"
FORM_TAG = re.compile(r"<form\b[^>]*>", re.S)
LIVE_ATTR = re.compile(r'\sdata-live(?:="([^"]*)")?(?=[\s>])')
SIMPLE = re.compile(r"^(#[\w-]+|\.[\w-]+|[a-z]+)$")


def live_forms():
    """(template, selectors) for every <form> tag that carries data-live."""
    for path in sorted(TEMPLATES.glob("*.html")):
        for tag in FORM_TAG.findall(path.read_text(encoding="utf-8")):
            got = LIVE_ATTR.search(tag)
            if got:
                parts = [p.strip() for p in (got.group(1) or "").split(",") if p.strip()]
                yield path.name, parts


def names_in_templates():
    ids, classes, tags = set(), set(), set()
    for path in TEMPLATES.glob("*.html"):
        text = path.read_text(encoding="utf-8")
        ids.update(re.findall(r'\bid="([\w-]+)"', text))
        for value in re.findall(r'\bclass="([^"]*)"', text):
            classes.update(re.findall(r"[\w-]+", value))
        tags.update(re.findall(r"<([a-z]+)[\s>]", text))
    return ids, classes, tags


def test_every_live_selector_names_an_element_in_the_templates():
    forms = list(live_forms())
    assert len(forms) >= 10, "the task forms carry data-live"
    ids, classes, tags = names_in_templates()
    assert "main" in tags     # the default, in base.html
    for name, parts in forms:
        for sel in parts:
            # live.js finds a twin by id or by the n-th match: keep it to plain names.
            assert SIMPLE.match(sel), f"{name}: data-live part {sel!r} is not #id, .class or a tag"
            kind, word = sel[0], sel[1:]
            known = ids if kind == "#" else classes if kind == "." else tags
            assert (word if kind in "#." else sel) in known, f"{name}: {sel!r} is in no template"


def test_data_live_change_is_only_on_live_forms():
    for path in TEMPLATES.glob("*.html"):
        for tag in FORM_TAG.findall(path.read_text(encoding="utf-8")):
            if "data-live-change" in tag:
                assert re.search(r'\sdata-live[=\s>]', tag), f"{path.name}: {tag}"


# ------------------------------------------------------------ rendered pages


class Node:
    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.parent, self.children = tag, attrs, parent, []

    def classes(self):
        return (self.attrs.get("class") or "").split()

    def matches(self, sel):
        if sel.startswith("#"):
            return self.attrs.get("id") == sel[1:]
        if sel.startswith("."):
            return sel[1:] in self.classes()
        return self.tag == sel

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()

    def contains(self, other):
        while other is not None:
            if other is self:
                return True
            other = other.parent
        return False


VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
        "source", "track", "wbr"}


class Tree(HTMLParser):
    """Just enough of a DOM: tags, attributes, parents. The templates close
    what they open, so no repair is needed."""

    def __init__(self, html):
        super().__init__()
        self.root = Node("#document", {}, None)
        self.at = self.root
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs), self.at)
        self.at.children.append(node)
        if tag not in VOID:
            self.at = node

    def handle_endtag(self, tag):
        node = self.at
        while node is not self.root and node.tag != tag:
            node = node.parent
        if node is not self.root:
            self.at = node.parent


def regions(tree, form):
    """live.js `regions()`: the outermost matches of the form's selectors, else <main>."""
    parts = [p.strip() for p in (form.attrs.get("data-live") or "").split(",") if p.strip()]
    found = []
    for sel in parts:
        for node in tree.root.walk():
            if node.matches(sel) and node not in found:
                found.append(node)
    found = [a for a in found if not any(b is not a and b.contains(a) for b in found)]
    if not found:
        found = [n for n in tree.root.walk() if n.tag == "main"][:1]
    return found


def has_script(node):
    return any(n.tag == "script" and n.attrs.get("type") != "application/json"
               for n in node.walk() if n is not node)


@pytest.fixture
def typed_client(repo):
    """An app with task types (so the type select is drawn) and a company with
    a contact, an interaction and tasks for the company and the person."""
    config = {**CONFIG, "task_types": [{"name": "call", "colour": "green"}]}
    app = web.create_app(repo, config=config)
    store = app.state.store
    store.clock = lambda: FIXED_NOW
    company = store.create_company("Acme Example", website="https://acme.example.com")
    contact = store.create_contact(company.slug, "Jane", "Roe", email="jane@example.com")
    first = store.create_interaction(company.slug, "email", "out", subject="Hello",
                                     contact=contact.slug, date="2026-09-10")
    store.add_task(company.slug, "send the pricing page", due="2026-09-20")
    store.add_task(company.slug, "book a call", due="2026-09-22", contact=contact.slug)
    client = TestClient(app, follow_redirects=False)
    client.interaction = first.id
    return client, company.slug, contact.slug


PAGES = ["/tasks", "/pipeline", "/companies/{c}", "/companies/{c}/contacts/{p}", "/",
         "/companies/{c}/interactions/new", "/companies/{c}/interactions/{i}/edit"]


@pytest.mark.parametrize("page", PAGES)
def test_every_live_form_swaps_a_part_that_holds_it_and_no_script(typed_client, page):
    client, slug, person = typed_client
    response = client.get(page.format(c=slug, p=person, i=client.interaction))
    assert response.status_code == 200
    tree = Tree(response.text)
    forms = [n for n in tree.root.walk() if n.tag == "form" and "data-live" in n.attrs]
    if page != "/":
        assert forms, f"{page} has live forms"
    for form in forms:
        parts = regions(tree, form)
        label = f"{page}: form {form.attrs.get('action')}"
        assert parts, f"{label} has nothing to swap"
        assert any(p.contains(form) for p in parts), f"{label} is outside what it swaps"
        for part in parts:
            assert not has_script(part), f"{label} would swap a <{part.tag}> holding a <script>"


def test_the_task_forms_on_a_company_page_swap_the_task_section(typed_client):
    client, slug, _ = typed_client
    tree = Tree(client.get(f"/companies/{slug}").text)
    done = [n for n in tree.root.walk()
            if n.tag == "form" and n.attrs.get("action", "").endswith("/tasks/0/done")]
    assert done
    assert [p.attrs.get("id") for p in regions(tree, done[0])][0] == "tasks"


def test_the_board_and_the_interaction_form_swap_their_own_parts(typed_client):
    client, slug, person = typed_client
    board = Tree(client.get("/pipeline").text)
    stage = [n for n in board.root.walk()
             if n.tag == "form" and n.attrs.get("action") == f"/companies/{slug}/stage"]
    assert stage and "data-live-change" in stage[0].attrs
    assert [p.classes() for p in regions(board, stage[0])] == [["board"]]
    page = Tree(client.get(f"/companies/{slug}/contacts/{person}").text)
    log = [n for n in page.root.walk() if n.tag == "form" and "interaction-form" in n.classes()]
    assert log
    swapped = regions(page, log[0])
    assert {p.attrs.get("id") or p.classes()[0] for p in swapped} == {"quick-add", "timeline",
                                                                       "status-strip"}
