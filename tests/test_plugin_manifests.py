import json
import tomllib
from pathlib import Path

from notionmemory.core import skill_assets

ROOT = Path(__file__).resolve().parents[1]
CLAUDE_PLUGIN = ".claude-plugin/plugin.json"
CLAUDE_MKT = ".claude-plugin/marketplace.json"
CODEX_MKT = ".agents/plugins/marketplace.json"
CODEX_PLUGIN = "plugins/notionmemory/.codex-plugin/plugin.json"
AGENT_SKILLS = ROOT / "notionmemory" / "agent_skills"
PLUGIN_SKILLS = ROOT / "plugins" / "notionmemory" / "skills"


def _json(rel):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def _pyproject_version():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["version"]


def test_all_manifests_are_valid_json():
    for rel in (CLAUDE_PLUGIN, CLAUDE_MKT, CODEX_MKT, CODEX_PLUGIN):
        _json(rel)


def test_plugin_name_and_version_track_pyproject():
    v = _pyproject_version()
    for rel in (CLAUDE_PLUGIN, CODEX_PLUGIN):
        m = _json(rel)
        assert m["name"] == "notionmemory", rel
        assert m["version"] == v, f"{rel}: version 이 pyproject({v}) 와 다르다"

    mkt = _json(CLAUDE_MKT)
    entry = next(p for p in mkt["plugins"] if p["name"] == "notionmemory")
    assert entry["version"] == v, "claude marketplace.json plugin version must track pyproject"


def test_claude_skills_path_is_the_single_source():
    m = _json(CLAUDE_PLUGIN)
    p = (ROOT / m["skills"]).resolve()
    assert p == AGENT_SKILLS.resolve(), "Claude skills 필드가 agent_skills 를 가리켜야 한다"
    names = {d.name for d in p.iterdir() if (d / "SKILL.md").is_file()}
    assert names == set(skill_assets.skill_names())


def test_codex_plugin_skills_are_real_files_not_symlink():
    # codex plugin add 가 심링크를 안 따르므로 실디렉터리·실파일이어야 스킬이 전달된다
    assert PLUGIN_SKILLS.is_dir() and not PLUGIN_SKILLS.is_symlink()
    names = {d.name for d in PLUGIN_SKILLS.iterdir() if (d / "SKILL.md").is_file()}
    assert names == set(skill_assets.skill_names())
    for name in skill_assets.skill_names():
        assert not (PLUGIN_SKILLS / name / "SKILL.md").is_symlink(), \
            f"{name}/SKILL.md must be a real file (codex plugin add skips symlinks)"


def test_codex_plugin_skills_are_byte_identical_to_agent_skills():
    for name in skill_assets.skill_names():
        src = (AGENT_SKILLS / name / "SKILL.md").read_bytes()
        dup = (PLUGIN_SKILLS / name / "SKILL.md").read_bytes()
        assert src == dup, (f"{name}: plugins/notionmemory/skills 사본이 agent_skills 와 다르다 "
                            f"— scripts/sync_plugin_skills.sh 로 갱신하세요")


def test_claude_hooks_match_the_cli_hook_contract():
    from notionmemory.core.install import manifest
    m = _json(CLAUDE_PLUGIN)
    # 같은 훅을 두 경로가 기술한다 — 이벤트 집합이 CLI install 과 드리프트하면 안 된다
    cli_events = set(manifest.HOOK_EVENTS("/x/notionmemory", "claude").keys())
    assert set(m["hooks"]) == cli_events == {
        "SessionStart", "PreCompact", "Stop", "UserPromptSubmit", "SessionEnd"}
    cmds = [h["command"] for grp in m["hooks"].values()
            for entry in grp for h in entry["hooks"]]
    assert any("notionmemory hook session-start" in c for c in cmds)
    assert any("notionmemory hook save-reminder" in c for c in cmds)
    assert any("notionmemory hook session-stop" in c for c in cmds)
    assert any("notionmemory hook user-prompt" in c for c in cmds)
    assert any("notionmemory hook session-end" in c for c in cmds)


def test_codex_marketplace_points_at_the_plugin_dir():
    m = _json(CODEX_MKT)
    entry = next(p for p in m["plugins"] if p["name"] == "notionmemory")
    assert entry["source"]["path"] == "./plugins/notionmemory"
