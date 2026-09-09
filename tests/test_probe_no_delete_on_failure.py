from pathlib import Path
import subprocess
import sys


def test_probe_failure_does_not_delete_input(tmp_path):
    # Resolve the repo root and the probe script path reliably
    repo_root = Path(__file__).resolve().parent.parent
    probe = repo_root / "scripts" / "probe.py"
    decoy = tmp_path / "decoy.txt"
    decoy.write_text("not a video", encoding="utf-8")

    proc = subprocess.run([sys.executable, str(probe), str(decoy)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    # probe should fail (non-zero exit code) when given a non-media file
    assert proc.returncode != 0, f"probe unexpectedly succeeded: stdout={proc.stdout!r} stderr={proc.stderr!r}"
    # but the input file must still exist afterwards
    assert decoy.exists(), "probe failure removed the input file"
