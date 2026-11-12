#!/bin/bash -eu
# Build every fuzz/*_fuzzer.py into a standalone fuzzer. scripts/ is added to the bundle's import
# path so `_common` resolves inside the PyInstaller build exactly as it does from the checkout.
for fuzzer in "$SRC"/ffmpeg-skill/fuzz/*_fuzzer.py; do
  compile_python_fuzzer "$fuzzer" --paths "$SRC/ffmpeg-skill/scripts" --paths "$SRC/ffmpeg-skill/fuzz"
  name=$(basename "$fuzzer" .py)
  seeds="$SRC/ffmpeg-skill/fuzz/seeds/${name%_fuzzer}"
  if [ -d "$seeds" ]; then
    (cd "$seeds" && zip -q -r "$OUT/${name}_seed_corpus.zip" .)
  fi
done
