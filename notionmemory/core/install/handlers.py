"""아티팩트 핸들러 — 각각 install / remove / detect 만 갖는다.

JsonHookBlock 은 Claude(settings.json)와 Codex(hooks.json) 양쪽에 쓰인다. 두 파일의
훅 스키마가 동일함이 2026-07-21 실측으로 확인됐다(스펙 §1). 경로만 다르다 — 그래서
기능 동등성이 문서상 약속이 아니라 공유 클래스로 보장된다.
"""
from __future__ import annotations

import json
import os
import platform
import plistlib
import re
import shutil
import subprocess
from pathlib import Path

from notionmemory.core.install.spec import ArtifactSpec

# 스킬 디렉터리 소유권 판정용 사이드카. 이름만으로 판정하면 사용자가 직접 만든
# ~/.claude/skills/memory 를 teardown 이 지워버린다.
OWNED_MARKER_FILE = ".notionmemory-owned"

# `[hooks.state."<key>"]` 헤더에서 key 를 뽑아낸다. key 안의 `"` 는 `\"` 로 이스케이프돼
# 있으므로(CodexTrust._toml_escape) 바깥쪽 두 따옴표만 진짜 경계다 — greedy `.*` 가
# 마지막 `"]` 까지 잡으면 내부의 이스케이프된 `\"` 는 자연히 포함된다.
_STATE_HEADER_RE = re.compile(r'^\[hooks\.state\."(.*)"\]$')
# C0 제어문자 + DEL. TOML 기본 문자열로 안전히 못 담고, 특히 개행은 우리 줄 단위
# 파서(_blocks)를 깨뜨린다. hooks/list 는 외부 프로세스 산출물이라 신뢰하지 않는다.
_CONTROL_CHARS = frozenset(chr(c) for c in range(0x20)) | {chr(0x7f)}

# JsonHookBlock 훅 소유권 판정용 구조적 패턴. `command in blob` 부분일치는
# `/Users/bob/backups/old_memory_hooks_project/run.sh` 처럼 `memory_hooks`가
# 남의 경로 조각으로 우연히 들어간 command 를 우리 것으로 오판해 지워버린다
# (리뷰 Important — CodexTrust 에서 이미 고친 것과 같은 버그 계열). 현재
# 마커는 우리 CLI 의 `hook` 서브커맨드 호출만, 레거시 마커는 실제 구 스크립트
# 경로(`memory_hooks/session_start.py`, `memory_hooks/save_reminder.py`)만
# 인정한다 — `memory_hooks`라는 디렉터리 이름 자체는 소유권 근거가 아니다.
# Codex 타깃 명령에는 `--harness codex` 가 붙는다(Stop/PreCompact 의 stdout 형태가
# 하네스별로 다름이 실기로 확인됨 — manifest.HOOK_EVENTS 참조) — 그 꼬리를 허용하지
# 않으면 우리가 방금 심은 codex.hooks 자체를 우리 것으로 인식하지 못해 teardown 이
# 지우지 못하고 재설치도 중복 병합해버린다.
_CLI_HOOK_COMMAND_RE = re.compile(
    r'(?:^|[\\/])notionmemory(?:\.exe)? hook \S+(?: --harness (?:claude|codex|kimi))?$')
_LEGACY_HOOK_SCRIPT_RE = re.compile(
    r'(?:^|[\\/])memory_hooks[\\/](?:session_start|save_reminder)\.py(?:$|\s)')


def hook_command_is_ours(command: object, markers: tuple[str, ...]) -> bool:
    """훅 command 하나가 우리 것인가 — 구조적 판정, 부분문자열 일치가 아니다.

    이 판정은 **한 군데에만** 있어야 한다. 같은 정규식을 복사해 두 곳에서 쓰면
    한쪽만 고쳐지고 다른 쪽이 낡은 채로 남는다 — 실제로 그렇게 갈라져서
    `codex.our_hooks` 가 부분일치를 계속 쓰고 있었고, 그쪽 결과는 "남의 훅에
    Codex 신뢰(trusted_hash)를 부여"였다. 그래서 함수로 공유한다.

    마커 목록에 해당 종류가 없으면(예: 다른 용도로 markers 를 좁혀 부른 경우)
    그 종류는 검사하지 않는다.
    """
    if not isinstance(command, str):
        return False
    if "notionmemory hook" in markers and _CLI_HOOK_COMMAND_RE.search(command):
        return True
    if "memory_hooks" in markers and _LEGACY_HOOK_SCRIPT_RE.search(command):
        return True
    return False


class OwnershipConflict(Exception):
    """설치 대상이 이미 있는데 우리 것이라는 근거가 없다 — 사람이 판단할 일이다."""

    def __init__(self, path: Path):
        self.path = Path(path)
        super().__init__(str(path))


class SkillMirror:
    """패키지의 SKILL.md 디렉터리를 사용자 레벨 스킬 루트에 미러."""

    def install(self, spec: ArtifactSpec) -> bool:
        src = Path(spec.payload["source"])
        dest = Path(spec.path)
        # 소유권 판정 지점. remove 는 사이드카가 없으면 거부하는데 install 만
        # 무조건 rmtree 라서, 사용자가 직접 만든 ~/.claude/skills/memory 를 첫
        # 설치가 통째로 날렸다(스펙 §5.3 이 memory/calendar/notes 는 사용자가
        # 만들 법한 이름이라고 논증한 그 사고).
        #
        # 사이드카가 없는 동명 디렉터리에는 두 출처가 겹친다: ① 사용자가 만든 것
        # ② 마커를 안 남기던 구 scripts/sync_skills.py 가 심은 것. ②는 canonical
        # 디렉터리를 copytree 로 그대로 복사했을 뿐 식별자를 하나도 안 남겼으므로
        # (main 의 scripts/sync_skills.py 확인) 파일 시스템에는 둘을 가르는 근거가
        # 없다. "SKILL.md 가 notionmemory 를 언급하면 우리 것" 같은 휴리스틱은
        # 사용자가 만든 래퍼 스킬을 지우므로 채택하지 않는다 — 틀렸을 때 잃는 것이
        # 사용자 데이터인 쪽으로는 기울지 않는다. 손대지 않고 사람에게 넘긴다.
        #
        # 심링크는 사이드카 여부와 무관하게 항상 거부한다 — detect() 는 링크를
        # 따라가므로 "우리 것"으로 보일 수 있지만, rmtree 는 심링크를 못 지우고
        # 따라가서 지우면 링크가 가리키던 남의 디렉터리를 파괴한다.
        if dest.is_symlink():
            raise OwnershipConflict(dest)
        if dest.exists():
            if not self.detect(spec):
                raise OwnershipConflict(dest)
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dest)
        (dest / OWNED_MARKER_FILE).write_text("notionmemory\n", encoding="utf-8")
        return True

    def detect(self, spec: ArtifactSpec) -> bool:
        return (Path(spec.path) / OWNED_MARKER_FILE).is_file()

    def remove(self, spec: ArtifactSpec) -> bool:
        dest = Path(spec.path)
        if not self.detect(spec):
            return False          # 우리 것이 아니다 — 손대지 않는다
        shutil.rmtree(dest)
        return True


class BundleMirror:
    """Copy a packaged bundle dir into a harness's extension dir. Same ownership /
    teardown discipline as SkillMirror (owner sidecar, no symlink follow), plus a
    generated notionmemory.json carrying the install-time-resolved CLI path so the
    shim can invoke the right binary without trusting the harness runtime's PATH.
    """

    def install(self, spec: ArtifactSpec) -> bool:
        src = Path(spec.payload["source"])
        dest = Path(spec.path)
        if dest.is_symlink():
            raise OwnershipConflict(dest)
        if dest.exists():
            if not self.detect(spec):
                raise OwnershipConflict(dest)
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dest)
        (dest / OWNED_MARKER_FILE).write_text("notionmemory\n", encoding="utf-8")
        cli = spec.payload.get("cli_path")
        if cli:
            (dest / "notionmemory.json").write_text(
                json.dumps({"cli": cli}) + "\n", encoding="utf-8")
        return True

    def detect(self, spec: ArtifactSpec) -> bool:
        return (Path(spec.path) / OWNED_MARKER_FILE).is_file()

    def remove(self, spec: ArtifactSpec) -> bool:
        dest = Path(spec.path)
        if not self.detect(spec):
            return False
        shutil.rmtree(dest)
        return True


class JsonHookBlock:
    """세션 훅 블록을 JSON 설정 파일에 멱등 병합/제거. 기존 사용자 항목은 보존."""

    def _load(self, path: Path) -> dict:
        try:
            return json.loads(path.read_text(encoding="utf-8") or "{}")
        except (OSError, ValueError):
            return {}

    def _is_ours(self, entry: dict, markers: tuple[str, ...]) -> bool:
        """구조적 판정 — entry 를 통째로 JSON 직렬화해 부분일치하지 않는다.

        `command` 필드 하나만 놓고, 우리가 실제로 쓰는 두 형태에만 맞는지 본다
        (판정 본체는 모듈 수준 `hook_command_is_ours` — Codex 신뢰 등록과 공유).
        """
        if not isinstance(entry, dict):
            return False
        return any(hook_command_is_ours(h.get("command"), markers)
                   for h in (entry.get("hooks") or []) if isinstance(h, dict))

    def _write(self, path: Path, raw: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")

    def install(self, spec: ArtifactSpec) -> bool:
        path = Path(spec.path)
        raw = self._load(path)
        hooks = raw.setdefault("hooks", {})
        changed = False
        events = spec.payload["events"]
        for event, entries in events.items():
            kept = [e for e in hooks.get(event, []) if not self._is_ours(e, spec.markers)]
            merged = kept + list(entries)
            if hooks.get(event) != merged:
                hooks[event] = merged
                changed = True
        # 매니페스트에서 빠진 이벤트에 남아 있는 우리 항목을 걷는다. 이게 없으면
        # 구버전이 심은 Stop 항목이 업그레이드 후에도 계속 발화한다 — 매니페스트를
        # 유일한 진실로 삼는다는 계약(CLAUDE.md 1항)이 설치 경로에서만 깨진다.
        for event in [e for e in hooks if e not in events]:
            kept = [e for e in hooks[event] if not self._is_ours(e, spec.markers)]
            if kept == hooks[event]:
                continue
            changed = True
            if kept:
                hooks[event] = kept
            else:
                del hooks[event]
        if changed:
            self._write(path, raw)
        return changed

    def detect(self, spec: ArtifactSpec) -> bool:
        hooks = self._load(Path(spec.path)).get("hooks") or {}
        return any(self._is_ours(e, spec.markers)
                   for entries in hooks.values() for e in entries)

    def remove(self, spec: ArtifactSpec) -> bool:
        path = Path(spec.path)
        raw = self._load(path)
        hooks = raw.get("hooks") or {}
        changed = False
        for event in list(hooks):
            kept = [e for e in hooks[event] if not self._is_ours(e, spec.markers)]
            if kept != hooks[event]:
                changed = True
                if kept:
                    hooks[event] = kept
                else:
                    del hooks[event]
        if changed:
            if self._should_unlink(spec, raw):
                path.unlink(missing_ok=True)
            else:
                self._write(path, raw)
        return changed

    def _should_unlink(self, spec: ArtifactSpec, raw: dict) -> bool:
        """우리 블록을 뺀 결과가 내용 없는 껍데기이고, 그 파일이 훅 전용인가.

        판정 근거는 spec.target 하나다 — payload 플래그로 하면 teardown 이 만드는
        명세(영수증·스윕 모두 payload={})에서 조용히 꺼져 실제 제거 경로에서만
        동작하지 않는다. 실제로 그렇게 짰다가 테스트에 걸렸다.

        껍데기 판정은 보수적이다: 남은 이벤트도, 우리가 모르는 최상위 키도 없을 때만
        참이다. 사용자가 자기 훅이나 다른 설정을 같은 파일에 넣어뒀으면 파일은 산다.
        """
        from notionmemory.core.install import manifest
        if not manifest.hook_file_is_dedicated(spec.target):
            return False
        return not (raw.get("hooks") or {}) and set(raw) <= {"hooks"}


class OpencodeConfigEntry:
    """단일 문자열 항목을 JSON 설정 파일의 최상위 `plugin` 배열에 멱등 병합/제거.

    OpenCode 는 플러그인 디렉터리를 자동 발견하지 않고 `<config>/opencode.json` 의
    `plugin` 배열에 등록된 항목만 로드한다(2026-08-27 실측). JsonHookBlock 과 같은
    비파괴 원칙을 따른다 — 소유권 마커는 우리 항목 문자열 자체이고, 파일의 다른 키·
    다른 항목은 손대지 않는다.
    """

    def _load(self, path: Path) -> dict:
        try:
            return json.loads(path.read_text(encoding="utf-8") or "{}")
        except (OSError, ValueError):
            return {}

    def install(self, spec: ArtifactSpec) -> bool:
        entry = spec.payload["entry"]
        path = Path(spec.path)
        raw = self._load(path)
        if not isinstance(raw, dict):
            return False
        plugin = raw.setdefault("plugin", [])
        if not isinstance(plugin, list):
            return False           # 사용자 데이터 형태가 다르다 — 손대지 않는다
        # 마커에 해당하는 옛 항목(rename 전 값 포함)을 먼저 걷어내고 현재 entry 를
        # 새로 붙인다 — JsonHookBlock 과 같은 rename-safety(CLAUDE.md 4항).
        stripped = [e for e in plugin if e not in spec.markers]
        new_plugin = stripped + [entry]
        if new_plugin == plugin:
            return False
        raw["plugin"] = new_plugin
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        return True

    def detect(self, spec: ArtifactSpec) -> bool:
        raw = self._load(Path(spec.path))
        plugin = raw.get("plugin") if isinstance(raw, dict) else None
        if not isinstance(plugin, list):
            return False
        return any(m in plugin for m in spec.markers)

    def remove(self, spec: ArtifactSpec) -> bool:
        path = Path(spec.path)
        raw = self._load(path)
        if not isinstance(raw, dict):
            return False
        plugin = raw.get("plugin")
        if not isinstance(plugin, list):
            return False
        kept = [e for e in plugin if e not in spec.markers]
        if kept == plugin:
            return False
        raw["plugin"] = kept
        path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        return True


class GitHooks:
    """레포별 post-commit 훅.

    설치는 `notionmemory git install` 과 세션 훅이 담당하므로 install() 은 no-op 이다.
    그래도 매니페스트에 항목으로 존재해야 한다 — 설치물을 소유하는 스킬은 그 사실을
    매니페스트에 등록하는 것이 완료 조건이고(Task 12의 계약 테스트가 강제한다),
    teardown 은 매니페스트를 통해서만 이 훅을 찾을 수 있다.

    spec.path 는 리포 레지스트리가 든 config 경로다.
    """

    def _repos(self, spec: ArtifactSpec) -> list[str]:
        from notionmemory.core.config import Config
        return list(Config.load(str(spec.path)).skill_options("git").get("repos") or [])

    def install(self, spec: ArtifactSpec) -> bool:
        return False

    def detect(self, spec: ArtifactSpec) -> bool:
        from notionmemory.skills.git import hooks as gc_hooks
        return any(gc_hooks.is_installed(Path(r)) for r in self._repos(spec))

    def remove(self, spec: ArtifactSpec) -> bool:
        from notionmemory.skills.git import hooks as gc_hooks
        changed = False
        for r in self._repos(spec):
            # config_path 를 넘기지 않는다 — teardown 은 리포를 exclude 에 넣는
            # 사용자 의사표시가 아니다. gc_hooks.ALL_MARKERS 가 구 마커
            # (git-capture)까지 인식하므로 레거시 잔재도 함께 걷힌다(606ed33).
            if gc_hooks.uninstall(Path(r)):
                changed = True
        return changed


class CodexTrust:
    """~/.codex/config.toml 의 [hooks.state."<key>"] trusted_hash 항목.

    Codex 는 trusted_hash 가 없는 훅을 로그 한 줄 없이 조용히 건너뛴다. TOML 라이브러리
    의존을 늘리지 않기 위해 우리 블록만 텍스트로 다룬다 — 사용자의 다른 설정은 건드리지
    않고, 우리 hooks.json 경로가 키에 든 블록만 인식·교체·제거한다.
    """

    def _blocks(self, text: str) -> list[tuple[int, int, str]]:
        """(시작줄, 끝줄(배타), 헤더) 목록. 헤더는 `[hooks.state."..."]` 줄.

        블록은 다음에 오는 `[`로 시작하는 줄에서 끝난다고 가정한다 — 우리가 쓰는
        값(trusted_hash 스칼라 하나)은 여러 줄에 걸치지 않으므로 이 가정은 우리
        쓰기 경로에서는 항상 성립한다. 사용자가 이 블록 안에 멀티라인 배열을 손으로
        넣는 경우(각 원소가 `[`로 시작하는 줄일 수 있음)는 여기서 다루지 않는다 —
        우리가 만들지 않는 형태이고, 발생 확률과 파서 복잡도를 맞바꿀 가치가 없다.
        """
        lines = text.splitlines()
        found = []
        for i, line in enumerate(lines):
            if not line.strip().startswith('[hooks.state."'):
                continue
            j = i + 1
            while j < len(lines) and not lines[j].strip().startswith("["):
                j += 1
            found.append((i, j, line.strip()))
        return found

    def _toml_escape(self, s: str) -> str:
        """TOML 기본 문자열 규칙: 백슬래시 먼저, 그 다음 큰따옴표."""
        return s.replace("\\", "\\\\").replace('"', '\\"')

    def _is_safe(self, s: str) -> bool:
        return not any(ch in _CONTROL_CHARS for ch in s)

    def split_safe(self, entries: list[dict]) -> tuple[list[dict], list[dict]]:
        """key·currentHash 에 제어문자/개행이 든 항목을 분리한다.

        그런 값은 TOML 기본 문자열로 안전히 표현할 수 없다(개행은 우리 줄 단위
        파서도 깨뜨린다) — 쓰지 않고 걸러낸다.
        """
        safe, unsafe = [], []
        for e in entries:
            key = str(e.get("key", ""))
            digest = str(e.get("currentHash", ""))
            if self._is_safe(key) and self._is_safe(digest):
                safe.append(e)
            else:
                unsafe.append(e)
        return safe, unsafe

    def _header_key(self, header: str) -> str | None:
        m = _STATE_HEADER_RE.match(header)
        return m.group(1) if m else None

    def _ours(self, header: str, markers: tuple[str, ...]) -> bool:
        """구조적 비교 — 부분문자열 일치가 아니다.

        `hooks.json` 경로를 부분문자열로 비교하면 `hooks.json.bak` 처럼 우리 경로가
        접두사인 남의 키까지 우리 것으로 오판해 지워버린다(리뷰 Critical). 우리 키는
        항상 `<marker>:<event>:<group>:<handler>` 형태이므로 정확히 marker 이거나
        `marker + ":"` 로 시작하는 경우만 우리 것으로 본다. 헤더에 쓰인 key 는
        _toml_escape 를 거친 상태이므로 marker 도 같은 방식으로 이스케이프한 뒤
        비교한다 — 그래야 쓰기(_render)와 판정(_ours)이 일치한다.
        """
        key = self._header_key(header)
        if key is None:
            return False
        for marker in markers:
            esc = self._toml_escape(marker)
            if key == esc or key.startswith(esc + ":"):
                return True
        return False

    def _line_ending(self, text: str) -> str:
        """파일의 우세한 줄바꿈을 그대로 재사용한다 — CRLF 파일을 LF 로 바꿔치기
        하지 않는다."""
        crlf = text.count("\r\n")
        lf_only = text.count("\n") - crlf
        return "\r\n" if crlf > lf_only else "\n"

    def _strip(self, text: str, markers: tuple[str, ...]) -> tuple[str, bool]:
        eol = self._line_ending(text)
        lines = text.splitlines()
        drop: set[int] = set()
        for start, end, header in self._blocks(text):
            if self._ours(header, markers):
                drop.update(range(start, end))
        if not drop:
            return text, False
        kept = [ln for i, ln in enumerate(lines) if i not in drop]
        return eol.join(kept).rstrip("\r\n") + eol, True

    def _render(self, entries: list[dict], eol: str = "\n") -> str:
        out = []
        for e in entries:
            key = self._toml_escape(str(e["key"]))
            digest = self._toml_escape(str(e["currentHash"]))
            out.append(f'[hooks.state."{key}"]')
            out.append(f'trusted_hash = "{digest}"')
            out.append("")
        return eol.join(out)

    def _read(self, path: Path) -> str:
        # newline="" 로 유니버설 개행 변환을 끈다 — 그게 켜져 있으면 파일의 실제
        # \r\n 이 읽는 순간 \n 으로 바뀌어 _line_ending 이 CRLF 파일을 LF 로
        # 오판한다(리뷰 Important #4).
        return path.read_text(encoding="utf-8", newline="") if path.exists() else ""

    def _write(self, path: Path, text: str) -> None:
        # 같은 이유로 newline="" — 안 그러면 우리가 넣은 \r\n 이 쓰는 순간
        # os.linesep 기준으로 다시 번역돼 이중으로 바뀔 수 있다.
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="")

    def install(self, spec: ArtifactSpec) -> bool:
        path = Path(spec.path)
        entries = spec.payload.get("entries") or []
        safe, _unsafe = self.split_safe(entries)
        if not safe:
            return False
        text = self._read(path)
        eol = self._line_ending(text)
        stripped, _ = self._strip(text, spec.markers)
        new = stripped.rstrip("\r\n") + eol + eol + self._render(safe, eol)
        new = new.lstrip("\r\n")
        if path.exists() and self._read(path) == new:
            return False
        self._write(path, new)
        return True

    def detect(self, spec: ArtifactSpec) -> bool:
        path = Path(spec.path)
        if not path.exists():
            return False
        text = self._read(path)
        return any(self._ours(h, spec.markers) for _, _, h in self._blocks(text))

    def remove(self, spec: ArtifactSpec) -> bool:
        path = Path(spec.path)
        if not path.exists():
            return False
        text = self._read(path)
        new, changed = self._strip(text, spec.markers)
        if changed:
            self._write(path, new)
        return changed


class TomlHookBlock:
    """Kimi config.toml [[hooks]] block — idempotent, non-destructive, marker-owned.

    Line-based like CodexTrust (no TOML library): our [[hooks]] tables are those whose
    `command` is one of ours (hook_command_is_ours). We strip ours and append fresh,
    preserving all other TOML content (user keys and user-authored [[hooks]]).
    """

    def _read(self, path: Path) -> str:
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def _blocks(self, text: str) -> list[tuple[int, int, str]]:
        """(start, end-exclusive, command-value) for each [[hooks]] table."""
        lines = text.splitlines()
        out = []
        for i, line in enumerate(lines):
            if line.strip() != "[[hooks]]":
                continue
            j, command = i + 1, ""
            while j < len(lines) and not lines[j].strip().startswith("["):
                m = re.match(r'\s*command\s*=\s*"(.*)"\s*$', lines[j])
                if m:
                    command = m.group(1)
                j += 1
            out.append((i, j, command))
        return out

    def _ours_blocks(self, text: str, markers: tuple[str, ...]) -> list[tuple[int, int, str]]:
        return [b for b in self._blocks(text) if hook_command_is_ours(b[2], markers)]

    def _entries(self, payload: dict) -> list[tuple[str, str, int]]:
        rows = []
        for event, entries in payload["events"].items():
            for entry in entries:
                for h in entry.get("hooks", []):
                    rows.append((event, h["command"], int(h.get("timeout", 30))))
        return rows

    def _render(self, rows: list[tuple[str, str, int]]) -> str:
        # command values are our own CLI strings (no quotes/backslashes) — safe as-is.
        out = []
        for event, command, timeout in rows:
            out.append("[[hooks]]")
            out.append(f'event = "{event}"')
            out.append(f'command = "{command}"')
            out.append(f"timeout = {timeout}")
            out.append("")
        return "\n".join(out)

    def _strip(self, text: str, markers: tuple[str, ...]) -> tuple[str, bool]:
        lines = text.splitlines()
        drop: set[int] = set()
        for start, end, _ in self._ours_blocks(text, markers):
            drop.update(range(start, end))
        if not drop:
            return text, False
        kept = [ln for i, ln in enumerate(lines) if i not in drop]
        return "\n".join(kept).rstrip("\n"), True

    def install(self, spec: ArtifactSpec) -> bool:
        path = Path(spec.path)
        text = self._read(path)
        stripped, _ = self._strip(text, spec.markers)
        body = self._render(self._entries(spec.payload))
        new = (stripped.rstrip("\n") + "\n\n" + body).lstrip("\n")
        new = new.rstrip("\n") + "\n"
        if path.exists() and self._read(path) == new:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new, encoding="utf-8")
        return True

    def detect(self, spec: ArtifactSpec) -> bool:
        return bool(self._ours_blocks(self._read(Path(spec.path)), spec.markers))

    def remove(self, spec: ArtifactSpec) -> bool:
        path = Path(spec.path)
        if not path.exists():
            return False
        new, changed = self._strip(self._read(path), spec.markers)
        if not changed:
            return False
        # Kimi config.toml is user-owned (not hook-dedicated) — never delete the file,
        # even if empty after stripping (a user may re-add keys). Leave a trimmed file.
        path.write_text((new.rstrip("\n") + "\n") if new.strip() else "", encoding="utf-8")
        return True


class LaunchAgent:
    """A notionmemory-owned macOS LaunchAgent plist.

    The process holds no copy of the secret on disk.  It reads the PAT from
    Keychain for each proxied request, which lets sandboxed agents share the
    user's existing connection without gaining access to the PAT.
    """

    def _is_ours(self, path: Path, markers: tuple[str, ...]) -> bool:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return False
        return any(marker in text for marker in markers)

    def _launchctl(self, action: str, path: Path) -> None:
        if platform.system() != "Darwin":
            return
        domain = f"gui/{os.getuid()}"
        if action == "load":
            subprocess.run(["launchctl", "bootstrap", domain, str(path)],
                           check=False, capture_output=True, text=True)
            subprocess.run(["launchctl", "kickstart", "-k",
                            f"{domain}/com.notionmemory.notion-broker"],
                           check=False, capture_output=True, text=True)
        else:
            subprocess.run(["launchctl", "bootout", domain, str(path)],
                           check=False, capture_output=True, text=True)

    def install(self, spec: ArtifactSpec) -> bool:
        path = Path(spec.path)
        payload = {
            "Label": spec.payload["label"],
            "ProgramArguments": [spec.payload["program"], "broker", "serve"],
            "RunAtLoad": True,
            "KeepAlive": True,
            "ProcessType": "Background",
            "EnvironmentVariables": {"HOME": str(spec.payload["home"])},
        }
        text = "<!-- " + spec.markers[0] + " -->\n" + plistlib.dumps(payload).decode("utf-8")
        changed = not path.exists() or path.read_text(encoding="utf-8") != text
        if changed:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        self._launchctl("load", path)
        return changed

    def detect(self, spec: ArtifactSpec) -> bool:
        return self._is_ours(Path(spec.path), spec.markers)

    def remove(self, spec: ArtifactSpec) -> bool:
        path = Path(spec.path)
        if not self.detect(spec):
            return False
        self._launchctl("unload", path)
        path.unlink(missing_ok=True)
        return True


HANDLERS: dict[str, object] = {
    "skill_mirror": SkillMirror(),
    "bundle_mirror": BundleMirror(),
    "json_hook_block": JsonHookBlock(),
    "toml_hook_block": TomlHookBlock(),
    "opencode_config_entry": OpencodeConfigEntry(),
    "git_hooks": GitHooks(),
    "codex_trust": CodexTrust(),
    "launch_agent": LaunchAgent(),
}
