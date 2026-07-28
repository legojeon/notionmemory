from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from notionmemory.core import detection, notion_auth
from notionmemory.core.config import Config
from notionmemory.skills.git import hooks as gc_hooks


@dataclass
class IntegrationStatus:
    id: str
    connected: bool
    detail: str = ""


class Integration(ABC):
    id: str = ""
    name: str = ""

    @abstractmethod
    def status(self, config: Config) -> IntegrationStatus: ...

    def test(self, config: Config) -> IntegrationStatus:
        return self.status(config)


class NotionIntegration(Integration):
    id, name = "notion", "Notion"

    def _token(self, config: Config) -> str:
        return notion_auth.load_pat() or config.integration("notion").get("token") or ""

    def status(self, config: Config) -> IntegrationStatus:
        meta = config.integration("notion")
        if notion_auth.load_pat():
            ws = meta.get("workspace_name")
            return IntegrationStatus(self.id, True, f"PAT ({ws})" if ws else "PAT 저장됨")
        if meta.get("token"):
            return IntegrationStatus(self.id, True, "config 토큰")
        return IntegrationStatus(self.id, False, "PAT 없음 (연결 필요)")

    def test(self, config: Config) -> IntegrationStatus:
        token = self._token(config)
        if not token:
            return IntegrationStatus(self.id, False, "PAT 없음 (연결 필요)")
        result = notion_auth.verify_token(token)
        if result["ok"]:
            name = result.get("name", "")
            return IntegrationStatus(self.id, True, f"검증됨 ({name})" if name else "검증됨")
        return IntegrationStatus(self.id, False, result["error"])


class AgentIntegration(Integration):
    id, name = "agent", "Agent (Claude Code / Codex)"
    BACKENDS = ("claude", "codex")

    def status(self, config: Config, *, refresh: bool = False) -> IntegrationStatus:
        backend = config.integration("agent").get("backend")
        if backend:
            return IntegrationStatus(self.id, True, f"backend={backend} (설정됨)")
        errors = []
        for cand in self.BACKENDS:
            probe = detection.probe_cli(cand, refresh=refresh)
            if probe.ok:
                detail = f"backend={cand} ({probe.version})"
                if detection.dotfolder(cand):
                    detail += f", ~/.{cand} 있음"
                return IntegrationStatus(self.id, True, detail)
            errors.append(f"{cand}: {probe.error}")
        return IntegrationStatus(self.id, False, f"claude/codex 미감지 ({'; '.join(errors)})")

    def test(self, config: Config) -> IntegrationStatus:
        return self.status(config, refresh=True)


class GitIntegration(Integration):
    """커밋 캡처 연동 — 판정 근거는 `git` CLI + post-commit 훅이다.

    예전에는 `gh` 설치와 `gh auth status` 만 봤다. 그건 틀린 판정이었다: 캡처는 로컬
    훅이 큐에 쓰고 flusher 가 읽는 것으로 완결되며 `gh` 는 커밋 Link URL 을 채울 때만
    쓰이고, 실패하면 `git remote` 파싱으로 대체된다. 그래서 gh 없는 기계에서 **정상
    동작하는 연동**이 대시보드에 빨갛게 떴다. gh 는 이제 detail 에만 나오는 선택 항목이다.
    """

    id, name = "git", "git 커밋 캡처"

    def _hooked_repos(self, config: Config) -> tuple[int, int] | None:
        """(훅 걸린 리포 수, 등록된 리포 수). 레지스트리를 못 읽으면 None."""
        try:
            rows = gc_hooks.status(config.path)
        except Exception:
            return None
        return sum(1 for r in rows if r.get("installed")), len(rows)

    def _gh_note(self, refresh: bool) -> str:
        probe = detection.probe_cli("gh", refresh=refresh)
        if probe.ok:
            return "gh 있음(선택 — 커밋 링크 보강)"
        return "gh 없음(선택 — 링크는 git remote 로 대체)"

    def status(self, config: Config, *, refresh: bool = False) -> IntegrationStatus:
        probe = detection.probe_cli("git", refresh=refresh)
        if not probe.ok:
            return IntegrationStatus(self.id, False, f"git 미설치 ({probe.error})")

        counts = self._hooked_repos(config)
        if counts is None:
            return IntegrationStatus(
                self.id, False, f"{probe.version}, 리포 레지스트리를 읽을 수 없습니다")

        hooked, registered = counts
        gh = self._gh_note(refresh)
        if not hooked:
            hint = "훅 설치된 리포 없음 — `notionmemory git install` 로 리포를 등록하세요"
            if registered:
                hint = (f"등록 {registered}개 리포에 훅이 없습니다 — "
                        "`notionmemory git install` 로 다시 설치하세요")
            return IntegrationStatus(self.id, False, f"{probe.version}, {hint}")
        return IntegrationStatus(self.id, True,
                                 f"{probe.version}, 훅 {hooked}개 리포, {gh}")

    def test(self, config: Config) -> IntegrationStatus:
        return self.status(config, refresh=True)


def build_integrations(config: Config) -> dict[str, Integration]:
    return {i.id: i for i in (NotionIntegration(), AgentIntegration(), GitIntegration())}
