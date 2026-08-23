"""`notionmemory --version` — 서브커맨드 required 여도 먼저 출력하고 exit 0."""
import pytest

from notionmemory import cli
from notionmemory.core import version


def test_version_flag_prints_and_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "notionmemory" in out
    assert version.package_version() in out
