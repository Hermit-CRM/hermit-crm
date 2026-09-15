from datetime import date, datetime
from types import SimpleNamespace

from starlette.datastructures import QueryParams

from owncrm.filters import Column, apply, matches, parse

COLS = [
    Column("name", "name"),
    Column("stage", "stage", "enum", ["prospect", "offer"]),
    Column("score", "score", "number"),
    Column("due", "due", "date"),
    Column("tags", "tags"),
]


def row(**kw):
    base = {"name": "Acme", "stage": "prospect", "score": None, "due": None, "tags": []}
    base.update(kw)
    return SimpleNamespace(**base)


def test_parse_reads_text_and_multi_enum():
    params = QueryParams("f_name=ac&f_stage=prospect&f_stage=offer&f_score=&f_due=+")
    assert parse(params, COLS) == {"name": "ac", "stage": ["prospect", "offer"]}


def test_text_operators():
    col = Column("name", "name")
    assert matches(col, "Acme GmbH", "acme")
    assert not matches(col, "Acme GmbH", "!acme")
    assert matches(col, "Acme GmbH", "!beta")
    assert matches(col, "Acme GmbH", "=acme gmbh") and not matches(col, "Acme GmbH", "=acme")
    assert matches(col, "", "-") and not matches(col, "x", "-")
    assert matches(col, "x", "*") and not matches(col, None, "*")
    assert matches(col, ["a", "b"], "b")


def test_number_and_date_comparisons():
    score = Column("score", "score", "number")
    assert matches(score, 7, ">5") and not matches(score, 5, ">5")
    assert matches(score, 3, "<5") and not matches(score, None, "<5")
    assert matches(score, "~13", ">10")
    assert not matches(score, 7, ">abc")
    due = Column("due", "due", "date")
    assert matches(due, date(2026, 9, 20), ">2026-09-14")
    assert matches(due, datetime(2026, 9, 10, 9, 0), "<2026-09-14")
    assert not matches(due, None, "<2026-09-14")
    assert matches(due, date(2026, 9, 20), "2026-09")


def test_apply_combines_all_active_filters():
    rows = [row(name="Acme", stage="offer", score=8), row(name="Beta", stage="prospect", score=2),
            row(name="Gamma", stage="offer", score=None)]
    assert [r.name for r in apply(rows, COLS, {"stage": ["offer"]})] == ["Acme", "Gamma"]
    assert [r.name for r in apply(rows, COLS, {"stage": ["offer"], "score": ">5"})] == ["Acme"]
    assert [r.name for r in apply(rows, COLS, {"name": "!a"})] == []
    assert len(apply(rows, COLS, {})) == 3
    getter = Column("upper", "upper", getter=lambda r: r.name.upper())
    assert [r.name for r in apply(rows, [getter], {"upper": "=BETA"})] == ["Beta"]


# ------------------------------------------------------------------- sorting


from owncrm.filters import parse_sort, sort_rows  # noqa: E402


def test_parse_sort_only_accepts_known_columns():
    assert parse_sort(QueryParams("sort=name&dir=desc"), COLS) == ("name", "desc")
    assert parse_sort(QueryParams("sort=name"), COLS) == ("name", "asc")
    assert parse_sort(QueryParams("sort=nope&dir=desc"), COLS) == ("", "asc")
    assert parse_sort(QueryParams(""), COLS) == ("", "asc")


def test_sort_rows_text_number_date_and_empty_last():
    rows = [row(name="beta", score=None, due=date(2026, 9, 2)),
            row(name="Alpha", score="~30", due=None),
            row(name="gamma", score=5, due=date(2026, 1, 1))]
    assert [r.name for r in sort_rows(rows, COLS, "name")] == ["Alpha", "beta", "gamma"]
    assert [r.name for r in sort_rows(rows, COLS, "name", "desc")] == ["gamma", "beta", "Alpha"]
    assert [r.name for r in sort_rows(rows, COLS, "score")] == ["gamma", "Alpha", "beta"]
    assert [r.name for r in sort_rows(rows, COLS, "score", "desc")] == ["Alpha", "gamma", "beta"]
    assert [r.name for r in sort_rows(rows, COLS, "due")] == ["gamma", "beta", "Alpha"]
    assert [r.name for r in sort_rows(rows, COLS, "due", "desc")] == ["beta", "gamma", "Alpha"]
    assert [r.name for r in sort_rows(rows, COLS, "")] == ["beta", "Alpha", "gamma"]
