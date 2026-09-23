# Leaving findings as comments in the source document

When the checked text came from a Google Doc or a Notion page, the
needs_review findings can go back into it as comments, each on its
passage, the way an editor's comment does. Two routes:

- **Google Doc + a browser.** Keyboard shortcuts in the Docs editor.
  Claude in Chrome first: it is the user's own Chrome, signed in to
  Google, so the doc opens with their access and their name on the
  comments. The built-in browser is the fallback; it has no logins, so
  ask the user to sign in there first, and never sign in for them.
- **Notion page + the Notion connector.** One tool call per comment,
  anchored by a start…end snippet of the passage. No browser.

The user's "yes" or "do it" to the offer is the go-ahead; comments are
reversible, so there is no second confirmation and no preview step.

If neither route is available, or the document is read-only, say so in
one line and stop. Never try to sign in, request access, or change the
document's mode.

## Prepare the comments

    python3 scripts/assemble.py export comments source.txt check.json comments.json

Each entry has the comment in two forms: `text`, plain with each
source's label and URL on their own lines (Google Docs renders bare
URLs as links), and `markdown`, with inline links (Notion). It also has
`find`, a short literal fragment of the passage, curly quotes
straightened, extended until it occurs once in the checked text, and
`selection`, the passage's first ten and last ten characters joined by
an ellipsis, the form Notion anchors on. Use these, never the whole
quote: the document's punctuation and line breaks may differ from the
text you checked.

## Google Docs: the sequence, per comment

Open the doc once in Claude in Chrome (`navigate`), wait for it to
load, press Escape to dismiss any link-preview popup, and click once in
the body text so the editor has focus. Then for each entry, in one
`browser_batch`:

| Step | Mac | Windows / Linux | What it does |
|---|---|---|---|
| 1 | `cmd+f` | `ctrl+f` | opens Docs' own find box |
| 2 | type `find` | | the match is highlighted; the box shows "1 of 1" |
| 3 | `Escape` | | closes the box and leaves the match **selected** |
| 4 | `cmd+alt+m` | `ctrl+alt+m` | opens a comment on the selection |
| 5 | type `text` | | newlines are fine; Enter does not post |
| 6 | `cmd+Return` | `ctrl+Enter` | posts the comment |
| 7 | wait 2s, `find` "Cancel" | | a Cancel button means the comment is still an unsaved draft |
| 8 | screenshot | | shows which passage was highlighted |

Put a one-second wait after steps 1, 3, 4 and 5; the editor needs it.

**A comment counts only once it is saved.** While it is a draft, its
box still has a text field with a Comment and a Cancel button. Once
saved, the box closes and the comment shows the author's name and a
time. If step 7 finds a Cancel button, the shortcut did not post: click
the Comment button beside it, by its ref from `find`, wait two seconds
and check again. Do not open the next comment while a draft is open. A
draft and a saved comment look almost the same in a screenshot, so the
screenshot confirms only that the highlighted passage is the one you
meant; it never confirms that the comment was saved.

If the find box showed "0" or "1 of 2+", press Escape, do not open a
comment, and retry with a longer fragment from `quote`. If the passage
no longer exists (the doc was edited since the check), skip it and say
so at the end.

Comments only: never type into the document body, accept a suggestion,
or resolve or delete anything. One comment per finding. Leave the tab
open on the doc when done.

## Notion: one call per comment

For each entry, call the connector's create-comment with the page id,
`selection_with_ellipsis` set to the entry's `selection`, and the
markdown set to the entry's `quote` in quotation marks on its own first
line, then the entry's `markdown`. The quote line matters: Notion
anchors a comment to the block that contains the selection, not to the
phrase, so two findings in one paragraph become two comments on the
same block and the reader needs the quoted words to tell them apart.
If the call reports that the selection is ambiguous or not found, widen
the snippet from `quote` and retry once; if it still fails, skip the
finding and say so at the end. Never edit the page's blocks.

## Verify and report

Verify in the document, never from screenshots: the count you report
is the count you read back.

Google Docs: if the Drive connector is available, read the doc with
comments included and confirm each comment appears as an open thread on
its passage. Otherwise reload the doc, so that what you read is what
Google saved, open the comment history (`cmd+alt+shift+a`, or
`ctrl+alt+shift+a`), and read the panel as page text. Match each entry
you posted to a saved comment by its first words. Post any that are
missing and read again.

Notion: fetch the page with discussions included and confirm each
comment sits on its block.

Then, in chat, one line: how many comments the document now holds from
this check, and which findings were skipped and why. Not a recap of the
findings; they are in the document and the report.
