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
    def __init__(self, backend: str, binary: str, timeout: float = 300.0):
        if backend not in _BACKENDS:
            raise AgentRuntimeError(f"지원하지 않는 backend: {backend}")
        self.backend = backend
        self.binary = binary
        self.timeout = timeout

    def _prompt(self, system: str, user: str, image_paths: list | None) -> str:
        parts = [system, "---", user]
        if image_paths:
            files = "\n".join(str(p) for p in image_paths)
            parts.append("다음 이미지 파일들을 직접 읽어 작업하라:\n" + files)
        return "\n\n".join(p for p in parts if p)

    def _run_claude(self, prompt: str) -> tuple[str, str]:
        argv = [self.binary, "-p", "--output-format", "text"]
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
            argv = [self.binary, "exec", "--skip-git-repo-check",
                    "--output-last-message", path]
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
    for cand in candidates:
        probe = detection.probe_cli(cand)
        if probe.ok:
            return AgentRuntime(cand, probe.path, timeout=timeout)
    raise AgentRuntimeError("agent 런타임 미감지 — claude 또는 codex CLI가 필요합니다")
