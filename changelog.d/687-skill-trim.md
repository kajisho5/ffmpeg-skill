### Changed

- SKILL.md keeps only the request rows whose command is not the obvious one (80 rows to 35; 220
  lines to 175, 19.6 KB to 14.8 KB). Every request, with its variants, is in
  `references/requests.md`, which SKILL.md points to and which names every tool; the contract's
  per-tool `examples` take a tool's rows from there when SKILL.md's table does not name it. The
  SKILL.md ceiling is now 180 lines and 16,000 bytes, so the table cannot grow back (#687).
