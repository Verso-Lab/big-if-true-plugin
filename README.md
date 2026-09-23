# Big If True

A fact-checking plugin for Claude by [Verso](https://verso.ink). Give it an
article, a draft, a newsletter or a press release: it finds every checkable
claim, verifies each against primary records and the live web, and delivers
an annotated report where every claim carries a verdict and its sources.

- **Supported**: two independent sources agree, or one definitive source settles it.
- **Couldn't verify**: the evidence doesn't settle it either way.
- **Needs review**: something could be off here. Have a look.

More, including how we tested it: [verso.ink/big-if-true](https://verso.ink/big-if-true).

## Install

**Claude Code and Cowork**: from the Claude plugin directory, or add this
repository as a marketplace:

```
/plugin marketplace add Verso-Lab/big-if-true-plugin
/plugin install big-if-true@verso
```

**Claude app (chat)**: download the skill from
[verso.ink/big-if-true](https://verso.ink/big-if-true) and upload it under
Settings → Capabilities → Skills.

Then ask Claude to fact-check something. The plugin needs web search; with
code execution it builds the report page and runs the official-data lookups.

## What's in here

`skills/big-if-true/` is the skill: the method (`SKILL.md`), the claim
extraction rules and per-topic evidence routes (`references/`), the report
builder and data lookups (`scripts/`), and the report page (`assets/`).

This repository is published from Verso's development repository at each
release; changes are made there and measured against a test set before they
ship. Feedback and bug reports: [team@verso.ink](mailto:team@verso.ink) or an
issue here.

## Licence

MIT, © 2026 Verso Lab LLC. See [LICENSE](LICENSE).
