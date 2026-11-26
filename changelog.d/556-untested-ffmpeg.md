### Added

- An FFmpeg outside the majors the test suite runs (6.x-9.x), a git or vendor build, or one whose
  version cannot be read now adds one `ffmpeg_version_untested` warning to every tool's result, and
  `doctor` reports it as `ffmpeg_tested` (#556). Nothing is refused; the run goes on as before.
