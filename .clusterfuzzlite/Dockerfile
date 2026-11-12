# ClusterFuzzLite build image. The base is pinned by digest (Scorecard Pinned-Dependencies) and
# already carries atheris and PyInstaller; nothing is installed from a package index here.
FROM gcr.io/oss-fuzz-base/base-builder-python@sha256:21f6fab17ace4dc76e1c56de91ee95d3d03da021df94b41056ba036f6c6f55e9
COPY . $SRC/ffmpeg-skill
WORKDIR $SRC/ffmpeg-skill
COPY .clusterfuzzlite/build.sh $SRC/
