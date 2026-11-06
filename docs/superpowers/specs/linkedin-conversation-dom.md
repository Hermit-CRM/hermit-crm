# What a LinkedIn conversation looks like in the page (spike 0.2)

Observed 2026-11-01, Chrome 156, UI language English, one account. Source: two
structure dumps taken by the owner with the throwaway spike kit (every letter masked to
`a`/`A`, digits to `9`, profile ids and hrefs dropped; class names, tags, roles and the
shape of attributes kept). Nothing here came from reading a real conversation.

This note is the contract for the bookmarklet's extractor. LinkedIn changes class names
every few months, so every selector below is a **guess that worked on the day**, and the
extractor must degrade to "could not read this page" (Task 4.1), never to a wrong import.

Fixtures built from this note, all invented people: `tests/fixtures/linkedin/`.

## 1. Two places, one markup

| Situation | Where the messages live | Tested |
|---|---|---|
| (a) Full Messaging page, `linkedin.com/messaging/thread/<id>/` | Ordinary DOM (light DOM) | Yes |
| (b) Chat bubble after **Message** on `linkedin.com/in/<name>/` | **Inside an open shadow root** on `div#interop-outlet` (`aside#msg-overlay` > `div.msg-overlay-conversation-bubble`) | Yes |
| (c) Bubble opened from `messaging/compose/?profileUrn=...&recipient=...` for someone already written to | Assumed identical to (b); same overlay | **Not run** |
| (d) Someone never written to (empty thread) | Unknown; expected: the list has no `li.msg-s-message-list__event` | **Not run** |

The list of messages is the same in (a) and (b): `ul.msg-s-message-list-content`, children
`li.msg-s-message-list__event`. **Consequences:**

- One extractor serves both. It must look for that `ul` in `document` **and in every open
  shadow root** (`document.querySelectorAll('*')` and each `el.shadowRoot`, recursively).
  A plain `document.querySelector` finds nothing in (b). This is why the first version of the
  spike bookmark "did nothing" in the bubble: `window.getSelection()` reports an empty
  selection when the selection is inside a shadow root.
- More than one such `ul` can exist (a full thread and a bubble open together, or two
  bubbles). The extractor must not guess: with a text selection, take the list that contains
  it (`Selection.getComposedRanges({shadowRoots})`); with exactly one list, take it; otherwise
  stop and say "more than one conversation is open, close the others".
- Chrome 137+ is needed for `getComposedRanges`. The spike ran on 156. The fallback for
  older browsers is `shadowRoot.getSelection()`, as the spike does.
- Only messages LinkedIn has already rendered are in the DOM (the list is virtualised and
  loads older messages when scrolled). The extractor reads what is there. No scrolling.

## 2. Anatomy of the list

```
ul.msg-s-message-list-content
  li.msg-s-message-list__top-of-list          (ignore)
  li.msg-s-message-list__loader.hidden        (ignore)
  li.msg-s-message-list__event                one per message
    time.msg-s-message-list__time-heading     day heading, ONLY on the first message of a day
    span.msg-s-event-listitem--group-a11y-heading.visually-hidden
                                              "<Name> sent the following messages at 12:26 AM"
                                              ONLY on the first message of a sender's run
    div.msg-s-event-listitem [--other] [--last-in-group] [--m2m-msg-followed-by-date-boundary]
        data-event-urn="urn:li:msg_message:(urn:li:fsd_profile:<ID, 39 chars>,<ID, ~90 chars>)"
        data-view-name="message-list-item"
      a.msg-s-event-listitem__link[href=/in/ACo...]     avatar link, first message of a run, other person only
      div.msg-s-message-group__meta                     ONLY on the first message of a run
        a[href=/in/ACo...] > span.msg-s-message-group__name     sender name
        span.t-12 "(He/Him)"                            optional pronouns, a separate span
        time.msg-s-message-group__timestamp             "6:24 PM" / "12:26 AM" / "18:24"
      div.msg-s-event-listitem__message-bubble
        div.msg-s-event-listitem__actions-container     hover menu: emoji, reply, options. IGNORE ALL OF IT
        div.msg-s-event-with-indicator
          div.msg-s-event__content
            p.msg-s-event-listitem__body                THE MESSAGE TEXT
          span.msg-s-event-with-indicator__sending-indicator--sent
              title="Sent at 11/1/2026, 6:24 PM"        own messages only, see 4
      ul.msg-reactions-reaction-summary-presenter__container   reaction pills. IGNORE
    div.msg-s-event-listitem__seen-receipts               "seen by" avatars. IGNORE
```

Rules the extractor can rely on, each seen in both dumps:

1. **Direction.** The modifier class `msg-s-event-listitem--other` is on messages from the
   other person and absent on the owner's own. (Observed in the bubble: the owner's own run has
   no `--other`, the other person's run has it. The same in the full page.) This is the primary signal. The server still cross-checks
   it against the sender name and the config `owner_name`, and asks when they disagree.
2. **Grouping.** A run of consecutive messages from one sender shows the name, the time and
   the avatar **once**, on the first `li`. The following `li`s have none of them. The
   extractor carries the last seen sender and time forward and marks carried values as
   inherited (`when_inherited: true`), because the real time of a follow-up message can be
   minutes later. The review page shows those with "~".
3. **Day headings.** `time.msg-s-message-list__time-heading` has **no `datetime` attribute**.
   Its text is `Today`, `Yesterday`, a weekday (`Saturday`) for the last week, or `Oct 29`
   (no year; a year is expected on old ones, not yet seen). It applies to every message
   until the next heading. The first message of a day carries the heading; the dump shows
   it as the first child of its `li`.
4. **Times.** `time.msg-s-message-group__timestamp` has **no `datetime` attribute** either.
   Text only, in the UI locale (`6:24 PM`; a 24-hour form is expected for other locales,
   not yet seen). Own messages also carry an **absolute** time in the title of
   `span.msg-s-event-with-indicator__sending-indicator--sent`:
   `Sent at 9/9/9999, 9:99 AA`, a US-style date in an English UI. Use it to verify the
   date the heading gave, never as the only source: its format follows the locale and a
   `01/11/2026` is ambiguous (1 Nov or 11 Jan). Only seen in English.
5. **Message id.** `data-event-urn` on `div.msg-s-event-listitem` is unique per message and
   stable across reloads (shape `urn:li:msg_message:(urn:li:fsd_profile:<39>,<~90>)`). The
   whole attribute value is the dedup key: `message_id = linkedin:<value>`. Do not parse it
   and do not depend on its length. The `fsd_profile` part is a member id; whose it is
   (sender or conversation) was not established, so treat it as opaque. Fall back to the
   hash key of the plan when the attribute is absent.
6. **Message text.** `p.msg-s-event-listitem__body`. Use `innerText`, which keeps the line
   breaks (`<br>`) and the spaces (`span.white-space-pre`). A link inside the text is an
   `a[target=_blank]` whose own text is the URL or a shortened form; `innerText` is enough.
   Emoji are plain text. Seen: a message whose body is only a link, a long multi-paragraph
   message, a message with a reaction pill.
7. **Other person.** In the full page, `a.msg-thread__link-to-profile[href=/in/ACo...]` in
   `.msg-title-bar` (its `title` is `View <name>'s profile`). In the bubble,
   `h2.msg-overlay-bubble-header__title > a[href=/in/ACo...]` holds the name. In both, the
   href is the member id form (`/in/ACoAAA...`), **not** the vanity URL the owner's contacts
   normally store. So matching to a Hermit contact is by name, then the member id can be
   remembered. (Recorded as a plan decision: still "not stored in v1".)
8. **Language.** `<html lang>` held `en`. Day words come from the UI language. The server
   parser handles en, nl, de, fr, es (plan); an unknown word asks.
9. **Attachments.** A conversation list entry said "You sent an attachment". The message
   DOM for an attachment was not captured. Expected: no `p.msg-s-event-listitem__body`, or
   one next to a file card. The extractor takes the text it finds and, when a message has
   an attachment-looking block but no text, emits `[attachment]`. To confirm with one more
   dump if attachments matter.

## 3. Things the dump did not show (open)

- **Group conversations.** Not captured. Detect by: the header has no single profile link,
  or the messages carry more than one distinct `--other` sender (by `a[href]` of the
  meta link). When in doubt, refuse. Needs one real group dump to be sure.
- **Empty thread (d)** and **compose-URL bubble (c)**, above.
- **Other UI languages** (a Dutch or German LinkedIn), including the 24-hour time form
  and the text of the sent-indicator title.
- **Messages from a sponsored or InMail sender**, system rows ("You are now connected"),
  and "message deleted" rows: probably an `li.msg-s-message-list__event` without a body.
  The extractor skips an `li` with no `p.msg-s-event-listitem__body` and no attachment block.

## 4. What the extractor sends

Raw pieces only (plan: dumb client, smart server). One item per `li` that has a body:

```json
{"v": 1, "url": "https://www.linkedin.com/in/<vanity-or-ACo>/", "layout": "bubble",
 "other": {"name": "Alex Voorbeeld", "href": "/in/ACoAAA..."},
 "lang": "en", "now_local": "2026-11-01T14:55", "tz_min": -60,
 "items": [{"urn": "urn:li:msg_message:(...)", "is_other": true,
            "who": "Alex Voorbeeld", "who_href": "/in/ACoAAA...",
            "day": "Saturday", "time": "6:24 PM", "inherited": false,
            "sent_title": "Sent at 10/31/2026, 6:24 PM",
            "text": "Hi Sam,\n..."}]}
```

`now_local` and `tz_min` let the server resolve "Today" and "Saturday" against the
**browser's** clock rather than the server's. Both are the same Mac here; they are sent anyway.
