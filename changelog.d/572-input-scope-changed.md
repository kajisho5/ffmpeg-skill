### Changed

- The ffmpeg command lines in a result's `commands` (and in a plan) now carry `-protocol_whitelist file` before each input's own options, because that is what runs (#572).
