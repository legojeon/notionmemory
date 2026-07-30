"""프로필 파일 — 등록된 템플릿의 단일 소스.

`~/.local/state/notionmemory/templates/<slug>.md` = YAML 프론트매터(기계 진실) +
마크다운 본문(에이전트 해석). config.yaml 에는 아무것도 쓰지 않는다 — 파일이 곧 전부다.

**위치 제약이 곧 설치물 계약이다.** teardown 이 상태 디렉터리를 통째로 지우므로 그
아래 있는 한 매니페스트 항목이 필요 없다. 여기를 벗어나는 순간 ArtifactSpec 이 필요해진다.
"""
from __future__ import annotations

import difflib
import os
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from notionmemory.core import paths

# SessionStart 주입·목록에 보이는 health. `gone` 은 판정 즉시 파일이 삭제되므로
# 디스크에 존재할 수 없다(스펙 §8).
VISIBLE_HEALTH = ("ok", "degraded")

_SEP = "---"


@dataclass
class Profile:
    slug: str
    name: str
    page_id: str
    page_url: str = ""
    enabled: bool = True
    health: str = "ok"
    health_checked_at: str = ""
    schema_fetched_at: str = ""
    summary: str = ""
    capabilities: list = field(default_factory=list)
    databases: list = field(default_factory=list)
    pages: list = field(default_factory=list)
    prompt: str = ""     # 이 템플릿에 채울 때 에이전트가 따를 지시문(tone 포함, 스펙 §2)
    body: str = ""


def store_dir() -> Path:
    return paths.state_dir() / "templates"


def path_for(slug: str) -> Path:
    return store_dir() / f"{slug}.md"


def exists(slug: str) -> bool:
    return path_for(slug).is_file()


def save(p: Profile) -> Path:
    data = asdict(p)
    body = data.pop("body") or ""
    target = path_for(p.slug)
    target.parent.mkdir(parents=True, exist_ok=True)
    head = yaml.safe_dump(data, allow_unicode=True, sort_keys=False).rstrip("\n")
    # 원자 교체(config.py 와 같은 규율) — write_text 도중 끊기면 잘린 프로필이 남고,
    # load_all 은 파싱 실패를 삼켜 템플릿이 목록에서 **조용히 사라진다**. prompt 는
    # 사용자가 손으로 쓴 콘텐츠(강의노트 규칙 등)라 다른 사본이 없다(opus 스윕).
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(f"{_SEP}\n{head}\n{_SEP}\n{body}", encoding="utf-8")
    os.replace(tmp, target)
    return target


def _parse(text: str, slug: str) -> Profile:
    """`---\\n<yaml>\\n---\\n<body>` 만 인정한다.

    본문에 '---' 나 'key: value' 가 들어 있어도 오해하지 않도록 **앞쪽 두 구분자만**
    쓰고 나머지는 전부 본문으로 넘긴다.
    """
    if not text.startswith(_SEP + "\n"):
        raise ValueError(f"프로필 형식이 아닙니다: {slug}")
    rest = text[len(_SEP) + 1:]
    end = rest.find("\n" + _SEP + "\n")
    if end < 0:
        raise ValueError(f"프로필 프론트매터가 닫히지 않았습니다: {slug}")
    head = yaml.safe_load(rest[:end]) or {}
    if not isinstance(head, dict):
        raise ValueError(f"프로필 프론트매터가 매핑이 아닙니다: {slug}")
    body = rest[end + len(_SEP) + 2:]
    known = {f for f in Profile.__dataclass_fields__ if f != "body"}
    return Profile(body=body, **{k: v for k, v in head.items() if k in known})


def load(slug: str) -> Profile:
    target = path_for(slug)
    if not target.is_file():
        available = ", ".join(list_slugs()) or "(없음)"
        raise ValueError(f"등록되지 않은 템플릿입니다: {slug} — 등록된 목록: {available}")
    return _parse(target.read_text(encoding="utf-8"), slug)


def list_slugs() -> list[str]:
    root = store_dir()
    if not root.is_dir():
        return []
    return sorted(p.stem for p in root.glob("*.md"))


def load_all() -> list[Profile]:
    """깨진 파일 하나가 전체 목록을 죽이지 않는다 — 세션 훅이 이걸 부른다."""
    out = []
    for slug in list_slugs():
        try:
            out.append(load(slug))
        except (ValueError, OSError, yaml.YAMLError):
            continue
    return out


def delete(slug: str) -> bool:
    target = path_for(slug)
    if not target.is_file():
        return False
    target.unlink()
    return True


def find_db(p: Profile, key: str) -> dict:
    for db in p.databases:
        if db.get("key") == key:
            return db
    keys = ", ".join(db.get("key", "?") for db in p.databases) or "(없음)"
    raise ValueError(f"'{p.slug}'에 그런 데이터베이스가 없습니다: {key} — 사용 가능: {keys}")


def find_prop(db: dict, name: str) -> dict:
    props = db.get("properties") or []
    for prop in props:
        if prop.get("name") == name:
            return prop
    # 공백 무시 폴백 — Notion 스키마엔 `마감일 ` 처럼 끝공백 붙은 이름이 흔한데(공유
    # 템플릿 복제 등) CLI 파싱(parse_set/--fields/--where)은 이름을 strip 하므로 정확
    # 일치로는 영원히 도달 불가다(실사용 버그). strip 비교로 **유일**할 때만 그 속성을
    # 돌려준다 — 둘 이상이면 추측하지 않고 아래 기존 오류로 떨어진다. 호출부는 사용자가
    # 친 이름이 아니라 여기서 받은 캐노니컬 `prop["name"]` 을 페이로드 키로 써야 한다.
    # NFC 정규화도 함께 접는다 — macOS 파일명/일부 입력기는 한글을 NFD 로 내보내
    # `마감일`(NFD) vs `마감일`(NFC) 이 **화면엔 똑같이 보이면서** 불일치한다(오류
    # 메시지가 자기모순처럼 읽히는, 공백과 같은 부류의 함정). slugify 는 이미 NFC 로
    # 정규화한다 — 같은 규율을 조회 이음매에도 적용한다.
    def _norm(s: str) -> str:
        return unicodedata.normalize("NFC", (s or "").strip())
    stripped = [p for p in props if _norm(p.get("name")) == _norm(name)]
    if len(stripped) == 1:
        return stripped[0]
    names = [prop.get("name", "") for prop in props]
    close = difflib.get_close_matches(name, names, n=1, cutoff=0.6)
    hint = f" 혹시 `{close[0]}`인가요?" if close else f" 사용 가능: {', '.join(names)}"
    raise ValueError(
        f"'{db.get('key')}'에 그런 속성이 없습니다: {name}.{hint} "
        f"(Notion 에서 이름을 바꿨다면 `notionmemory templates refresh <slug>` 하세요)")


def injection_line(profiles: list[Profile]) -> str:
    """SessionStart 주입 한 줄. 보여줄 게 없으면 빈 문자열 — 노이즈를 넣지 않는다.

    접두사를 고정한다: 첫 글자가 '[' 나 '{' 이면 Claude Code 2.1.215+ 가 stdout 을
    JSON 으로 스니핑하다 훅을 실패 처리한다(이 리포가 이미 밟은 지뢰).
    """
    shown = [p for p in profiles if p.enabled and p.health in VISIBLE_HEALTH]
    if not shown:
        return ""
    items = ", ".join(f"{p.slug}({p.summary})" if p.summary else p.slug for p in shown)
    return f"notionmemory templates: {items}"
