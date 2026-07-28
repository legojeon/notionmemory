"""wheel 에 런타임 데이터가 동봉되는가.

`pip install -e .` 는 소스 트리를 그대로 읽으므로 package-data 가 틀려도 아무 일도
일어나지 않는다 — scripts/verify_clean_clone.sh 조차 editable 설치를 쓰기 때문에
같은 사각지대를 공유한다. 그 결과 이 마일스톤이 겨냥한 설치 방식
(`uv tool install .` / `pip install .` / PyPI)에서만 조용히 깨졌다:
web/assets 가 빠져 settings 대시보드가 404, notes/prompts 가 빠져 notes 스킬이
FileNotFoundError — SKILL.md 는 에이전트에게 둘 다 실행하라고 시키면서.

여기서는 선언(package-data 글롭)이 실제 데이터 파일을 전부 덮는지 본다.
실제 wheel 빌드 검증은 scripts/verify_clean_clone.sh 가 한다(두 층 다 필요하다 —
이 테스트는 빠르고 항상 돌고, 스크립트는 setuptools 의 실제 동작까지 확인한다).
"""
import tomllib
from pathlib import PurePosixPath
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG_ROOT = ROOT / "notionmemory"
TOP = "notionmemory"


def _package_data() -> dict[str, list[str]]:
    raw = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return raw["tool"]["setuptools"]["package-data"]


def _data_files() -> list[PurePosixPath]:
    """패키지 안의 비-파이썬 파일 = wheel 에 들어가야 할 런타임 데이터."""
    out = []
    for p in sorted(PKG_ROOT.rglob("*")):
        if not p.is_file() or p.suffix == ".py" or "__pycache__" in p.parts:
            continue
        out.append(PurePosixPath(p.relative_to(PKG_ROOT).as_posix()))
    return out


def _is_declared(rel: PurePosixPath, table: dict[str, list[str]]) -> bool:
    for key, patterns in table.items():
        if key == TOP:
            base = PurePosixPath(".")
        elif key.startswith(f"{TOP}."):
            base = PurePosixPath(key[len(TOP) + 1:].replace(".", "/"))
        else:
            continue
        try:
            inner = rel.relative_to(base) if str(base) != "." else rel
        except ValueError:
            continue
        if any(inner.full_match(pattern) for pattern in patterns):
            return True
    return False


def test_every_runtime_data_file_is_declared_in_package_data():
    """새 데이터 디렉터리를 추가하고 package-data 갱신을 잊으면 여기서 터진다."""
    table = _package_data()
    missing = [str(rel) for rel in _data_files() if not _is_declared(rel, table)]
    assert missing == [], (
        "wheel 에 안 들어가는 런타임 데이터가 있습니다 — pyproject.toml 의 "
        f"[tool.setuptools.package-data] 에 글롭을 추가하세요: {missing}")


def test_the_two_runtime_data_dirs_actually_exist_where_code_reads_them():
    """글롭만 맞고 파일이 사라지면 위 테스트는 공허하게 통과한다."""
    assert (PKG_ROOT / "web" / "assets" / "index.html").is_file()
    assert (PKG_ROOT / "agent_skills" / "memory" / "SKILL.md").is_file()


def test_packages_are_explicitly_declared_not_auto_discovered():
    """Flat-layout 자동탐색은 stray top-level 디렉터리(data/·notion/)를 주워
    빌드를 거부한다. 명시적 find 설정이 있어야 빌드가 결정적이다."""
    raw = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    find = raw["tool"]["setuptools"].get("packages", {}).get("find")
    assert find is not None, "no [tool.setuptools.packages.find] — 빌드가 자동탐색에 의존"
    assert any(pat.startswith("notionmemory") for pat in find.get("include", []))


def test_pyproject_has_publish_metadata():
    raw = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    proj = raw["project"]
    import re
    assert re.match(r"^\d+\.\d+\.\d+$", proj["version"]), f"version not semver: {proj['version']!r}"
    assert proj.get("description", "").strip(), "missing description"
    assert proj.get("authors"), "missing authors"
    assert proj["authors"][0].get("name") and proj["authors"][0].get("email")
    assert proj.get("keywords"), "missing keywords"
    assert any("Python :: 3.13" in c for c in proj.get("classifiers", []))
    assert not any(c.startswith("License ::") for c in proj.get("classifiers", [])), \
        "SPDX 라이선스를 쓰면 License:: classifier 는 넣지 않는다(setuptools 77+ 충돌)"
    urls = proj.get("urls", {})
    assert any("github.com/legojeon/notionmemory" in v for v in urls.values())


def test_mit_license_declared_and_file_present():
    raw = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert raw["project"].get("license") == "MIT"
    assert raw["project"].get("license-files") == ["LICENSE"]
    lic = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "MIT License" in lic
    assert "Jaewoo Jeon" in lic


def test_readme_is_english_stub_korean_preserved():
    raw = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert raw["project"].get("readme") == "README.md"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "notionmemory" in readme
    assert "Install" in readme            # English section marker
    assert (ROOT / "docs" / "README.ko.md").is_file()  # 한국어 개발로그 보존
