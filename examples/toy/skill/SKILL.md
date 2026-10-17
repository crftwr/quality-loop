---
name: greeter
description: Write greeting files in the house style. Use when the user asks for a greeting for someone.
---

# Greeter

A greeting is one file, `greeting.txt`, in the `out/` directory of the
greeter home (the directory the user's TASK names, or `GREETER_HOME` below).

1. Read `style.txt` in the greeter home. It is one word: `plain` or `uppercase`.
2. Write `out/greeting.txt` holding exactly one line, `Hello, <name>!`,
   followed by a single newline - with the name uppercased when the style is
   `uppercase`. Create `out/` first if it does not exist.
3. Do not change `style.txt`. It is the user's.

GREETER_HOME is given in RULES.md.
