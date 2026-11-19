---
name: building-the-review-page
description: Build or change the standalone review page (scripts/_review.py, `npx ffmpeg-skill review`) — the editor-style screen where a person looks at a render project and its result and composes an instruction for their agent. Covers the fixed constraints (one offline HTML file, nothing executed, no new dependency, not a contract tool), the 16:10 three-column layout, the numbering scheme every element carries (S, C, T, A, M, R, P, #), the instruction composer, options read from the contract, playback and waveforms, the interface checklist, and how to verify a change in a real browser. Use when adding a panel, a control or a field to the review page, when changing its HTML/CSS/JS, or when reviewing such a change.
---

# Building the Review Page

The review page is for a person who knows Premiere or DaVinci and directs an
agent. It shows what was planned and what was measured, and it turns clicks into
an instruction the agent can act on. It is not an editor: nothing on it changes
media.

## Constraints that do not move

- **One HTML file, offline.** No network request, no CDN, no web font. Images,
  the output video and stills are local files beside the page.
- **The page runs nothing.** It writes text (an instruction, an edited project
  JSON). Rendering again is `render.py`, started by the person or their agent.
- **No new dependency.** Plain HTML, CSS and JavaScript. No framework, no build
  step. Third-party editor kits (Remotion, Editframe and the like) are out for
  this reason.
- **Standalone only (#633).** Not a contract tool, not listed by the MCP server.
- **Shipped Python is under a ceiling** (`.github/code-budget.json`). Keep the
  page's markup, CSS and JS in a template file that `_review.py` fills, not in
  Python string literals.
- **Every write is guarded.** The page, each still and the marker go through
  `write_new()` and `is_input()` in `_review.py`: staged beside the target,
  replaced by name, refused when the target is an input by name or by file
  identity. A new output file uses the same two calls.

## Layout: one 16:10 screen, three columns

No page scroll at 1440×900 or 1920×1080. A panel with more rows than fit scrolls
inside itself.

| Column | Top | Bottom |
| --- | --- | --- |
| Left | Sources: one card per file, with its probe facts | Work steps: each tool that ran, in order |
| Centre | Viewer: Source / Program / side by side, safe-area overlay, loudness meter, transport | Timeline: ruler, V, T, A tracks with waveforms, markers, ranges, playhead |
| Right | Inspector: the selected item's values and its options; measured against target; what a person must confirm | Instruction composer, always visible |

The header carries the project, the output, the PASS and to-check counts, the
run switch (this run against the one before) and Save project / Copy
instruction.

## Every element has a number

A person points at things by number; the agent reads the same numbers.

| Prefix | Is |
| --- | --- |
| `S1` | a source file |
| `C1` | a clip on the video track |
| `T1` | a caption cue |
| `A1` | an audio track |
| `M1` | a marker: a position to look at (from `check.py`, or set by the person) |
| `R1` | a range the person marked with In and Out |
| `P1` | a measured property against its target |
| `#1` | a work step: one tool run, in execution order |

Numbers are stable within one page build. A work step shows the tool, what it
did in one line, and the measured before and after (`372.4 s → 60.0 s`), taken
from that step's result document, never recomputed by the page.

## The instruction composer

- Clicking any numbered element selects it and adds a row for it.
- Each row has one free-text field: what should change.
- Choosing an option in the inspector, or editing a caption's text there, writes
  the row's text itself.
- The page assembles one instruction: the project file, one line per row
  (`- C2 (clip 2): out to 05:28.0`), and the legend of prefixes. Copy puts it on
  the clipboard. The text stays visible, so it can be copied by hand.

## Options come from the contract

The choices offered for a work step are that tool's real flags, read from
`python3 scripts/_contract.py --json`: never a hand-kept list. The default shown
is the value the run used. An option appears in the instruction only when it
differs from that value. A flag the tool does not have is not offered.

## Playback and waveforms

- **Waveforms** are images from `waveform.py`, one per audio track.
- **After a render**, the output plays in a `<video>` element. The playhead
  follows `currentTime`; clicking the ruler seeks; markers and ranges read the
  same clock.
- **Before a render** there is no output: the page says so. A rough play of the
  sources in order is labelled as rough (no captions, no loudness pass).
- **A format the browser cannot decode** (ProRes, some HEVC, MKV) needs a small
  H.264 proxy made at build time. Say on the page that the picture is a proxy.
- Keys: Space play, J K L shuttle, I and O range, M marker. Every key action
  also has a button.

## Interface checklist

Written against the Web Interface Guidelines
(github.com/vercel-labs/web-interface-guidelines); check the current list when
reviewing.

- Actions are `<button>`; icon-only buttons have `aria-label` and a `title`;
  decorative SVG is `aria-hidden`.
- Every input has a label; a checkbox and its label are one target.
- A visible `:focus-visible` ring on everything pressable; hover is visibly
  different from rest.
- Numbers that change in place (timecode, meters) use tabular figures.
- Text that can be long truncates or wraps; flex children that hold text have
  `min-width: 0`.
- Status that changes without a click ("Copied") is announced
  (`aria-live="polite"`).
- Motion stops under `prefers-reduced-motion`; nothing autoplays.
- States differ by more than hue: PASS is a filled green pill, to-check is an
  outlined white pill, unverified is grey.
- Green means measured and passed (the project's design rule). Do not spend it
  on decoration.

Colours, type and spacing come from the project's design tokens (`site/index.html`
is the reference implementation; ink ground, one key green, Manrope with the
Japanese fallbacks, monospace for commands and measured values).

## Verifying a change

1. Build the page from a real project and a real `render.py --json` result.
2. Open it with the pre-installed Playwright at 1440×900 and at 1920×1080.
   Take a screenshot of each and look at it.
3. Assert in the same script: no horizontal scroll; no element outside the
   viewport; every button has an accessible name; clicking `C1` adds a `C1` row
   and the copied text holds it.
4. Run the review-page test in `tests/test_orchestration.py`. A new write path
   gets a case there with a hard-linked and a symlinked target.

A claim that the page "looks right" needs the screenshot. Without one, say the
look was not checked.
