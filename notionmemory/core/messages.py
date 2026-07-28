"""온보딩 임계 CLI 메시지 카탈로그 (install·teardown·session_start).
대시보드(web/assets/i18n.json)와 별개 — 이건 파이썬 소비, 저건 JS 소비.
en·ko 키셋 동일(테스트가 강제). 조회는 `i18n.t(CATALOG, key, lang, **fmt)`."""

CATALOG = {
    "en": {
        # --- install (core/install/runner.py) ---
        "install.codex_absent": "codex is not on PATH — skipping the Codex target.",
        "install.skip_conflict": (
            "skipped: {id} → {path} already exists but has no ownership marker "
            "({marker}). It may be a skill you created or a mirror left by an old "
            "version (scripts/sync_skills.py), so it was not overwritten — inspect "
            "it and move or delete it yourself, then install again."),
        "install.installed": "installed: {id} → {path}",
        "install.unchanged": "unchanged: {id} → {path}",
        "install.trust_notfound": (
            "Could not find the Codex hook in hooks/list — skipping trust registration."),
        "install.trust_unsafe": (
            "{n} entry(ies) contain control characters/newlines and are skipped "
            "from trust registration."),
        "install.trust_registered": "trust registered: {n} → {path}",
        "install.trust_unchanged": "unchanged: {n} → {path}",
        "install.trust_absent": (
            "Codex hook trust is not registered, so the hooks will not fire — "
            "approve with `notionmemory install --codex --trust-codex-hooks`."),
        "install.receipt": "receipt: {path}",
        # --- teardown (core/install/teardown.py) ---
        "teardown.unknown_handler": (
            "skipped: don't recognize handler '{handler}' for receipt entry {id} — "
            "it looks like a newer version installed it. Remove it with that "
            "version's `notionmemory teardown`."),
        "teardown.will_remove": "will remove: {id} → {path}",
        "teardown.remove_failed_legacy": (
            "remove failed (legacy name): {id} → {path} — still present. Please "
            "check and delete it yourself."),
        "teardown.removed_legacy": "removed (legacy name): {id} → {path}",
        "teardown.remove_failed": (
            "remove failed: {id} → {path} — {err}. Please check and delete it yourself."),
        "teardown.removed": "removed: {id} → {path}",
        "teardown.keep_unowned": (
            "kept (no ownership marker): {path} — it has no marker showing we "
            "installed it ({marker}), so it was left untouched. If an old version "
            "(scripts/sync_skills.py) installed it, delete it yourself."),
        "teardown.pending_git": (
            "warning: {n} unsent git commit(s) will be deleted "
            "(run `notionmemory git flush` first)"),
        "teardown.registered_templates": (
            "profiles for {n} registered template(s) will be deleted (the Notion "
            "originals are preserved — re-register to restore them)"),
        "teardown.will_remove_state": "will remove: state directory → {path}",
        "teardown.remove_failed_state": (
            "remove failed: the state directory is still present → {path} "
            "(check permissions and delete it yourself)"),
        "teardown.removed_state": "removed: state directory → {path}",
        "teardown.will_remove_config": "will remove: config → {path}",
        "teardown.removed_config": "removed: config → {path}",
        "teardown.keep_config": "kept: config (remove with --purge-config)",
        "teardown.will_remove_secrets": "will remove: keyring PAT",
        "teardown.removed_secrets": "removed: keyring PAT",
        "teardown.remove_failed_secrets": (
            "keyring PAT removal failed (or none present) — ignoring"),
        "teardown.keep_secrets": "kept: keyring PAT (remove with --purge-secrets)",
        "teardown.keep_notion": "kept: Notion DBs & pages (user data is never deleted)",
        # --- session_start hook (hooks/session_start.py) ---
        "hook.git_queue": (
            "git: this repo's queue has {n} commit(s). Review them with "
            "`{cli} git list`, read the changes with git show, summarize them into "
            "meaningful units, then save with `{cli} remember --auto --source git "
            "--project {project} --files <changed-files> --url <commit URL>`, and "
            "remove saved commits from the queue with `{cli} git ack <hash...>`. "
            "Also ack commits you judge not worth remembering so the queue doesn't "
            "keep growing."),
        "hook.git_hook_ask": (
            "notionmemory git: the {toplevel} repo has no post-commit capture hook. "
            "Ask the user whether to enable commit capture, and if approved run "
            "`{cli} git install`."),
        "hook.git_hook_installed": (
            "notionmemory git: installed a post-commit hook in the {toplevel} repo "
            "(install_policy=auto — tell the user in one line. If unwanted, "
            "`{cli} git uninstall`)."),
        "hook.library_empty": (
            "library index: none — run `notionmemory library refresh --full` "
            "before your first search"),
        "hook.library_count": "library index: {n} entries, last refreshed {watermark}",
        "hook.watermark_unknown": "(unknown)",
    },
    "ko": {
        # --- install ---
        "install.codex_absent": "codex 가 PATH 에 없어 Codex 타깃은 건너뜁니다.",
        "install.skip_conflict": (
            "건너뜀: {id} → {path} 이(가) 이미 있는데 우리 소유 표시({marker})가 "
            "없습니다. 사용자가 만든 스킬이거나 구버전(scripts/sync_skills.py)이 심은 "
            "미러일 수 있어 덮어쓰지 않았습니다 — 내용을 확인하고 직접 옮기거나 지운 "
            "뒤 다시 설치하세요."),
        "install.installed": "설치: {id} → {path}",
        "install.unchanged": "변경없음: {id} → {path}",
        "install.trust_notfound": "Codex 훅을 hooks/list 에서 찾지 못해 신뢰 등록을 건너뜁니다.",
        "install.trust_unsafe": "{n}건은 제어문자/개행이 포함돼 신뢰 등록에서 건너뜁니다.",
        "install.trust_registered": "신뢰 등록: {n}건 → {path}",
        "install.trust_unchanged": "변경없음: {n}건 → {path}",
        "install.trust_absent": (
            "Codex 훅 신뢰가 등록되지 않아 훅이 발화하지 않습니다 — "
            "`notionmemory install --codex --trust-codex-hooks` 로 승인하세요."),
        "install.receipt": "영수증: {path}",
        # --- teardown ---
        "teardown.unknown_handler": (
            "건너뜀: 영수증 항목 {id} 의 핸들러 '{handler}' 를 모릅니다 — 더 새 "
            "버전이 설치한 것 같습니다. 그 버전의 `notionmemory teardown` 으로 지우세요."),
        "teardown.will_remove": "제거 예정: {id} → {path}",
        "teardown.remove_failed_legacy": (
            "제거 실패(구 이름): {id} → {path} — 남아 있습니다. 직접 확인해 지우세요."),
        "teardown.removed_legacy": "제거(구 이름): {id} → {path}",
        "teardown.remove_failed": (
            "제거 실패: {id} → {path} — {err}. 직접 확인해 지우세요."),
        "teardown.removed": "제거: {id} → {path}",
        "teardown.keep_unowned": (
            "보존(소유 표시 없음): {path} — 우리가 심었다는 표시({marker})가 없어 "
            "손대지 않았습니다. 구버전(scripts/sync_skills.py)이 심은 것이라면 "
            "직접 지우세요."),
        "teardown.pending_git": (
            "경고: 미전송 git 커밋 {n}건이 삭제됩니다 "
            "(notionmemory git flush 로 먼저 반영하세요)"),
        "teardown.registered_templates": (
            "등록 템플릿 {n}건의 프로필이 삭제됩니다 "
            "(Notion 원본은 보존 — 재등록하면 복구됩니다)"),
        "teardown.will_remove_state": "제거 예정: 상태 디렉터리 → {path}",
        "teardown.remove_failed_state": (
            "제거 실패: 상태 디렉터리가 남아 있습니다 → {path} "
            "(권한을 확인하고 직접 지우세요)"),
        "teardown.removed_state": "제거: 상태 디렉터리 → {path}",
        "teardown.will_remove_config": "제거 예정: config → {path}",
        "teardown.removed_config": "제거: config → {path}",
        "teardown.keep_config": "보존: config (지우려면 --purge-config)",
        "teardown.will_remove_secrets": "제거 예정: keyring PAT",
        "teardown.removed_secrets": "제거: keyring PAT",
        "teardown.remove_failed_secrets": "keyring PAT 제거 실패(또는 없음) — 무시합니다",
        "teardown.keep_secrets": "보존: keyring PAT (지우려면 --purge-secrets)",
        "teardown.keep_notion": "보존: Notion DB·페이지 (사용자 데이터는 삭제하지 않습니다)",
        # --- session_start hook ---
        "hook.git_queue": (
            "git: 이 리포 큐에 커밋 {n}건이 있습니다. `{cli} git list`로 확인하고 "
            "git show 로 변경을 읽어 의미 단위로 요약한 뒤 `{cli} remember --auto "
            "--source git --project {project} --files <변경파일> --url <커밋 URL>`로 "
            "저장하고, 저장한 커밋은 `{cli} git ack <hash...>`로 큐에서 제거하세요. "
            "기억할 가치가 없다고 판단한 커밋도 ack로 제거해 큐가 계속 쌓이지 않게 하세요."),
        "hook.git_hook_ask": (
            "notionmemory git: {toplevel} 리포에 post-commit 캡처 훅이 없습니다. "
            "사용자에게 커밋 캡처를 켤지 물어보고, 승인하면 `{cli} git install`을 "
            "실행하세요."),
        "hook.git_hook_installed": (
            "notionmemory git: {toplevel} 리포에 post-commit 훅을 설치했습니다 "
            "(install_policy=auto — 사용자에게 한 줄로 알려주세요. 원치 않으면 "
            "`{cli} git uninstall`)."),
        "hook.library_empty": (
            "library 색인: 없음 — 첫 검색 전 `notionmemory library refresh --full` 필요"),
        "hook.library_count": "library 색인: {n}건, 마지막 갱신 {watermark}",
        "hook.watermark_unknown": "(미상)",
    },
}
