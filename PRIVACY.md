# Privacy

ffmpeg-skill is a set of command-line tools that run on your own machine. This page says what
they do with data, as of the version it ships with.

- **No collection.** The tools send no telemetry, analytics or usage data, and the project runs
  no server that could receive any. There is no account and nothing to sign in to. The one record
  of use they can keep is local, off by default, and described below.
- **Your media stays local.** Video, audio, subtitles and project files are read from and written
  to the paths you give. Nothing is uploaded.
- **No network use by the tools themselves**, and no API key is read. One exception:
  transcription (`caption.py --transcribe`, `silence.py --transcribe` with `--filler` or a sentence
  flag) runs a speech
  engine you installed yourself (whisper.cpp, faster-whisper, openai-whisper or parakeet). On its
  first run such an engine may download its model from its own provider, and a Hugging Face
  client uses a token you are logged in with. What those engines and providers do is covered by
  their own policies.
- **Installing** from npm, GitHub or a plugin directory is a download from that service, under
  that service's policy.
- **Environment variables** the tools read are configuration only: the `FFMPEG_SKILL_*` switches,
  `PARAKEET_MODEL` and `PARAKEET_CPP_MODEL` for a speech model, `PATH`, `PATHEXT` and `WINDIR`
  to find programs and fonts, and `XDG_STATE_HOME`, `LOCALAPPDATA` and `HOME` (`USERPROFILE` on
  Windows) only to place the usage record below when it is turned on.

## The usage record (off unless you turn it on)

`FFMPEG_SKILL_USAGE_LOG` turns it on (#689). Unset, empty or `0`, the default, nothing is recorded
and no file is written anywhere.

- **Where.** `FFMPEG_SKILL_USAGE_LOG=1` writes `ffmpeg-skill/usage.jsonl` under `$XDG_STATE_HOME`
  (`~/.local/state` when that is unset; `%LOCALAPPDATA%` on Windows); an absolute path writes that
  file instead. On macOS and Linux the file, and the directory holding it when a tool creates it, are
  created readable by you only. Nothing is sent anywhere: no tool has code that could send it.
- **What one line holds.** Each run of a tool appends one JSON line, dry runs and refusals
  included, and a tool that another runs (render's stages, batch's items, verify's steps) writes
  its own:
  `{"ffmpeg_major": 6, "flags": ["--end", "--json", "--start", "-o"], "kind": null, "reason": null, "seconds": 0.81, "status": "completed", "tool": "cut", "version": "4.17.0"}`.
  `tool` and `version` are the skill's; `status` is `completed` or `failed`; `kind` and `reason` are
  the failure's `error.kind` and `error.reason` codes (`usage` for a command line the argument
  parser refused, `internal` for a crash); `flags` are the names of the options given, as the tool
  spells them, sorted; `seconds` is how long the run took; `ffmpeg_major` is the FFmpeg major
  version, when the run read it.
- **What it never holds.** The value of any option, a positional argument, a path, a file name, a
  message, subtitle or title text, anything read from your media, a time of day, a host or user
  name. An option the tool does not define is left out, since its name is text you typed.
- **Where it is not written.** A path that is not absolute, that is outside `FFMPEG_SKILL_ROOTS`
  when that is set, that is one of the run's inputs or outputs, or that is not a regular file: the
  tool prints a warning on stderr and its result and exit code are unchanged.
- **Reading it.** `python3 scripts/_contract.py doctor --usage` prints the counts (runs per tool
  and status, failures by kind and reason, option names, versions) as JSON without the file's path,
  to paste into an issue if you want to. Nothing reads the file otherwise.
- **Deleting it.** Delete the file (`rm ~/.local/state/ffmpeg-skill/usage.jsonl` with the default
  location); `doctor --usage` names it on stderr. Unset the variable to stop recording.

Questions: open an issue at https://github.com/kajisho5/ffmpeg-skill/issues.
