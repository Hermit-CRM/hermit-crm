# A sample account for new users

Agreed with Gijs on 2026-09-19: option A (in the user's own folder), one account
with one of everything, built now.

## Problem

`hermitcrm init --demo` makes a separate folder with six fictional companies, but
a new user never sees it: INSTALL.md tells the installing assistant not to create
records, and the empty Home offers only "Add a company / Import / BCC". The demo
also predates free tasks (PR #12) and skips two stages.

## Design

**Demo refresh.** `load_demo` becomes one builder per account (`_Demo`), so the
sample reuses one of them. The demo gains free tasks (company, person, one done),
a `disqualified` and a `temp-disqualified` company (every stage), and the Northwind
proposal moves to 6 days ago so it is a live nudge on the follow-up radar rather
than a message already counted as unanswered.

**Sample account** (`hermitcrm/sample.py`). The demo's Northwind Robotics account:
two people with roles, a LinkedIn message and its reply, a meeting, stage history
prospect → engaged → discovery → offer with a monthly value, a proposal still
waiting for an answer, a next step due in 3 days, a task on a person due in 5 and
one done task, notes that explain it is fictional and how to remove it.

- Marker: `sample: true` in company front matter (an ordinary extra key, so no
  data format change) plus the tag `sample`. Removing the key by hand makes the
  record yours; nothing else ever deletes it.
- Load: `hermitcrm sample add`, a start card on the empty Home, and a line on
  /welcome (new users land there first). One commit, `sample: added`. Refused
  while a sample exists.
- Bar on every page while a sample exists, linking to removal.
- Remove: `/sample/remove` lists exactly what goes (people, interactions, tasks,
  including anything added since), then one commit `sample: removed`.
  `Store.delete_sample(slug)` refuses any company without the marker. There is
  still no general company delete. `hermitcrm sample remove` does the same.
- Walkthrough: `welcome.steps()` ignores sample companies, so its steps still
  mean the user's own records.
- AI agents: PIPELINE.md ends a sample company's line with `| sample (fictional)`;
  the data folder's CLAUDE.md/AGENTS.md (new folders) say to leave samples out.
- Reports count the sample while it is there; the bar is the reminder.

Not in the sample: user-defined fields (would write the user's fields.toml), a
BCC inbox item, lost/disqualified accounts. No migration.

## Tests

Loading into an empty folder: `check` is clean, one commit, marker and tag,
every page 200 with the bar, walkthrough progress unchanged. Loading twice is
refused. Remove: only marked folders go, a real company stays, one commit, the
bar is gone; nothing to remove says so; `delete_sample` refuses an unmarked
company; POSTs need the CSRF token. PIPELINE.md marks the line. Demo: all eight
stages, tasks present, report baselines regenerated.

## After Gijs tested it (2026-09-20)

Removing the sample and adding a real company emptied the home page of every
beginner thing at once, because home had one switch (`no_companies`) and it
flips on the first company. *What this thing does* sat outside that test and so
never left at all.

- The start cards, the sample offer and the areas grid are one block, shown
  while `welcome.should_show()` is true -- the walkthrough's own switch. With
  companies in the folder it sits below the real lists and carries the
  walkthrough's progress; **Hide the tutorial** posts to `/welcome/dismiss`.
- Removing the sample now says, on the confirm page and in the flash, that it
  can be loaded again from Getting started.
- Fixed on the way: a toggle whose off value is an empty form field needs a
  falsy default, or FastAPI substitutes the default and the off button turns
  the thing on. It broke **Open this at start again** and **Untick**.
