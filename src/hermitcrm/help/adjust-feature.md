# Make it yours: something Hermit can't do yet

A recipe for your AI agent: when a wish needs new code, check first whether the files already cover it, then write a feature request or, for a developer, build it in their own copy.

Read `hermitcrm help adjust` first; its rules apply here too.

## 1. Check whether it is already possible

Most wishes are a field, a layout, a dashboard, a routine or a template in
disguise. Try these before anything else:

| The user wants | It is |
|---|---|
| A separate list of deals, partners or investors | companies with a field (`type = "partner"`) and a pinned dashboard filtered on it (`hermitcrm help adjust-fields`, `hermitcrm help adjust-dashboards`) |
| A deal value, a probability, a renewal date | a number or date field |
| "Hide this", "put that first" | a page layout (`hermitcrm help adjust-layout`) |
| A weekly overview, a ranked list, a report of their own | a dashboard |
| A reminder, a daily brief, follow-ups drafted for me | a routine (`hermitcrm help adjust-routines`); it drafts, never sends |
| The wording of a quote, a proposal or an email in their style | a template in `MESSAGING.md` (`hermitcrm help adjust-messages`), filled in by you on request |
| Data from another tool | an import (`hermitcrm help adjust-connect`) |

If one of these does the whole job, say so, build it that way, and say what is
different from what they asked.

If one only does part of it (a button, a PDF, line items, a calculation, a
screen Hermit does not have), a "quote generator" for instance, say which part
it covers, write the feature request for the rest (step 2), and ask before you
build the partial version: change nothing in the data folder until they say yes.

## 2. If it really needs code: a feature request

Hermit runs no code from the data folder, and you never change the installed
package (an update would undo it). Write the request for the user instead:

```text
Title: <one line: what they want to do, not how>

What I am trying to do:
<the job, in their words, one paragraph>

What I tried in Hermit:
<the field, layout, dashboard or routine you checked, and why it falls short>

What would help:
<the smallest change that would do it>

Hermit CRM version: <hermitcrm --version>
```

Show it to the user. They can send it with Help > Feedback (it saves the text in
the folder and offers to mail it) or paste it into a new issue on the Hermit CRM
GitHub repository. Never post it yourself.

## 3. For a developer: build it in their own copy

If the user is a developer and wants to build it, do that in their own clone of
the Hermit CRM source (Apache 2.0), never in the data folder and never in the
installed package:

1. Clone the repository, make a branch, follow `CONTRIBUTING.md` and the
   repository's `AGENTS.md`.
2. Write the change with tests; the test suite must pass.
3. Sign off every commit (Developer Certificate of Origin, `git commit -s`) and
   open a pull request.

## Safety

- Nothing in the data folder changes in this recipe, unless step 1 found a way
  that does the whole job, or the user said yes to a partial one.
- Never post, mail or open an issue on the user's behalf.

Related: [Make it yours](/help/adjust), [Feedback](/help/feedback)
