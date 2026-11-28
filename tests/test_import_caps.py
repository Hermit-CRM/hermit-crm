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

"""Size caps on spreadsheet import (audit S9; 2026-10-31 action plan row 13), the
same limits as textsource.py: 15 MB uploaded, 20 MB for any part of an .xlsx
once unzipped. A small .xlsx can unpack to gigabytes and freeze the app."""

from __future__ import annotations

import io
import zipfile

import pytest

from hermitcrm import importer
from hermitcrm.models import ValidationError

NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'


def _xlsx(shared_xml: str, sheet_xml: str = "") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("xl/sharedStrings.xml", shared_xml)
        zf.writestr("xl/worksheets/sheet1.xml", sheet_xml or (
            f'<worksheet {NS}><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c></row>'
            f'</sheetData></worksheet>'))
    return buf.getvalue()


def test_an_upload_over_15_mb_is_refused_with_a_plain_message():
    data = b"name,website\n" + b"x" * importer.MAX_FILE_BYTES
    with pytest.raises(ValidationError) as caught:
        importer.decode_upload(data)
    assert "15 MB" in caught.value.errors["file"]


def test_a_small_xlsx_that_unpacks_past_20_mb_is_refused():
    bomb = _xlsx(f"<sst {NS}><si><t>" + "a" * (importer.MAX_XML_BYTES + 1) + "</t></si></sst>")
    assert len(bomb) < 1024 * 1024                   # small on disk
    with pytest.raises(ValidationError) as caught:
        importer.decode_upload(bomb)
    assert "too large" in caught.value.errors["file"]


def test_the_sheet_itself_is_capped_too():
    big_sheet = (f'<worksheet {NS}><sheetData>' + "<row/>" * (importer.MAX_XML_BYTES // 6 + 1)
                 + '</sheetData></worksheet>')
    with pytest.raises(ValidationError) as caught:
        importer.xlsx_to_text(_xlsx(f"<sst {NS}><si><t>Name</t></si></sst>", big_sheet))
    assert "too large" in caught.value.errors["file"]


def test_a_part_whose_zip_header_understates_its_size_is_refused(monkeypatch):
    # The size in the zip's directory is the sender's word. zipfile stops at that
    # size and then fails its checksum, so a lie reads as unreadable, never as
    # gigabytes; the read in _read_part is capped as well, as in textsource.py.
    data = _xlsx(f"<sst {NS}><si><t>" + "a" * 5000 + "</t></si></sst>")
    real = zipfile.ZipFile.getinfo

    def lying(self, name):
        info = real(self, name)
        info.file_size = 10
        return info
    monkeypatch.setattr(zipfile.ZipFile, "getinfo", lying)
    monkeypatch.setattr(importer, "MAX_XML_BYTES", 1000)
    with pytest.raises(ValidationError) as caught:
        importer.xlsx_to_text(data)
    assert caught.value.errors["file"] in (importer.TOO_BIG_XLSX,
                                           "could not read the file as .xlsx")


def test_an_ordinary_xlsx_still_reads():
    text = importer.decode_upload(_xlsx(f"<sst {NS}><si><t>Name</t></si></sst>"))
    assert text == "Name\n"


def test_the_web_import_refuses_an_oversized_file_with_the_message(client):
    big = b"name\n" + b"x" * (importer.MAX_FILE_BYTES + 10)
    csrf = client.app.state.csrf_token
    r = client.post("/import/preview", data={"csrf_token": csrf, "mode": ""},
                    files={"file": ("big.csv", big, "text/csv")})
    assert r.status_code == 400
    assert "15 MB" in r.text
