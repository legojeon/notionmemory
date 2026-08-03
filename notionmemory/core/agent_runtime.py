"""구독형 agent 런타임(headless CLI) 어댑터 — LLM API 키 없이 추론.

스파이크 실측(2026-07-14): `claude -p --output-format text` + stdin 프롬프트로
이미지 절대경로 참조 전사 동작 확인(1페이지 ~12s). 프롬프트가 출력 형식을 엄격히
지시해야 하며(코드펜스·설명 문구 방지), 어댑터는 출력을 가공하지 않는다.
"""
from __future__ import annotations

import os
import subprocess
import tempfile

from notionmemory.core import detection
from notionmemory.core.config import Config


class AgentRuntimeError(Exception):
    pass


_BACKENDS = {"claude", "codex"}


class AgentRuntime:
    def __init__(self, backend: str, binary: str, timeout: float = 300.0,
                 model: str = ""):
        if backend not in _BACKENDS:
            raise AgentRuntimeError(f"지원하지 않는 backend: {backend}")
        self.backend = backend
        self.binary = binary
        self.timeout = timeout
        # config `integrations.agent.model` — 배치 작업(consolidate·git 요약·템플릿
        # 설명/노트)의 모델을 고정한다. 빈 값이면 CLI 기본 모델(무변경 기본값 —
        # 판정+요약 급 작업엔 sonnet 급이면 충분해서, 기본 모델이 상위 티어인
        # 사용자의 비용 절감 노브. 레퍼런스 둘 다 같은 노브를 둔다: agentmemory 는
        # *_MODEL env 기본 gpt-4o-mini, claude-mem 은 CLAUDE_MEM_MODEL+티어 별칭).
        self.model = model

    def _prompt(self, system: str, user: str, image_paths: list | None) -> str:
        parts = [system, "---", user]
        if image_paths:
            files = "\n".join(str(p) for p in image_paths)
            parts.append("다음 이미지 파일들을 직접 읽어 작업하라:\n" + files)
        return "\n\n".join(p for p in parts if p)

    def _run_claude(self, prompt: str) -> tuple[str, str]:
        argv = [self.binary, "-p", "--output-format", "text"]
        if self.model:
            argv += ["--model", self.model]
        try:
            out = subprocess.run(argv, input=prompt, capture_output=True,
                                 text=True, timeout=self.timeout)
        except subprocess.TimeoutExpired:
            return "", f"시간 초과({self.timeout}s)"
        except OSError as exc:
            return "", f"실행 불가: {exc}"
        if out.returncode != 0:
            return "", f"exit {out.returncode}: {out.stderr.strip()[:500]}"
        return out.stdout.strip(), ""

    def _run_codex(self, prompt: str) -> tuple[str, str]:
        # codex exec 는 stdout 이 세션 로그(헤더·hook·tokens) 범벅이라
        # --output-last-message 로 최종 답만 tmp 파일에 받아 읽는다.
        fd, path = tempfile.mkstemp(prefix="notionmemory-codex-", suffix=".txt")
        os.close(fd)
        try:
            argv = [self.binary, "exec", "--skip-git-repo-check"]
            if self.model:
                argv += ["-m", self.model]
            argv += ["--output-last-message", path]
            try:
                out = subprocess.run(argv, input=prompt, capture_output=True,
                                     text=True, timeout=self.timeout)
            except subprocess.TimeoutExpired:
                return "", f"시간 초과({self.timeout}s)"
            except OSError as exc:
                return "", f"실행 불가: {exc}"
            if out.returncode != 0:
                return "", f"exit {out.returncode}: {out.stderr.strip()[:500]}"
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return f.read().strip(), ""
            except OSError as exc:
                return "", f"결과 파일 읽기 실패: {exc}"
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def generate(self, system: str, user: str, image_paths: list | None = None) -> str:
        prompt = self._prompt(system, user, image_paths)
        runner = self._run_codex if self.backend == "codex" else self._run_claude
        last_error = ""
        for _attempt in range(2):
            text, err = runner(prompt)
            if text:
                return text
            last_error = err or "빈 출력"
        raise AgentRuntimeError(f"{self.backend} 호출 실패 — {last_error}")


def build_runtime(config: Config, timeout: float = 300.0) -> AgentRuntime:
    backend = config.integration("agent").get("backend")
    candidates = [backend] if backend else ["claude", "codex"]
    configured = str(config.integration("agent").get("model") or "")
    # 백엔드별 기본 모델 — 배치 작업(판정+요약)엔 상위 티어가 불필요해서 agentmemory 와
    # 같은 정책으로 claude 는 sonnet 을 핀(별칭 — 날짜 ID 와 달리 버전 교체에도 유효).
    # codex 는 모델명 변동이 잦아 핀이 오히려 깨질 위험이 커 CLI 기본에 위임(빈 값).
    # 명시 설정(integrations.agent.model)은 언제나 우선한다.
    backend_default = {"claude": "sonnet", "codex": ""}
    for cand in candidates:
        probe = detection.probe_cli(cand)
        if probe.ok:
            model = configured or backend_default.get(cand, "")
            return AgentRuntime(cand, probe.path, timeout=timeout, model=model)
    raise AgentRuntimeError("agent 런타임 미감지 — claude 또는 codex CLI가 필요합니다")
