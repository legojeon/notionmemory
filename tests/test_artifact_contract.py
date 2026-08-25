"""설치물 계약 — 새 스킬은 자기 설치물을 매니페스트에 등록해야 한다.

이 테스트가 깨지면 규칙 위반이 아니라 '아직 결정하지 않았다'는 뜻이다.
아티팩트를 등록하거나, 설치물이 없음을 OWNS_NOTHING 에 명시하거나 둘 중 하나를 하라.
"""
from notionmemory.app import build_registry
from notionmemory.core import skill_assets
from notionmemory.core.install import manifest


def _skill_ids(tmp_path) -> set[str]:
    return {c.id for c in build_registry(str(tmp_path / "none.yaml")).cards()}


def test_every_skill_declares_its_artifacts(tmp_path):
    specs = manifest.build(["claude", "codex"], "/x/notionmemory")
    owners = {s.owner for s in specs}
    for skill_id in _skill_ids(tmp_path):
        assert skill_id in owners or skill_id in manifest.OWNS_NOTHING, (
            f"{skill_id}: 시스템에 심는 것이 있으면 manifest.build 에 ArtifactSpec 을 "
            f"추가하고, 없으면 manifest.OWNS_NOTHING 에 명시하세요. "
            f"teardown 은 매니페스트를 통해서만 설치물을 찾습니다.")


def test_owns_nothing_has_no_stale_entries(tmp_path):
    """사라진 스킬이 allowlist 에 남아 규칙을 조용히 무력화하지 않게 한다."""
    assert manifest.OWNS_NOTHING <= _skill_ids(tmp_path)


def test_every_artifact_owner_is_real(tmp_path):
    """owner 오타가 계약을 우회하지 못하게 한다."""
    known = _skill_ids(tmp_path) | {"_core"} | set(skill_assets.skill_names())
    for spec in manifest.build(["claude", "codex"], "/x/notionmemory"):
        assert spec.owner in known, f"{spec.id}: 알 수 없는 owner {spec.owner!r}"


def test_contract_document_exists_and_is_loaded_by_both_harnesses():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    claude, agents = root / "CLAUDE.md", root / "AGENTS.md"
    assert claude.is_file(), "CLAUDE.md 가 없으면 Claude Code 세션이 계약을 못 본다"
    assert agents.exists(), "AGENTS.md 가 없으면 Codex 세션이 계약을 못 본다"
    text = claude.read_text(encoding="utf-8")
    assert "ArtifactSpec" in text and "teardown" in text
    # 두 파일이 갈라지면 한쪽 하네스만 낡은 규칙을 읽는다
    assert agents.read_text(encoding="utf-8") == text


# ---------------------------------------------------------------------------
# 최종 리뷰 Important — codex.trust 는 ~/.codex/config.toml 에 실제로 심는
# 설치물인데 manifest.build 에 없었다. runner 와 teardown._sweep 이 각자
# 조립해서 같은 지식이 두 곳에 복제돼 있었고, 이 파일의 네 검사는 전부 owner
# 기준이라(그리고 _core 는 allowlist) 구조적으로 이것을 볼 수 없었다.
# CLAUDE.md 규칙 1 의 유일한 실질 위반이었다.
# ---------------------------------------------------------------------------

def test_codex_trust_is_registered_in_manifest():
    specs = manifest.build(["codex"], "/x/notionmemory")
    trust = [s for s in specs if s.id == "codex.trust"]
    assert trust, ("codex.trust 는 config.toml 에 심는 설치물이다 — "
                   "manifest.build 에 등록돼야 teardown 이 매니페스트를 통해 찾는다")
    assert trust[0].handler == "codex_trust"
    assert trust[0].path.name == "config.toml"


def test_codex_trust_is_absent_without_codex_target():
    specs = manifest.build(["claude"], "/x/notionmemory")
    assert not [s for s in specs if s.id == "codex.trust"]


def test_trust_spec_is_not_rebuilt_by_teardown_sweep(tmp_path, monkeypatch):
    """스윕이 자체 조립을 유지하면 매니페스트와 조용히 갈라진다."""
    from notionmemory.core.install import teardown

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    built = next(s for s in manifest.build(["codex"], "/x/notionmemory")
                 if s.id == "codex.trust")
    swept = next(s for s in teardown._sweep(["codex"]) if s.id == "codex.trust")
    assert swept == built


# ---------------------------------------------------------------------------
# Kimi Code harness — 새 provider 도 훅·스킬 미러 설치물이 매니페스트를
# 통해서만 teardown 에 잡혀야 한다(규칙 1). config.toml 훅 블록은 codex.trust
# 와 같은 파일을 공유하지 않지만 같은 마커 계약(HOOK_MARKERS)을 쓴다.
# ---------------------------------------------------------------------------

def test_kimi_artifacts_are_manifest_reachable():
    from notionmemory.core.install import manifest
    from notionmemory import providers
    assert "kimi" in providers.names()
    specs = {s.id: s for s in manifest.build(["kimi"], "notionmemory")}
    hooks = specs["kimi.hooks"]
    assert hooks.handler == "toml_hook_block"
    assert str(hooks.path).endswith("config.toml")
    assert hooks.markers == manifest.HOOK_MARKERS   # teardown finds ours by marker
    # a kimi skill mirror is registered too (teardown-reachable)
    assert any(i.startswith("kimi.skills.") for i in specs)
