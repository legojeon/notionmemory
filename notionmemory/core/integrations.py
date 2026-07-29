from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from notionmemory.core import detection, i18n, notion_auth
from notionmemory.core.i18n import tui
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
        lang = i18n.language(config)
        meta = config.integration("notion")
        if notion_auth.load_pat():
            ws = meta.get("workspace_name")
            detail = f"PAT ({ws})" if ws else tui(lang, "ui.int.notion.pat_saved", "PAT saved")
            return IntegrationStatus(self.id, True, detail)
        if meta.get("token"):
            return IntegrationStatus(self.id, True, tui(lang, "ui.int.notion.config_token", "config token"))
        return IntegrationStatus(self.id, False,
                                 tui(lang, "ui.int.notion.no_pat", "no PAT (connect required)"))

    def test(self, config: Config) -> IntegrationStatus:
        lang = i18n.language(config)
        token = self._token(config)
        if not token:
            return IntegrationStatus(self.id, False,
                                     tui(lang, "ui.int.notion.no_pat", "no PAT (connect required)"))
        result = notion_auth.verify_token(token)
        if result["ok"]:
            name = result.get("name", "")
            if name:
                detail = tui(lang, "ui.int.notion.verified_named", "verified ({name})", name=name)
            else:
                detail = tui(lang, "ui.int.notion.verified", "verified")
            return IntegrationStatus(self.id, True, detail)
        return IntegrationStatus(self.id, False, result["error"])


class AgentIntegration(Integration):
    id, name = "agent", "Agent (Claude Code / Codex)"
    BACKENDS = ("claude", "codex")

    def status(self, config: Config, *, refresh: bool = False) -> IntegrationStatus:
        lang = i18n.language(config)
        backend = config.integration("agent").get("backend")
        if backend:
            return IntegrationStatus(self.id, True,
                                     tui(lang, "ui.int.agent.backend_configured",
                                        "backend={backend} (configured)", backend=backend))
        errors = []
        for cand in self.BACKENDS:
            probe = detection.probe_cli(cand, refresh=refresh)
            if probe.ok:
                detail = f"backend={cand} ({probe.version})"
                if detection.dotfolder(cand):
                    detail += tui(lang, "ui.int.agent.dotfolder_present",
                                 ", ~/.{cand} present", cand=cand)
                return IntegrationStatus(self.id, True, detail)
            err = tui(lang, probe.error_key, probe.error)
            errors.append(f"{cand}: {err}")
        return IntegrationStatus(self.id, False,
                                 tui(lang, "ui.int.agent.not_detected",
                                    "claude/codex not detected ({errors})",
                                    errors="; ".join(errors)))

    def test(self, config: Config) -> IntegrationStatus:
        return self.status(config, refresh=True)


class GitIntegration(Integration):
    """커밋 캡처 연동 — 판정 근거는 `git` CLI + post-commit 훅이다.

    예전에는 `gh` 설치와 `gh auth status` 만 봤다. 그건 틀린 판정이었다: 캡처는 로컬
    훅이 큐에 쓰고 flusher 가 읽는 것으로 완결되며 `gh` 는 커밋 Link URL 을 채울 때만
    쓰이고, 실패하면 `git remote` 파싱으로 대체된다. 그래서 gh 없는 기계에서 **정상
    동작하는 연동**이 대시보드에 빨갛게 떴다. gh 는 이제 detail 에만 나오는 선택 항목이다.
    """

    id, name = "git", "git commit capture"

    def _hooked_repos(self, config: Config) -> tuple[int, int] | None:
        """(훅 걸린 리포 수, 등록된 리포 수). 레지스트리를 못 읽으면 None."""
        try:
            rows = gc_hooks.status(config.path)
        except Exception:
            return None
        return sum(1 for r in rows if r.get("installed")), len(rows)

    def _gh_note(self, refresh: bool, lang: str) -> str:
        probe = detection.probe_cli("gh", refresh=refresh)
        if probe.ok:
            return tui(lang, "ui.int.git.gh_present",
                      "gh present (optional — enriches commit links)")
        return tui(lang, "ui.int.git.gh_absent",
                  "gh absent (optional — links fall back to git remote)")

    def status(self, config: Config, *, refresh: bool = False) -> IntegrationStatus:
        lang = i18n.language(config)
        probe = detection.probe_cli("git", refresh=refresh)
        if not probe.ok:
            err = tui(lang, probe.error_key, probe.error)
            return IntegrationStatus(self.id, False,
                                     tui(lang, "ui.int.git.not_installed",
                                        "git not installed ({error})", error=err))

        counts = self._hooked_repos(config)
        if counts is None:
            return IntegrationStatus(
                self.id, False, tui(lang, "ui.int.git.no_registry",
                                    "{version}, cannot read the repo registry",
                                    version=probe.version))

        hooked, registered = counts
        gh = self._gh_note(refresh, lang)
        if not hooked:
            if registered:
                hint = tui(lang, "ui.int.git.hook_missing_registered",
                          "{registered} registered repo(s) have no hook — "
                          "reinstall with `notionmemory git install`", registered=registered)
            else:
                hint = tui(lang, "ui.int.git.hook_missing_none",
                          "no repos hooked yet — a hook auto-installs when you open an "
                          "agent session in a git repo (or run `notionmemory git install`)")
            return IntegrationStatus(self.id, False, f"{probe.version}, {hint}")
        return IntegrationStatus(self.id, True,
                                 tui(lang, "ui.int.git.hooks_ok",
                                     "{version}, {hooked} repo(s) with hooks, {gh}",
                                     version=probe.version, hooked=hooked, gh=gh))

    def test(self, config: Config) -> IntegrationStatus:
        return self.status(config, refresh=True)


def build_integrations(config: Config) -> dict[str, Integration]:
    return {i.id: i for i in (NotionIntegration(), AgentIntegration(), GitIntegration())}
