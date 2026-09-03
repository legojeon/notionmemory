"""Detect which supported harnesses are present on this machine and whether
notionmemory is already wired into each — registry-driven, so a new harness is
picked up by adding a provider, with no change here.

Read-only: this never installs, removes, or touches anything.
"""
from __future__ import annotations

from dataclasses import dataclass

from notionmemory import providers
from notionmemory.core.install import manifest


@dataclass(frozen=True)
class HarnessState:
    name: str
    display_name: str
    present: bool          # the harness's config home exists on this machine
    installed: bool        # notionmemory is already wired into it
    install_cmd: str       # the command that would wire it


def _wired(spec: providers.ProviderSpec, home) -> bool:
    if spec.install_kind == "bundle":
        return bool(spec.bundle_install_subpath) and (home / spec.bundle_install_subpath).exists()
    try:
        text = (home / spec.hook_file_name).read_text(encoding="utf-8")
    except OSError:
        return False
    return any(m in text for m in manifest.HOOK_MARKERS)


def _install_cmd(spec: providers.ProviderSpec) -> str:
    return " ".join(["notionmemory", "install", f"--{spec.name}", *spec.install_extra_flags])


def detect() -> list[HarnessState]:
    states: list[HarnessState] = []
    for spec in providers.all():
        home = manifest.harness_home(spec.name)
        present = home.exists()
        installed = present and _wired(spec, home)
        states.append(HarnessState(spec.name, spec.display_name, present, installed,
                                    _install_cmd(spec)))
    return states


def pending() -> list[HarnessState]:
    """Present on this machine but not yet wired — what onboarding offers."""
    return [h for h in detect() if h.present and not h.installed]
