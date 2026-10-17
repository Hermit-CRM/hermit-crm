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

"""What the code-scanning pass changed: names stay inside their folder, a
redirect stays on this site, LinkedIn is matched by host, an address check
cannot be made to crawl, and a failed save never logs the secret."""

import logging
import subprocess
import time

import pytest

from hermitcrm import secrets, setup, web
from hermitcrm.models import ValidationError
from hermitcrm.paths import contained
from hermitcrm.scrape import _is_linkedin, name_from_handle


# --------------------------------------------------------------- paths


def test_contained_keeps_ordinary_names_and_a_relative_base(tmp_path, monkeypatch):
    assert contained(tmp_path, "a", "b.md") == tmp_path / "a" / "b.md"
    monkeypatch.chdir(tmp_path)
    assert str(contained("data", "acme")) == "data/acme"
    assert contained(tmp_path) == tmp_path


@pytest.mark.parametrize("name", ["..", "../x", "a/../../x", "/etc/passwd", ".", "",
                                  "a\0b", "../" + "x"])
def test_contained_refuses_a_name_that_leaves_the_folder(tmp_path, name):
    with pytest.raises(ValidationError):
        contained(tmp_path, name)


def test_a_company_slug_cannot_climb_out_of_companies(store):
    store.create_company("Acme")
    for bad in ("../x", "../../etc", "/abs", "acme/../../x"):
        with pytest.raises(ValidationError):
            store.company_dir(bad)
    assert store.company_dir("acme").name == "acme"


def test_a_contact_or_interaction_id_cannot_climb_out_of_its_folder(store):
    store.create_company("Acme")
    for bad in ("../company", "../../x", "/abs"):
        with pytest.raises(ValidationError):
            store.contact_file("acme", bad)
        with pytest.raises(ValidationError):
            store.interaction_file("acme", bad)
    assert store.contact_file("acme", "jane").parent.name == "contacts"


def test_nothing_is_deleted_outside_the_company_for_a_hostile_id(store, tmp_path):
    store.create_company("Acme")
    keep = tmp_path / "companies" / "acme" / "company.md"
    with pytest.raises(ValidationError):
        store.delete_interaction("acme", "../company")
    assert keep.exists()


def test_record_version_of_a_hostile_slug_is_empty(tmp_path):
    outside = tmp_path / "secret.md"
    outside.write_text("x")
    assert web.record_version(tmp_path, "../secret.md") == ""
    assert web.record_version(tmp_path, "acme", "../../../secret") == ""


# --------------------------------------------------------------- redirects


@pytest.mark.parametrize("target", [
    "https://evil.example.com/", "//evil.example.com", "/\\evil.example.com",
    "/\t/evil.example.com", "evil.example.com/x", "javascript:alert(1)", "", "?a=b",
    "/\n/evil.example.com"])
def test_a_redirect_never_leaves_the_site(target):
    assert web.local_path(target) == "/"
    response = web.goto(target)
    assert response.headers["location"] == "/"


def test_a_local_redirect_is_untouched():
    for path in ("/", "/companies/acme", "/companies/acme/contacts/jane?flash=ok#top"):
        assert web.local_path(path) == path
    assert web.flashed("/companies/acme", "Saved", "notes").headers["location"] \
        == "/companies/acme?flash=Saved#notes"


# --------------------------------------------------------------- LinkedIn


@pytest.mark.parametrize("url, expected", [
    ("https://www.linkedin.com/in/x", True), ("https://linkedin.com/in/x", True),
    ("https://nl.linkedin.com/in/x", True), ("https://LinkedIn.com:443/in/x", True),
    ("https://notlinkedin.com/in/x", False),
    ("https://linkedin.com.evil.example.com/in/x", False),
    ("https://evil.example.com/linkedin.com", False),
    ("https://evil.example.com/?u=linkedin.com", False),
    ("https://user:linkedin.com@evil.example.com/", False)])
def test_linkedin_is_matched_by_host(url, expected):
    assert _is_linkedin(url) is expected


def test_name_from_handle_still_reads_a_profile_address():
    assert name_from_handle("https://www.linkedin.com/in/ines-vega-8a1b2c3d/") == "Ines Vega"
    assert name_from_handle("nl.linkedin.com/in/ines-vega") == "Ines Vega"
    assert name_from_handle("https://www.linkedin.com/in/inesvega") == ""
    assert name_from_handle("https://example.com/in/ines-vega") == ""
    assert name_from_handle("") == ""


# --------------------------------------------------------------- addresses


@pytest.mark.parametrize("address, ok", [
    ("jane@example.com", True), ("jane+crm@mail.example.co.uk", True),
    ("a@b.c", True), ("jane@example", False), ("@example.com", False),
    ("jane@@example.com", False), ("jane doe@example.com", False),
    ("jane@exa mple.com", False), ("jane@.example.com", False),
    ("jane@example..com", False), ("jane@example.com.", False), ("", False)])
def test_valid_email(address, ok):
    assert setup.valid_email(address) is ok


def test_valid_email_is_linear_on_a_hostile_address():
    hostile = "!@!." + "!." * 20000
    started = time.perf_counter()
    assert setup.valid_email(hostile) is False
    assert time.perf_counter() - started < 1.0


# --------------------------------------------------------------- secrets


def test_a_failed_save_does_not_log_the_secret(caplog):
    value = "s3cret-value-9f2"

    def timeout(argv, **kw):
        raise subprocess.TimeoutExpired(argv, 20)

    def failing(argv, **kw):
        return subprocess.CompletedProcess(argv, 1, "", f"bad {value}")

    with caplog.at_level(logging.DEBUG, logger=secrets.logger.name):
        assert secrets.os_store_save(secrets.KEYCHAIN, "svc", "me", value,
                                     runner=timeout) is False
        assert secrets.os_store_save(secrets.KEYCHAIN, "svc", "me", value,
                                     runner=failing) is False
    assert "saving svc in" in caplog.text
    assert value not in caplog.text
