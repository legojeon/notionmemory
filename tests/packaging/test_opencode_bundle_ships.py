"""opencode 셰임(bundle/plugin.ts)이 실제 wheel 에 동봉되는가.

tests/packaging/test_pi_bundle_ships.py 와 동일한 방식으로 `python -m build` 로
실제 wheel 을 빌드해 안을 들여다본다 — package-data 글롭 문법이 setuptools 에서
기대대로 동작하는지까지 확인한다.
"""
import glob
import pathlib
import subprocess
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[2]

# tests/conftest.py's autouse `no_real_cli` fixture monkeypatches the shared
# subprocess.run (detection.subprocess is the same module object) to always
# return a stub CompletedProcess for every test, to keep CLI-detection tests
# hermetic. That collides with this test's need to actually run a wheel build,
# so we capture the genuine subprocess.run here at import time — before any
# per-test fixture has a chance to patch it — and call that reference below.
_real_run = subprocess.run


def test_opencode_shim_is_included_in_wheel(tmp_path):
    _real_run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(tmp_path)],
        cwd=ROOT, check=True, capture_output=True,
    )
    wheels = glob.glob(str(tmp_path / "*.whl"))
    assert wheels, "no wheel built"
    with zipfile.ZipFile(wheels[0]) as z:
        names = z.namelist()
    assert any(n.endswith("providers/opencode/bundle/plugin.ts") for n in names), \
        f"opencode shim missing from wheel; sample: {[n for n in names if 'providers' in n][:20]}"
