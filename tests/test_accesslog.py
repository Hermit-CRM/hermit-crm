"""The serve log keeps its request lines, never what a capture read off a page."""

import logging
import logging.config

import pytest

from hermitcrm import accesslog

LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


@pytest.fixture
def uvicorn_logging():
    """dictConfig is global: put the uvicorn loggers back as they were."""
    saved = {}
    for name in LOGGERS:
        lg = logging.getLogger(name)
        saved[name] = (lg.handlers[:], lg.filters[:], lg.level, lg.propagate, lg.disabled)
    yield
    for name, (handlers, filters, level, propagate, disabled) in saved.items():
        lg = logging.getLogger(name)
        lg.handlers[:], lg.filters[:] = handlers, filters
        lg.setLevel(level)
        lg.propagate, lg.disabled = propagate, disabled


def access_line(path):
    """The call uvicorn makes for every request it answers."""
    logging.getLogger("uvicorn.access").info(
        '%s - "%s %s HTTP/%s" %d', "127.0.0.1:51000", "GET", path, "1.1", 200)


CAPTURE = ("/extension/new?url=https%3A%2F%2Fwww.linkedin.com%2Fin%2Fines-vega"
           "&name=Ines+Vega&top=Head+of+Compliance")


def test_a_capture_is_logged_without_what_it_read(uvicorn_logging, capsys):
    logging.config.dictConfig(accesslog.log_config())
    access_line(CAPTURE)
    out = capsys.readouterr().out
    assert "GET /extension/new" in out and "200" in out
    assert "ines-vega" not in out and "Ines" not in out and "Compliance" not in out


def test_an_old_bookmarklet_capture_is_kept_out_too(uvicorn_logging, capsys):
    logging.config.dictConfig(accesslog.log_config())
    access_line("/capture/new?url=https%3A%2F%2Fwww.linkedin.com%2Fin%2Fines-vega")
    out = capsys.readouterr().out
    assert "GET /capture/new" in out and "ines-vega" not in out


def test_every_other_request_is_logged_as_it_was(uvicorn_logging, capsys):
    logging.config.dictConfig(accesslog.log_config())
    access_line("/companies?q=harbour")
    access_line("/extension")
    out = capsys.readouterr().out
    assert "GET /companies?q=harbour HTTP/1.1" in out
    assert "GET /extension HTTP/1.1" in out
