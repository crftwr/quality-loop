+++
title = "Change a note's text"
+++

## Prompt

In jot, my note that says "milk" should say "oat milk" instead. Can you
change it?

## Screen

None. The room drives jot itself.

## Must

- notes.txt afterwards holds "oat milk" where "milk" was, and every other
  note exactly as before, in the same order.
- jot was left by its own quit key, not abandoned running.

## Must not

- Delete any note.

## Live check

Start jot. Check that the list shows "oat milk" and no "milk" note. Then try
the key the manual gives for changing a note on another note, and press Esc
if anything asks for text, so nothing is changed. Quit with `q`.
