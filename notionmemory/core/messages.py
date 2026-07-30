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
            "library: not scanned yet — run `notionmemory library refresh --full` "
            "before your first search"),
        "hook.library_count": "library: {n} pages scanned, last refreshed {watermark}",
        "hook.library_full_refresh": (
            "library: deleted or unshared pages may be lingering in the search index — "
            "run `notionmemory library refresh --full` to prune them (periodic cleanup, ~1-2 min)."),
        "hook.watermark_unknown": "(unknown)",
        "hook.onboarding_offer": (
            "notionmemory isn't fully set up yet ({missing}). Offer the user guided "
            "onboarding: invoke the `onboard` skill — it walks Notion (PAT), memory, and "
            "calendar setup as structured choices (and offers a library scan), skipping "
            "whatever is already done. Not the dashboard — `onboard` drives it."),
        "hook.onboard_item.notion": "Notion not connected",
        "hook.onboard_item.memory": "memory not set up",
        "hook.onboard_item.calendar": "calendar not set up",
        "hook.memory_brief": "project brief ({project}):\n{brief}",
        "hook.memory_top": "high-strength memories ({project}): {items}",
        "hook.memory_pending_consolidation": (
            "unconsolidated memory activity in this project — run `{cli} memory "
            "consolidate` to refine drafts"),
        "hook.memory_index_empty": (
            "memory: local search index is empty — run `notionmemory memory reindex` "
            "to fill it (needed for per-message recall hints)"),
        "notion.auth_invalid": (
            "Notion rejected the token (HTTP 401) — it may be expired, rotated, or "
            "revoked. Reconnect Notion in the settings dashboard (`notionmemory serve`, "
            "or the `settings` / `onboard` skill), then re-check with `notionmemory status`."),
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
            "library: 아직 안 훑어봄 — 첫 검색 전 `notionmemory library refresh --full` 필요"),
        "hook.library_count": "library: {n}건 훑어봄, 마지막 갱신 {watermark}",
        "hook.library_full_refresh": (
            "library: 삭제·공유해제된 페이지가 검색 색인에 남아 있을 수 있습니다 — "
            "`notionmemory library refresh --full` 로 정리하세요(주기적 정리, ~1–2분)."),
        "hook.watermark_unknown": "(미상)",
        "hook.onboarding_offer": (
            "notionmemory 설정이 아직 완료되지 않았습니다({missing}). 사용자에게 안내 "
            "온보딩을 제안하세요: `onboard` 스킬을 호출하면 Notion(PAT)·memory·calendar "
            "설정을 구조화 선택지로 안내하고(라이브러리 스캔도 제안) 이미 된 단계는 "
            "건너뜁니다. settings 대시보드가 아니라 `onboard` 가 진행합니다."),
        "hook.onboard_item.notion": "Notion 미연결",
        "hook.onboard_item.memory": "memory 미설정",
        "hook.onboard_item.calendar": "calendar 미설정",
        "hook.memory_brief": "프로젝트 브리프({project}):\n{brief}",
        "hook.memory_top": "고Strength 메모리({project}): {items}",
        "hook.memory_pending_consolidation": (
            "이 프로젝트에 미정리 항목 있음 — `{cli} memory consolidate` 로 정리하세요"),
        "hook.memory_index_empty": (
            "memory 색인 없음 — `notionmemory memory reindex` 로 채우세요"
            "(메시지당 회수 힌트에 필요)"),
        "notion.auth_invalid": (
            "Notion 이 토큰을 거부했습니다(HTTP 401) — 만료·회전·폐기됐을 수 있습니다. "
            "settings 대시보드(`notionmemory serve`, 또는 `settings`/`onboard` 스킬)에서 "
            "Notion 을 재연결한 뒤 `notionmemory status` 로 확인하세요."),
    },
}

# 대시보드 서버 문자열 ko 오버레이 — `i18n.tui(lang, key, en, **fmt)` 가 소비한다.
# 위 CATALOG(온보딩 임계 CLI)와 달리 en/ko 키셋이 대칭일 필요는 없다: 키가 없으면
# tui() 가 en 인자로 폴백한다(예: exit code/exc 를 담은 detection 에러 일부는 의도적으로
# 미번역 — 포맷 인자를 여기서 못 채우는 자리). 값은 ccf53f6(0.1.1 영어화 스윕) 직전의
# 원본 한국어에서 그대로 가져왔다 — `git show ccf53f6^:<path>` 로 대조 가능.
UI_KO: dict[str, str] = {
    # --- core/integrations.py ---
    "ui.int.notion.pat_saved": "PAT 저장됨",
    "ui.int.notion.config_token": "config 토큰",
    "ui.int.notion.no_pat": "PAT 없음 (연결 필요)",
    "ui.int.notion.verified": "검증됨",
    "ui.int.notion.verified_named": "검증됨 ({name})",
    "ui.int.agent.backend_configured": "backend={backend} (설정됨)",
    "ui.int.agent.dotfolder_present": ", ~/.{cand} 있음",
    "ui.int.agent.not_detected": "claude/codex 미감지 ({errors})",
    "ui.int.git.not_installed": "git 미설치 ({error})",
    "ui.int.git.no_registry": "{version}, 리포 레지스트리를 읽을 수 없습니다",
    "ui.int.git.gh_present": "gh 있음(선택 — 커밋 링크 보강)",
    "ui.int.git.gh_absent": "gh 없음(선택 — 링크는 git remote 로 대체)",
    "ui.int.git.hook_missing_registered": (
        "등록 {registered}개 리포에 훅이 없습니다 — "
        "`notionmemory git install` 로 다시 설치하세요"),
    "ui.int.git.hook_missing_none": (
        "아직 훅이 걸린 리포 없음 — git 리포에서 에이전트 세션을 열면 "
        "자동 설치됩니다(수동: `notionmemory git install`)"),
    "ui.int.git.hooks_ok": "{version}, 훅 걸린 리포 {hooked}개, {gh}",
    "ui.int.git.name": "git 커밋 캡처",
    # --- core/detection.py (Probe.error_key) ---
    "detect.not_on_path": "PATH에 없음",
    "detect.timeout": "실행 시간 초과",
    # --- core/registry.py cards() (skill summary / run_label / setup_steps) ---
    "ui.card.memory.summary": "결정·패턴·선호를 Notion Second Brain 에 장기 저장하고 검색합니다.",
    "ui.card.calendar.summary": "Notion Calendar 에서 일정을 조회·등록·변경·취소합니다.",
    "ui.card.library.summary": "내 Notion 전체를 내용으로 검색해 무엇을 어디에 정리했는지 찾습니다.",
    "ui.card.templates.summary": "등록한 Notion 템플릿·데이터베이스를 조회·추가·수정·작성합니다.",
    "ui.card.git.summary": "커밋을 자동 캡처해 기억 큐에 적재합니다 (post-commit 훅, 백그라운드).",
    "ui.card.calendar.run_label": "실행",
    "ui.card.calendar.setup.0": "앱 Settings → Add Notion workspace 로 워크스페이스를 연결합니다",
    "ui.card.calendar.setup.1": (
        "사이드바에서 워크스페이스 ••• → Add Notion database → 'Calendar' 를 추가합니다"),
    "ui.card.calendar.setup.2": (
        "'Calendar' 위에 마우스 → ••• → Make default calendar 로 기본 캘린더를 지정합니다 "
        "(중요: 지정하지 않으면 앱에서 만든 일정이 Google 계정에 저장돼 에이전트가 읽지 못합니다)"),
    "ui.card.calendar.setup.3": (
        "색을 바꾸려면 'Calendar' 위에 마우스 → ••• → 원하는 색 선택 (색은 DB 단위입니다)"),
    "ui.card.git.run_label": "실행",
    "ui.card.library.run_label": "다시 훑기",
    "ui.card.memory.run_label": "실행",
    "ui.card.templates.run_label": "템플릿 등록",
    # --- skills/*/skill.py options_schema() label/help (overlaid in web/server.py GET options) ---
    "ui.opt.calendar.parent_page_id.label": "부모 페이지 ID",
    "ui.opt.calendar.parent_page_id.help": (
        "Calendar DB를 만들 부모 페이지 ID. 비우면 워크스페이스 최상위에 직접 생성."),
    "ui.opt.calendar.write_target.label": "일정 쓰기 대상",
    "ui.opt.calendar.write_target.help": (
        "비우면 등록된 템플릿과 겹칠 때 매번 되묻습니다. `calendar` = 내장 Calendar DB로 "
        "고정. `template:<slug>/<db-key>` = 그 템플릿으로 안내 (calendar 가 대신 쓰지는 "
        "않습니다)."),
    "ui.opt.git.install_policy.label": "훅 설치 정책",
    "ui.opt.git.install_policy.help": (
        "auto: 세션 시작 시 현재 git 리포에 post-commit 캡처 훅을 자동 설치(제외 목록 "
        "존중). ask: 에이전트가 사용자에게 물어봄. off: 자동 설치 안 함. repos/exclude "
        "목록은 CLI가 관리."),
    "ui.opt.library.full.label": "전체 다시 훑기",
    "ui.opt.library.full.help": (
        "체크하면 공유 페이지 전량을 다시 훑고 공유 해제분을 정리합니다. 비우면 마지막 "
        "갱신 이후 변경분만(빠름)."),
    "ui.opt.memory.capture_mode.label": "캡처 모드",
    "ui.opt.memory.capture_mode.help": (
        "auto: 에이전트가 스스로 판단한 저장(remember --auto)을 허용. manual: --auto "
        "저장을 CLI가 거부(exit 2) — 사용자가 직접 요청한 저장만 통과. 설정은 CLI가 "
        "기계적으로 강제한다."),
    "ui.opt.memory.top_n.label": "recall 상위 N개",
    "ui.opt.memory.top_n.help": "recall이 에이전트 컨텍스트로 반환하는 최대 결과 수.",
    "ui.opt.memory.default_project.label": "기본 프로젝트",
    "ui.opt.memory.default_project.help": "remember 시 --project 미지정이면 이 값을 사용.",
    "ui.opt.memory.parent_page_id.label": "부모 페이지 ID",
    "ui.opt.memory.parent_page_id.help": (
        "Second Brain DB를 만들 부모 페이지 ID. 비우면 워크스페이스 최상위에 직접 생성."),
    "ui.opt.templates.target.label": "템플릿 페이지 URL / ID / 이름",
    "ui.opt.templates.target.help": "Notion 에서 복제하고 integration 에 공유한 페이지.",
    "ui.opt.templates.slug.label": "슬러그(선택)",
    "ui.opt.templates.slug.help": (
        "비우면 페이지 제목에서 유도. 명시하면 같은 이름 덮어쓰기 (재등록)."),
    # --- web/server.py jsonify error strings ---
    "ui.err.token_required": "token 필요",
    "ui.err.name_required": "이름이 필요합니다",
    "ui.err.prompt_only_no_structure": "프롬프트 전용 템플릿은 갱신할 연결 구조가 없습니다",
    "ui.err.refresh_failed": "구조 갱신 실패: {exc}",
    "ui.err.url_required": "Notion URL 이 필요합니다",
    "ui.err.registration_failed": "등록 실패: {exc}",
    # --- core/status.py (notionmemory status) ---
    "ui.status.library.never": (
        "아직 안 훑어봄 — `notionmemory library refresh --full` 로 훑어두세요"),
    "ui.status.library.empty": "0건 훑어봄 (integration 에 공유된 페이지가 아직 없습니다)",
    "ui.status.library.watermark_unknown": "(미상)",
    "ui.status.library.count": "{n}건, 마지막 갱신 {watermark}",
    "ui.status.notion.connected": "연결됨",
    "ui.status.notion.not_connected": "미연결",
    "ui.status.bound": "연결됨",
    "ui.status.not_bound": "미연결",
    "ui.status.library.label": "library 훑어보기",
    "ui.status.probe_failed": "상태 조회 실패: {err}",
}
