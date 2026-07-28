#!/usr/bin/env bash
# 임시 클론에서 전체 테스트를 돌린다 — 커밋되지 않은 생성물 때문에 작업 트리에서만
# 통과하는 사고(2026-07-20)를 구조적으로 막는다.
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

echo "클론: $repo_root → $work/clone"
git clone --quiet "$repo_root" "$work/clone"
cd "$work/clone"

echo "venv 생성"
python3 -m venv venv
# 편집설치는 빌드 격리가 안 돼 venv 의 setuptools 를 직접 쓴다 — PEP 639 SPDX
# license = "MIT" 는 setuptools>=77 이 필요하므로 먼저 올린다.
./venv/bin/pip install --quiet -U "setuptools>=77" pip
./venv/bin/pip install --quiet -e . pytest
./venv/bin/pip install --quiet build twine

echo "전체 테스트"
./venv/bin/python -m pytest -q

# 위의 `pip install -e .` 는 소스 트리를 그대로 읽는다 — package-data 가 틀려도
# 아무 일도 안 일어난다. 그래서 실제로 배포되는 형태(wheel)를 따로 만들어
# 런타임 데이터가 안에 들어 있는지 본다. 이 스크립트가 막으려던 사고
# (커밋 안 된 생성물)와 같은 종류의 사각지대가 한 층 위에 또 있었다:
# web/assets 와 skills/notes/prompts 가 wheel 에서 통째로 빠져 있었고,
# 그 결과 `uv tool install .` 사용자는 settings 404 + notes FileNotFoundError.
# 회귀 가드: stray top-level 디렉터리가 있어도 빌드가 깨지면 안 된다 — flat-layout
# 자동탐색이 untracked data/·notion/ 를 주워 빌드를 거부한 적이 있다(명시 packages.find 로 수정).
mkdir -p stray_toplevel_dir && touch stray_toplevel_dir/x.py

echo "sdist + wheel 빌드"
./venv/bin/python -m build --outdir "$work/dist" . 2>&1 | tail -3
rm -rf stray_toplevel_dir

# 위의 빌드는 실제로 배포되는 형태다. wheel(zip)과 sdist(tar) 둘 다에 런타임 데이터가
# 들어 있는지 본다 — sdist 포함은 package-data 만으로 보장되지 않아 따로 확인해야 한다.
echo "wheel + sdist 런타임 데이터 검증"
./venv/bin/python - "$work"/dist <<'PY'
import pathlib
import sys
import tarfile
import zipfile

dist = pathlib.Path(sys.argv[1])

# 요구 목록을 손으로 적지 않고 소스 트리에서 뽑는다 — 그래야 앞으로 새 데이터
# 디렉터리를 추가하고 package-data 갱신을 잊었을 때 여기서 시끄럽게 실패한다.
required = sorted(
    p.as_posix() for p in pathlib.Path("notionmemory").rglob("*")
    if p.is_file() and p.suffix != ".py" and "__pycache__" not in p.parts)
if not required:
    sys.exit("소스 트리에서 런타임 데이터를 하나도 못 찾았다 — 검증이 공허하다")

whl = next(dist.glob("notionmemory-*.whl"))
whl_names = set(zipfile.ZipFile(whl).namelist())
miss_whl = [r for r in required if r not in whl_names]

sdist = next(dist.glob("notionmemory-*.tar.gz"))
with tarfile.open(sdist) as t:
    sdist_names = {m.name.split("/", 1)[1] for m in t.getmembers() if "/" in m.name}
miss_sdist = [r for r in required if r not in sdist_names]

if miss_whl or miss_sdist:
    for label, miss in (("wheel", miss_whl), ("sdist", miss_sdist)):
        for m in miss:
            print(f"  {label} 누락: {m}")
    sys.exit("pyproject.toml 의 [tool.setuptools.package-data] (필요시 MANIFEST.in) 를 고치세요")
print(f"wheel·sdist 각각 런타임 데이터 {len(required)}건 확인")
PY

echo "twine check (배포 메타데이터 유효성)"
./venv/bin/twine check "$work"/dist/*

echo "OK — 깨끗한 체크아웃에서 전체 테스트 + wheel·sdist 데이터 검증 + twine check 통과"
