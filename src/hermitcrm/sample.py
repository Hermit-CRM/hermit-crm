"""The sample account: one made-up company a new user can load, look at and remove.

It lives in the user's own folder, marked `sample: true` in its company.md, so
every page shows a finished account instead of an empty screen. Removing it
deletes only folders that still carry that marker, in one commit; take the key
out by hand and the company is yours. The content is the demo's Northwind
Robotics account (hermitcrm/datafolder.py), dated relative to today.
"""

from __future__ import annotations

from .models import Company
from .store import Store

ADDED = "sample: added"
REMOVED = "sample: removed"


class SampleError(Exception):
    pass


def samples(store: Store) -> list[Company]:
    return sorted((c for c in store.companies.values() if c.is_sample),
                  key=lambda c: c.name.lower())


def add(store: Store) -> Company:
    """Write the sample account (one commit). Refused while one is loaded."""
    from .datafolder import _Demo

    if loaded := samples(store):
        raise SampleError(f"The sample account is already loaded: {loaded[0].name}.")
    demo = _Demo(store, store.today())
    with store.batch(ADDED), demo.backdated():
        slug = demo.northwind(sample=True)
    return store.companies[slug]


def remove(store: Store) -> list[Company]:
    """Delete every company marked as a sample (one commit); [] when there is none."""
    found = samples(store)
    if found:
        with store.batch(REMOVED):
            for company in found:
                store.delete_sample(company.slug)
    return found
