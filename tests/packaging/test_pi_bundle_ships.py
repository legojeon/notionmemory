"""pi 셰임(bundle/index.ts)이 실제 wheel 에 동봉되는가.

tests/test_packaging.py 의 선언적 커버리지 테스트(글롭이 소스 트리의 모든 데이터
파일을 덮는지)와 달리, 여기서는 scripts/verify_clean_clone.sh 와 같은 방식으로
`python -m build` 로 실제 wheel 을 빌드해 안을 들여다본다 — package-data 글롭
문법이 setuptools 에서 기대대로 동작하는지까지 확인한다.
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


def test_pi_shim_is_included_in_wheel(tmp_path):
    _real_run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(tmp_path)],
        cwd=ROOT, check=True, capture_output=True,
    )
    wheels = glob.glob(str(tmp_path / "*.whl"))
    assert wheels, "no wheel built"
    with zipfile.ZipFile(wheels[0]) as z:
        names = z.namelist()
    assert any(n.endswith("providers/pi/bundle/index.ts") for n in names), \
        f"pi shim missing from wheel; sample: {[n for n in names if 'providers' in n][:20]}"
