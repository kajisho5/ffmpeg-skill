--- a/scripts/_common.py
+++ b/scripts/_common.py
@@
 def _run_captured(cmd: List[str], check: bool) -> subprocess.CompletedProcess:
@@
-    if proc.returncode != 0:
-        # Cleanup happens for every failed ffmpeg invocation, not just the check=True/_fail()
-        # path: a handful of scripts (cut.py, loudness.py, silence.py, sync.py) call run() with
-        # check=False so they can compose their own die() message from proc.stderr, but the
-        # partial-output risk is identical either way -- and for a script that retries into the
-        # same output path after a check=False failure (e.g. color.py's --retag copy-then-
-        # reencode fallback), removing the stale partial first is strictly safer than leaving it
-        # for -y to overwrite.
-        _cleanup_partial_output(cmd)
-        if check:
-            _fail(cmd, proc.returncode, proc.stderr)
+    if proc.returncode != 0:
+        # Only consider cleanup for ffmpeg (writing) commands: probing tools like ffprobe have
+        # the path to their INPUT as the final argv element and must never cause that file to be
+        # removed on failure. _cleanup_partial_output itself already guards on _is_ffmpeg(),
+        # but being explicit here documents intent and avoids surprising behaviour when callers
+        # change how they construct argv.
+        if _is_ffmpeg(cmd):
+            _cleanup_partial_output(cmd)
+        if check:
+            _fail(cmd, proc.returncode, proc.stderr)
     return proc
