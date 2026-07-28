from __future__ import annotations
import os
import tempfile
import yaml


class Config:
    def __init__(self, data: dict, path: str = ""):
        self.data = data if isinstance(data, dict) else {}
        self.path = path

    @classmethod
    def load(cls, path: str) -> "Config":
        if not os.path.exists(path):
            return cls({}, path)
        with open(path, "r", encoding="utf-8") as f:
            return cls(yaml.safe_load(f) or {}, path)

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def integration(self, id: str) -> dict:
        return (self.data.get("integrations") or {}).get(id) or {}

    def skill_options(self, skill_id: str) -> dict:
        return (self.data.get("skills") or {}).get(skill_id) or {}


def _load_raw(config_path: str) -> dict:
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def _write_raw(config_path: str, raw: dict) -> None:
    """tmp 파일에 전부 쓴 뒤 os.replace 로 원자 교체 — dump 도중 실패해도 원본 보존.
    safe_dump 재직렬화라 사용자가 config.yaml 에 직접 단 주석은 보존되지 않는다
    (설명 주석은 config.example.yaml 이 담당)."""
    directory = os.path.dirname(config_path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".config-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.safe_dump(raw, f, allow_unicode=True, sort_keys=False)
        os.replace(tmp_path, config_path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def save_language(config_path: str, lang: str) -> None:
    """최상위 language 키 기록. 다른 키 보존(원자 교체)."""
    raw = _load_raw(config_path)
    raw["language"] = lang
    _write_raw(config_path, raw)


def save_skill_options(config_path: str, skill_id: str, options: dict) -> dict:
    """skills.<skill_id> 섹션에 옵션을 병합 저장하고 병합된 섹션을 반환.
    토큰 등 민감값은 호출부가 걸러야 한다."""
    raw = _load_raw(config_path)
    skills = raw.get("skills") or {}
    existing = skills.get(skill_id) or {}
    existing.update(options)
    skills[skill_id] = existing
    raw["skills"] = skills
    _write_raw(config_path, raw)
    return existing


class SkillMeta:
    """notion_db ensure()의 get_meta/set_meta 계약 — config `skills.<id>` 섹션 구현."""

    def __init__(self, config: Config, skill_id: str):
        self.config = config
        self.skill_id = skill_id

    def get_meta(self, key: str) -> str:
        return str(self.config.skill_options(self.skill_id).get(key) or "")

    def set_meta(self, key: str, value: str) -> None:
        if self.config.path:
            # 디스크 병합 결과로 in-memory 섹션을 교체 — 디스크가 단일 소스.
            merged = save_skill_options(self.config.path, self.skill_id, {key: value})
            self.config.data.setdefault("skills", {})[self.skill_id] = dict(merged)
        else:
            self.config.data.setdefault("skills", {}).setdefault(self.skill_id, {})[key] = value
