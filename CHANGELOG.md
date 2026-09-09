Fix: do not remove input files when ffprobe fails

- Add an explicit _is_ffmpeg() guard before partial-output cleanup in _run_captured().
- This prevents read-only tools like ffprobe from deleting their input file when they fail.
- Add a regression test to ensure probe failures do not remove input files.

(Branch: fix/ffprobe-delete-input)
