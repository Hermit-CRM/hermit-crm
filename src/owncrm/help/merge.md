# Merge

Combine two companies, or two contacts of one company, into one record in a single commit.

## Companies

On the company page, pick the company to merge **into this one** and click
Compare. The merge page shows every field side by side with a radio per side;
the default is this company's value, or the other's when this one is empty.
Tags and notes can be combined. Contacts and interactions of the dropped
company move over (a contact slug that collides gets `-2`), its stage history
is merged by date, its folder is deleted, and the commit is
`company: <dropped> merged into <kept>`. The history stays in git.

## Contacts

On a contact page (when the company has more than one contact), pick another
contact to merge into this one. Same side-by-side choice; the dropped
contact's interactions are re-pointed and renamed to the kept contact. Commit:
`contact: <company>/<dropped> merged into <kept>`.

## Undo

Every merge is one commit: `git revert <sha>` in the data folder, then
`owncrm rebuild`.

Related: [Companies](/help/companies), [Contacts](/help/contacts), [Data format](/help/data-format)
