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

"""Settings and the Playbook page say less: what a reader needs once sits behind a
"?" (the `hint` macro). What a reader must see before acting (the sending limits,
where secrets are kept, the open-network warning) stays in the page itself."""

from __future__ import annotations

import html
import re

import pytest

from test_settings import demo, make_client, token  # noqa: F401  (demo is a fixture)

TIP = re.compile(r'<span class="tip" role="tooltip" id="[^"]+">.*?</span>', re.S)


def text_of(page: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page)))


def visible(page: str) -> str:
    """The page text with every hint's tip taken out: what is on show without hovering."""
    return text_of(TIP.sub("", page))


def tip_text(page: str, id: str) -> str:
    return text_of(re.search(rf'<span class="tip" role="tooltip" id="{id}">.*?</span>',
                             page, re.S).group(0))


@pytest.mark.parametrize("path", ["/settings", "/settings/playbook"])
def test_every_hint_is_described_by_its_own_tip_and_stays_out_of_tables(demo, tmp_path, path):  # noqa: F811
    app, client = make_client(demo, tmp_path)
    page = client.get(path).text
    tips = re.findall(r'<span class="tip" role="tooltip" id="([^"]+)"', page)
    described = re.findall(r'class="help hint"[^>]*aria-describedby="([^"]+)"', page)
    assert tips, f"{path} has no hint"
    assert tips == described and len(set(tips)) == len(tips)
    # a .table-scroll clips the tip
    for scroll in re.findall(r'<div class="table-scroll">.*?</div>', page, re.S):
        assert 'class="help hint"' not in scroll


def test_what_must_be_seen_before_acting_is_not_behind_a_hint(demo, tmp_path):  # noqa: F811
    app, client = make_client(demo, tmp_path)
    page = visible(client.get("/settings").text)
    for warning in [
        "cold email can hurt the reputation of the domain",   # Sending: deliverability
        "a new mailbox starts at 10",                          # ... and the ramp
        "third is held at 150",                                # ... and the cap
        "German and Austrian law ask for consent",             # ... and the legal note
        "never in config.toml",                                # where secrets are kept
        "Treat it like a password",                            # the secret calendar address
        "The repository must be PRIVATE",                      # the online copy of your data
        "Hermit CRM has no password",                          # the open network
    ]:
        assert warning in page, warning


@pytest.mark.parametrize("store, shown", [
    ("", "No system keyring was found"),
    ("keychain", "or the macOS Keychain"),
    ("secret-service", "A keyring is locked while you are logged out"),
])
def test_how_secrets_are_kept_is_on_show_for_every_kind_of_store(demo, tmp_path, store, shown):  # noqa: F811
    app, client = make_client(demo, tmp_path)
    app.state.os_store = ("linux", store)     # what the probe would have found
    page = client.get("/settings").text
    text = visible(page)
    assert shown in text and text.count("never in config.toml") >= 2   # BCC and Sending
    if store == "":
        assert "libsecret-tools" in tip_text(page, "keyring-help")      # the how-to is the hint
        assert "libsecret-tools" not in text


def test_the_stage_roles_and_the_interested_outcome_sit_behind_a_hint(demo, tmp_path):  # noqa: F811
    app, client = make_client(demo, tmp_path)
    t = token(client)
    r = client.post("/settings/outcomes", data={"csrf_token": t, "outcomes": "successful\nunsuccessful",
                                                 "message_window_days": "14", "silent_days": "14"})
    assert r.status_code == 303
    page = client.get("/settings").text
    roles = tip_text(page, "stage-roles-help")
    for role in ("open", "won", "lost", "closed", "parked"):
        assert role in roles
    assert "is out of the pipeline for now" in roles
    assert "is out of the pipeline for now" not in visible(page)    # the line above the table stays short
    assert "Replies to interest" in tip_text(page, "interested-help")
    assert "Add interested" in visible(page)                # the button itself is not hidden


def test_the_tip_script_is_served_and_loaded(demo, tmp_path):  # noqa: F811
    app, client = make_client(demo, tmp_path)
    assert client.get("/static/hint.js").status_code == 200
    assert "/static/hint.js" in client.get("/settings").text
