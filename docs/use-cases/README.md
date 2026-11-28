# Use cases

Six requests, each end to end: what you say to the agent, the commands the skill runs, what came
back, the result, and what to check before you deliver it. The commands were run on the clips in
[`demos/footage/`](../../demos/footage/README.md) with 4.17.0, and a test runs every one of them
again under `--dry-run` on each pull request (`test_use_case_pages_commands_are_accepted_by_the_tools`
in `tests/test_contract.py`), so a renamed flag fails CI instead of this page.

| You want | Page | Tools |
|---|---|---|
| a vertical Reels short with captions, from a landscape talk | [A vertical short with captions](vertical-short.md) | `loudness`, `insert`, `join`, `fit`, `background`, `overlay`, `audio`, `caption`, `graphics`, `export`, `check`, `look` (or `render --template reels`) |
| a podcast episode at podcast loudness, and a video of it with a waveform | [A podcast episode as an audiogram](audiogram.md) | `audio`, `loudness`, `check`, `waveform` (or `render --template audiogram`) |
| a shaky or dark phone clip made usable | [Cleaning up a phone clip](phone-clip.md) | `probe`, `stabilize`, `loudness`, `color`, `denoise`, `look` |
| the dead air and the fillers out of a recording | [A cut-down of a long recording](cut-down.md) | `proxy`, `silence`, `look` |
| one master delivered to TikTok, Reels, Shorts, YouTube, X, LinkedIn and Facebook | [One master, several platforms](platforms.md) | `render --template all`, `loudness --versions`, `export`, `check` |
| a talk from two cameras, cut on a switch list, and the slides beside the speaker | [A talk from two cameras](two-cameras.md) | `cut`, `crop`, `multicam`, `look`, `overlay` |

Every clip on these pages is AI-generated with Google Veo (the people do not exist) or shot on a
phone by the maintainer; [`demos/footage/README.md`](../../demos/footage/README.md) says which is
which. The commands are written to run from the root of a checkout. An installed skill has the same
scripts in `~/.claude/skills/ffmpeg-skill/scripts/` (Cursor: `~/.cursor/skills`, Codex:
`~/.agents/skills`).

In practice you only say the request: the agent picks the tools from `SKILL.md`, runs them, and
reports `Done:` or `Failed:` with what it measured. These pages show what happens in between.

More: [the demo gallery](../demos.md) (every tool, before and after, with its command), [the
showcase notes](../showcase.md) (the twelve clips on the website), and [examples/README.md](../../examples/README.md)
(requests and the commands behind them).
