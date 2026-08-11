from notionmemory import cli
from notionmemory.core.registry import SkillCard
from notionmemory.core.skill_base import RunResult


def test_broker_serve_starts_private_request_service(monkeypatch):
    from notionmemory.core import notion_broker

    seen = []
    monkeypatch.setattr(notion_broker, "serve_forever", lambda: seen.append(True))

    assert cli.main(["broker", "serve"]) == 0
    assert seen == [True]


def test_parse_kv_variants():
    got = cli._parse_kv(["--limit", "1", "--dry-run", "--doc-type", "paper", "--k=v"])
    assert got == {"limit": "1", "dry_run": "true", "doc_type": "paper", "k": "v"}


class _FakeSkill:
    id = "notes"

    def __init__(self):
        self.seen = None

    def run(self, options, log):
        self.seen = options
        log("작업 중")
        return RunResult(True, "성공 1 / 실패 0 / 스킵 0")


class _FakeRegistry:
    def __init__(self, skill, status="available", missing=None):
        self._skill = skill
        self._status = status
        self._missing = missing or []

    def get(self, sid):
        return self._skill if sid == self._skill.id else None

    def cards(self):
        return [SkillCard(self._skill.id, "Notes", ["capture"],
                          ["notion", "agent"], self._status, self._missing)]


def test_run_passes_positional_input_dir_and_options(monkeypatch, tmp_path):
    skill = _FakeSkill()
    monkeypatch.setattr(cli, "build_registry", lambda cfg: _FakeRegistry(skill))
    code = cli.main(["run", "notes", str(tmp_path), "--limit", "1", "--dry-run"])
    assert code == 0
    assert skill.seen["input_dir"] == str(tmp_path)
    assert skill.seen["limit"] == "1"
    assert skill.seen["dry_run"] == "true"


def test_run_unknown_skill_returns_2(monkeypatch, capsys):
    monkeypatch.setattr(cli, "build_registry", lambda cfg: _FakeRegistry(_FakeSkill()))
    assert cli.main(["run", "no-such-skill"]) == 2
    assert "no-such-skill" in capsys.readouterr().out


def test_run_blocked_skill_returns_2(monkeypatch):
    skill = _FakeSkill()
    monkeypatch.setattr(cli, "build_registry",
                        lambda cfg: _FakeRegistry(skill, status="blocked", missing=["notion"]))
    assert cli.main(["run", "notes", "/tmp/x"]) == 2
    assert skill.seen is None  # blocked 면 run 호출 안 함


def test_run_reports_failure_exit_1(monkeypatch, tmp_path):
    class _Failing(_FakeSkill):
        def run(self, options, log):
            return RunResult(False, "실패")
    skill = _Failing()
    monkeypatch.setattr(cli, "build_registry", lambda cfg: _FakeRegistry(skill))
    assert cli.main(["run", "notes", str(tmp_path)]) == 1


def test_run_rejects_config_after_skill_id(capsys):
    from notionmemory.cli import main
    code = main(["run", "notes", "--config", "other.yaml"])
    assert code == 2
    assert "--config" in capsys.readouterr().out


# ── memory direct mode verbs ───────────────────────────

import pytest


class _FakeStore:
    def __init__(self):
        self.calls = []
        self.recall_out = {"results": [], "fallback": False}
        self.get_out = None
        self.forget_out = True
        self.remember_supersede_error = ""

    def remember(self, content, **kw):
        self.calls.append(("remember", content, kw))
        result = {"mem_id": "mem_1_abc", "page_id": "pg_1", "concepts": kw.get("concepts", [])}
        if self.remember_supersede_error:
            result["supersede_error"] = self.remember_supersede_error
            result["supersede_target"] = "pg_old"
        return result

    def recall(self, query, **kw):
        self.calls.append(("recall", query, kw))
        return self.recall_out

    def get(self, mem_id):
        self.calls.append(("get", mem_id))
        return self.get_out

    def forget(self, mem_id):
        self.calls.append(("forget", mem_id))
        return self.forget_out


@pytest.fixture
def fake_store(monkeypatch):
    store = _FakeStore()
    monkeypatch.setattr(cli, "NotionSession", lambda **kw: object())
    monkeypatch.setattr(cli, "MemoryStore", lambda session, config: store)
    return store


def _write_cfg(tmp_path, body="skills: {}\n"):
    p = tmp_path / "config.yaml"
    p.write_text(body, encoding="utf-8")
    return str(p)


def test_remember_prints_saved_line(fake_store, tmp_path, capsys):
    code = cli.main(["remember", "내용", "--type", "fact", "--concepts", "a, b",
                     "--config", _write_cfg(tmp_path)])
    assert code == 0
    assert "Saved mem_1_abc with 2 concepts: a, b" in capsys.readouterr().out
    _, content, kw = fake_store.calls[0]
    assert content == "내용" and kw["concepts"] == ["a", "b"]
    assert kw["source"] == "manual" and kw["mem_type"] == "fact"


def test_remember_supersede_partial_failure_prints_saved_line_and_exits_1(
        fake_store, tmp_path, capsys):
    fake_store.remember_supersede_error = "429 exhausted"
    code = cli.main(["remember", "내용", "--type", "fact", "--supersedes", "mem_old",
                     "--config", _write_cfg(tmp_path)])
    out = capsys.readouterr().out
    assert "Saved mem_1_abc with 0 concepts" in out  # 페이지는 이미 생성됨 — mem_id 유실 없음
    assert "0 concepts:" not in out                  # 빈 concepts 후행 콜론 없음
    assert "pg_old" in out and "429 exhausted" in out
    assert code == 1


def test_remember_auto_blocked_when_garbage_capture_mode(fake_store, tmp_path, capsys):
    # fail-closed: "auto"가 아닌 값(오타/임의 값)은 전부 manual과 동일하게 취급한다.
    cfg = _write_cfg(tmp_path, "skills:\n  memory:\n    capture_mode: Auto\n")
    code = cli.main(["remember", "c", "--type", "fact", "--auto", "--config", cfg])
    assert code == 2
    assert "자동 저장 꺼짐 — 사용자가 요청한 경우만 저장" in capsys.readouterr().out
    assert fake_store.calls == []


def test_remember_auto_blocked_when_manual(fake_store, tmp_path, capsys):
    cfg = _write_cfg(tmp_path, "skills:\n  memory:\n    capture_mode: manual\n")
    code = cli.main(["remember", "c", "--type", "fact", "--auto", "--config", cfg])
    assert code == 2
    assert "자동 저장 꺼짐 — 사용자가 요청한 경우만 저장" in capsys.readouterr().out
    assert fake_store.calls == []  # 저장 시도 자체가 없어야 한다


def test_remember_auto_allowed_when_auto_default(fake_store, tmp_path):
    # capture_mode 미설정 = auto 기본
    code = cli.main(["remember", "c", "--type", "fact", "--auto",
                     "--config", _write_cfg(tmp_path)])
    assert code == 0 and fake_store.calls


def test_remember_default_project_from_config(fake_store, tmp_path):
    cfg = _write_cfg(tmp_path, "skills:\n  memory:\n    default_project: myproj\n")
    cli.main(["remember", "c", "--type", "fact", "--config", cfg])
    assert fake_store.calls[0][2]["project"] == "myproj"


def test_remember_explicit_project_wins(fake_store, tmp_path):
    cfg = _write_cfg(tmp_path, "skills:\n  memory:\n    default_project: myproj\n")
    cli.main(["remember", "c", "--type", "fact", "--project", "other", "--config", cfg])
    assert fake_store.calls[0][2]["project"] == "other"


def test_recall_prints_results_and_uses_config_top_n(fake_store, tmp_path, capsys):
    fake_store.recall_out = {"results": [
        {"mem_id": "m1", "type": "bug", "title": "T", "concepts": ["a"],
         "excerpt": "요약", "project": "", "last_edited": "", "page_id": "pg"}],
        "fallback": False}
    cfg = _write_cfg(tmp_path, "skills:\n  memory:\n    top_n: 3\n")
    code = cli.main(["recall", "질의", "--config", cfg])
    assert code == 0
    out = capsys.readouterr().out
    assert "[bug] m1 · T" in out and "concepts: a" in out and "요약" in out
    assert fake_store.calls[0][2]["top"] == 3  # --top 미지정 → config top_n


def test_recall_fallback_header(fake_store, tmp_path, capsys):
    fake_store.recall_out = {"results": [
        {"mem_id": "m1", "type": "fact", "title": "T", "concepts": [],
         "excerpt": "", "project": "", "last_edited": "", "page_id": "pg"}],
        "fallback": True}
    cli.main(["recall", "없는말", "--config", _write_cfg(tmp_path)])
    assert "결과 없음 — 최근 1건:" in capsys.readouterr().out


def test_recall_get_prints_full_content(fake_store, tmp_path, capsys):
    fake_store.get_out = {"mem_id": "m1", "type": "fact", "title": "T",
                          "concepts": ["a"], "excerpt": "", "project": "",
                          "last_edited": "", "page_id": "pg", "content": "본문 전체"}
    code = cli.main(["recall", "--get", "m1", "--config", _write_cfg(tmp_path)])
    assert code == 0
    out = capsys.readouterr().out
    assert "[fact] m1 · T" in out and "본문 전체" in out


def test_recall_get_missing_exit_1(fake_store, tmp_path, capsys):
    fake_store.get_out = None
    assert cli.main(["recall", "--get", "m_x", "--config", _write_cfg(tmp_path)]) == 1
    assert "메모리 없음: m_x" in capsys.readouterr().out


def test_forget_ok_and_missing(fake_store, tmp_path, capsys):
    assert cli.main(["forget", "m1", "--config", _write_cfg(tmp_path)]) == 0
    assert "Forgotten: m1" in capsys.readouterr().out
    fake_store.forget_out = False
    assert cli.main(["forget", "m_x", "--config", _write_cfg(tmp_path)]) == 1


def test_memory_verbs_report_notion_error_exit_1(monkeypatch, tmp_path, capsys):
    def boom(**kw):
        raise RuntimeError("Notion 토큰이 없습니다. 대시보드에서 Notion을 연결하세요.")
    monkeypatch.setattr(cli, "NotionSession", boom)
    code = cli.main(["recall", "q", "--config", _write_cfg(tmp_path)])
    assert code == 1
    assert "Notion 토큰이 없습니다" in capsys.readouterr().out


def test_recall_negative_top_exits_2(tmp_path, capsys):
    code = cli.main(["recall", "q", "--top", "-1", "--config", _write_cfg(tmp_path)])
    assert code == 2
    assert "--top" in capsys.readouterr().out


def test_memory_verbs_report_network_error_exit_1(monkeypatch, tmp_path, capsys):
    import requests

    def boom(**kw):
        raise requests.ConnectionError("connection refused")

    monkeypatch.setattr(cli, "NotionSession", boom)
    code = cli.main(["recall", "q", "--config", _write_cfg(tmp_path)])
    assert code == 1
    out = capsys.readouterr().out
    assert "Notion API 요청 실패" in out
    assert "Traceback" not in out


def test_default_config_is_xdg_absolute():
    from pathlib import Path

    from notionmemory.core import paths

    p = Path(cli.DEFAULT_CONFIG)
    assert p.is_absolute()
    assert p.name == "config.yaml"
    # 레포 체크아웃이 아니라 XDG config 해석기에 앵커된다
    assert p == paths.config_path()


# ── recall 출력의 포인터 노출 ──────────────────────────
# 포인터(Files/Link)는 저장돼 있었지만 recall 출력에 한 번도 나온 적이 없다.
# session_start 주입도 같은 _print_summary 를 타므로, 여기 찍히면 세션 시작 때
# 포인터가 자동으로 따라오고 에이전트가 알아서 gh/Read 로 확인할 수 있다.

def _summary(**over):
    base = {"type": "pattern", "mem_id": "mem_1", "title": "T", "concepts": [],
            "excerpt": "", "files": [], "url": ""}
    base.update(over)
    return base


def test_recall_prints_files_and_link(fake_store, tmp_path, capsys):
    fake_store.recall_out = {"fallback": False, "results": [
        _summary(files=["a.py", "b.py"], url="https://github.com/o/r/commit/abc")]}
    cli.main(["recall", "q", "--config", _write_cfg(tmp_path)])
    out = capsys.readouterr().out
    assert "a.py, b.py" in out
    assert "https://github.com/o/r/commit/abc" in out


def test_recall_omits_pointer_lines_when_absent(fake_store, tmp_path, capsys):
    """포인터가 없는 기억이 대부분이다 — 빈 줄로 세션 컨텍스트를 늘리면 안 된다."""
    fake_store.recall_out = {"fallback": False, "results": [_summary()]}
    cli.main(["recall", "q", "--config", _write_cfg(tmp_path)])
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert len(lines) == 1, lines


# 훅 stdout 첫 글자('['/'{') 규칙은 CLI 가 아니라 훅 레벨의 계약이다 — recall 출력은
# 원래 "[pattern] …" 으로 시작하고, session_start 가 앞에 헤더를 붙여 규칙을 지킨다.
# 그 가드는 tests/hooks/test_hook_cli.py 에 있고 포인터 줄이 늘어도 그대로 유효하다.


def test_get_prints_pointers_too(fake_store, tmp_path, capsys):
    fake_store.get_out = dict(_summary(files=["a.py"], url="https://x/y"), content="body")
    cli.main(["recall", "--get", "mem_1", "--config", _write_cfg(tmp_path)])
    out = capsys.readouterr().out
    assert "a.py" in out and "https://x/y" in out


def test_recall_says_so_when_the_file_list_is_truncated(fake_store, tmp_path, capsys):
    """8개까지만 찍고 끝내면 그게 전부인 것처럼 읽힌다 — 자른 사실을 말해야 한다."""
    fake_store.recall_out = {"fallback": False, "results": [
        _summary(files=[f"f{i}.py" for i in range(11)])]}
    cli.main(["recall", "q", "--config", _write_cfg(tmp_path)])
    out = capsys.readouterr().out
    assert "f7.py" in out and "f8.py" not in out
    assert "외 3개" in out


def test_status_cmd_prints_probe_and_exits_0(monkeypatch, tmp_path, capsys):
    """`_cmd_status`는 `status.probe()`(테스트로 이미 검증됨)를 그대로 사람이 읽는 줄로
    찍는 얇은 층이다 — 여기서는 그 배선(exit 0, 3개 항목 모두 출력)만 확인한다."""
    fake = {
        "notion": {"connected": True, "detail": "verified (Workspace)"},
        "memory": {"bound": True, "url": "https://www.notion.so/abc123"},
        "library": {"indexed": True, "detail": "3 page(s), last refreshed x"},
    }
    monkeypatch.setattr(cli.status_probe, "probe", lambda cfg: fake)
    code = cli.main(["status", "--config", _write_cfg(tmp_path)])
    out = capsys.readouterr().out
    assert code == 0
    assert "Notion" in out and "verified (Workspace)" in out
    assert "https://www.notion.so/abc123" in out
    assert "3 page(s)" in out
    assert "Traceback" not in out


def test_status_cmd_broken_config_exits_1_without_traceback(tmp_path, capsys):
    """config.yaml 이 파손돼 있어도(Config.load 가 예외를 던져도) 생 traceback 없이
    exit 1 — 견고성 계약(브리프: '실패해도 traceback 금지')."""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(": : [1,2\n")   # yaml.safe_load 가 ParserError 를 던지는 내용
    code = cli.main(["status", "--config", str(cfg_path)])
    out = capsys.readouterr().out
    assert code == 1
    assert "Traceback" not in out and "ParserError" not in out
