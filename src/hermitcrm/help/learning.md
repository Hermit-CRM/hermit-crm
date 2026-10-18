# Learning

What your edits and the answers to your messages teach the outreach bot, as short lessons in `MESSAGING.md` that you accept one by one.

Every time you change a draft before approving it, and every time a message
gets (or does not get) an answer, Hermit CRM keeps a signal. Nothing is
learned silently: a run turns the signals into **proposals**, and a proposal
only changes your Lessons when you accept it.

## The phases

The more you have reviewed and the more replies you have, the more weight goes
to outcomes over edits. `hermitcrm learn report` opens with a banner such as
"12 reviewed drafts, 2 replies, 1 positive: phase 1". Pin a phase with
`learning_phase_pin` in `config.toml`.

## The steps

1. `hermitcrm learn report` shows the efficiency trend (are your edits getting
   smaller?), the patterns in your edits, the outcome rates per angle, persona,
   channel and language (cells under 10 sent items are marked "too few"), and a
   style table. No AI is used.
2. `hermitcrm learn status` shows what a run would send: the cards (anonymised
   evidence from your edits), the prompt size and a token estimate.
3. `hermitcrm learn run` asks the AI once (strong tier) for proposals. With
   `learning_distill = "handoff"` in `config.toml` it writes
   `learning/evidence-pack.md` instead; give that to your own agent, save its
   answer as `learning/proposals.json`, then `hermitcrm learn import`.
4. `hermitcrm learn accept ID [--text "..."]` or `reject ID`. A rejected
   proposal is never proposed again.
5. `hermitcrm learn retire LESSON_ID` removes a lesson;
   `hermitcrm learn move LESSON_ID worked|failed|open` moves one.
6. `hermitcrm learn suggest` lists deterministic suggestions (a lower email word
   limit, phrases you keep deleting); `hermitcrm learn apply ID` applies one.

Add `--approach NAME` when you have more than one approach; the default is the
first. Tell Hermit why you changed a draft with `hermitcrm outreach ready ID
--tag too-long` (repeatable).

Related: [Outreach bot](/help/outreach), [Playbook](/help/playbook), [CLI](/help/cli)
