### Added

- Six use-case pages on the site, linked from the top of README (#690): a vertical short with
  captions, a podcast episode as an audiogram, cleaning up a phone clip, a cut-down of a long
  recording, one master to several platforms, and a talk from two cameras. Each is one request end
  to end: what you say, the commands the skill runs on the clips in `demos/footage/`, what came back,
  the result (clips and GIFs already in the repository) and what to check.
  `test_use_case_pages_commands_are_accepted_by_the_tools` runs every command on them under
  `--dry-run`, so a renamed flag fails CI.
- `README.ja.md`, a Japanese translation of README, linked both ways and published on the site
  (#690). `test_readme_ja_keeps_the_english_headings_and_commands` keeps its headings, command
  blocks, inline code and tool count in step with README.md; the Development section and the
  agent-eval history rows stay English only.
