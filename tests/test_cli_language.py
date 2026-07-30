"""`notionmemory language [en|ko]` — 온보딩 언어 스텝이 부르는 비대화형 설정 명령.
인자 있으면 config language 저장, 없으면 현재값 출력."""
from notionmemory.cli import main
from notionmemory.core import config as cfg
from notionmemory.core.config import Config


def test_language_set_ko_writes_config(tmp_path):
    p = str(tmp_path / "config.yaml")
    assert main(["language", "ko", "--config", p]) == 0
    assert Config.load(p).get("language") == "ko"


def test_language_set_en_writes_config(tmp_path):
    p = str(tmp_path / "config.yaml")
    cfg.save_language(p, "ko")            # start non-default
    assert main(["language", "en", "--config", p]) == 0
    assert Config.load(p).get("language") == "en"


def test_language_set_preserves_other_keys(tmp_path):
    p = str(tmp_path / "config.yaml")
    cfg.save_skill_options(p, "memory", {"database_id": "abc"})
    assert main(["language", "ko", "--config", p]) == 0
    loaded = Config.load(p)
    assert loaded.get("language") == "ko"
    assert loaded.skill_options("memory").get("database_id") == "abc"


def test_language_no_arg_prints_current(tmp_path, capsys):
    p = str(tmp_path / "config.yaml")
    cfg.save_language(p, "ko")
    assert main(["language", "--config", p]) == 0
    assert "ko" in capsys.readouterr().out


def test_language_rejects_invalid_choice(tmp_path):
    import pytest
    p = str(tmp_path / "config.yaml")
    with pytest.raises(SystemExit):        # argparse choices guard
        main(["language", "fr", "--config", p])


def test_text_or_file_missing_file_is_valueerror_not_traceback(tmp_path):
    """--*-file 의 주 사용자는 임시 파일을 쓰는 에이전트 — 지워진 경로는 예상된
    실패라 exit 2(ValueError)여야지 FileNotFoundError traceback 이면 안 된다."""
    import pytest
    from notionmemory.cli import _text_or_file
    with pytest.raises(ValueError):
        _text_or_file(None, str(tmp_path / "gone.md"))
    assert _text_or_file("inline", None) == "inline"
