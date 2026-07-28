# notionmemory

Notion을 second-brain 허브로 삼아, 에이전트 장기기억·강의노트 등 여러 소스를 모으는 개인 플랫폼. superpowers처럼 **스킬을 계속 꽂는** 구조.

## 🚀 새 세션(Claude 등)에서 시작하는 법 — 여기부터 읽으세요

**M1(플랫폼 골격)·M2(notes 이식)·M3(memory direct mode)·M4(보안+UI 마감)·§3 리팩터·git(커밋 자동 캡처)·calendar(일정 조회·등록)가 완료**되어 notes/memory/git/calendar 스킬을 실제로 사용할 수 있는 상태입니다(마일스톤 상세는 아래 "마일스톤" 절 참고).

1. **설계 이해**: `docs/superpowers/specs/2026-07-14-notionmemory-second-brain-design.md` 를 읽어 전체 그림·용어(capture/recall/action, 연동 모델)를 파악.
2. **설치**: `uv tool install .` (또는 `pip install -e .`) 후
   `notionmemory install --trust-codex-hooks` — Claude Code와 Codex 양쪽에 스킬과
   세션 훅을 설치한다. 제거는 `notionmemory teardown` (Notion DB는 보존).
   설치물 목록은 `notionmemory teardown --dry-run` 으로 확인한다.

   > **구 버전(`scripts/sync_skills.py`)에서 올라오는 경우**: 그때 심은 스킬 디렉터리에는
   > 소유 표시(`.notionmemory-owned`)가 없다. install은 그런 디렉터리를 덮어쓰지 않고
   > 건너뛰며 경로를 출력하고, teardown도 손대지 않고 알리기만 한다 — 사용자가 직접 만든
   > 동명 스킬과 파일 시스템으로 구분할 수 없기 때문이다. 출력에 나온 경로를 직접 지운 뒤
   > install을 다시 실행하면 된다.
3. 완료 기준(현재): `python -m pytest` 전부 통과 + `notionmemory serve` 로 대시보드가 뜨고 notes/memory/git/calendar 스킬을 실행할 수 있음.

## 실행

1. `cp config.example.yaml config.yaml` (필요한 옵션만 덮어써도 됨; 값 설명은 파일 안 주석 참고).
2. `notionmemory serve` 로 대시보드 기동(기본 포트 8765) 후 브라우저에서 열기.
3. 대시보드의 "연동" 패널에서 Notion PAT를 연결(토큰은 keyring에 저장, config.yaml엔 안 남음). agent 연동은 `claude` 또는 `codex` CLI가 PATH에 있으면 자동 감지된다.
4. notion+agent가 모두 연결되면 notes 카드가 활성화된다. 카드를 열어 `input_dir`(정리할 노트/PDF 폴더)을 지정하고 실행 → 로그가 1초 간격으로 폴링되며, 완료 시 성공/실패/스킵 카운트가 표시된다.
5. 노션에 실제로 내보내기 전에 `limit: 1` + `dry_run: true` 로 먼저 스모크 실행해 보는 것을 권장.

## git (커밋 자동 캡처)

리포에서 커밋할 때마다 순수 셸로 동작하는 post-commit 훅이 커밋 메타(해시·subject·body·변경
파일 목록)를 로컬 큐(`~/.local/state/notionmemory/gitqueue`)에 적재한다 — 네트워크 호출 없이
ms 단위로 끝나며 어떤 경우에도 exit 0(커밋을 절대 깨뜨리지 않음). 큐는 그 자리에서 Notion에
쓰이지 않고, 이후 두 경로 중 하나로 플러시된다: 세션 Stop 훅 리마인더(에이전트가 `git show`로
diff를 확인해 여러 커밋을 의미 단위로 묶어 요약·저장) 또는 `notionmemory git flush`
(headless 배치 요약). **diff 원문은 Notion에 저장하지 않는다** — 해시·Files·GitHub Link만
포인터로 남기고, 코드의 집은 항상 git 자체다.

| 서브커맨드 | 설명 |
| --- | --- |
| `install [path]` | 대상 리포에 post-commit 훅 설치 + 중앙 레지스트리 등록(기존 훅은 마커 블록으로 체이닝) |
| `uninstall [path]` | 훅 제거 + 자동 설치 제외 목록에 등록 |
| `status [--repair]` | 등록된 리포의 훅 상태 일람, `--repair`로 누락분 일괄 재설치 |
| `list [--all]` | 큐 내용 출력(기본 현재 리포, `--all`로 전체) |
| `ack <hash>...` | 저장 완료된 커밋을 큐에서 제거 |
| `flush [--repo path]` | headless로 큐를 요약해 Notion에 저장하고 정리(기본 전체 리포) |

`config.yaml`의 `skills.git`에서 `install_policy`(`auto`\|`ask`\|`off`, 기본 `auto`) /
`repos`(등록된 리포 목록, install이 관리) / `exclude`(자동 설치 제외 목록)를 설정한다.
`install_policy: auto`일 때는 세션 시작 시 현재 리포에 훅이 없으면 자동으로 설치한다.

> **기존 설치 마이그레이션(config 키 rename)**: `notes-capture`→`notes`, `git-capture`→`git`
> 이름 변경 이전에 만든 `config.yaml`이 있다면 `skills.notes-capture:` → `skills.notes:`,
> `skills.git-capture:` → `skills.git:`로 **키 이름만** 바꿔야 한다(값은 그대로 둠). 바꾸지
> 않으면 해당 섹션은 조용히 무시되고 기본값이 쓰인다 — 예: notes의 `parent_page_id`가
> 사라져 엉뚱한 위치에 쓰이거나, git의 `exclude` 목록이 사라져 제외했던 리포에 훅이
> 자동 재설치될 수 있다.

## calendar (일정 조회·등록)

전용 Notion `Calendar` DB를 부트스트랩해 에이전트가 일정을 읽고 쓴다. 일정 하나 = DB 행 하나 =
Notion 페이지(속성 + 본문 메모)이며, 일정 원문은 Second Brain에 복사하지 않는다 — 일정에서
태어난 결정만 memory로 저장하고 페이지 URL을 `--link`로 잇는다.

| 서브커맨드 | 설명 |
| --- | --- |
| `list [--from D] [--to D] [--days N]` | 기본 오늘부터 7일, 시작 오름차순(취소분 제외) |
| `add "<title>" --start "YYYY-MM-DD HH:MM"` | 일정 등록(`--end/--location/--link/--notes/--source`). 시각 없이 날짜만 주면 종일 |
| `update <event_id> [--start ...]` | 준 필드만 변경. 새 start와 기존 end가 안 맞으면 end 제거 + 경고 |
| `cancel <event_id>` | Status=Canceled 기록 후 페이지를 휴지통으로(앱에서도 사라짐, 30일 내 복원 가능) |
| `setup` | Notion Calendar 앱 연결 방법 안내 + DB 바로가기 출력 |

**Notion Calendar 앱 연결은 수동입니다** — 앱 설정에는 공개 API가 없어 자동화할 수 없다.
`notionmemory calendar setup`(또는 대시보드의 calendar 카드)이 알려주는 3단계를 따르면 된다:
① 앱에서 워크스페이스 연결 → ② `Calendar` DB 추가 → ③ **Make default calendar 지정**.
③을 빼먹으면 앱에서 만든 일정이 Google 계정에 저장돼 에이전트가 읽지 못하므로 중요하다.
시각이 있는 일정은 로컬 IANA 타임존으로 저장되고, 조회 구간 경계에도 로컬 오프셋이 붙는다.

## 핵심 설계 결정 (요약)

- **Notion = 허브이자 저장소**(사람·에이전트가 읽고 쓰는 창). memory 스킬은 Second Brain DB에 직접 저장·검색한다 — 별도 메모리 서버 없음.
- **스킬 프리미티브 3종**: `capture`(백그라운드 소스→Notion 단방향) / `recall`(에이전트 호출 Notion 읽기) / `action`(에이전트 호출 1회성 Notion 쓰기). 스킬 하나가 여러 kind를 가질 수 있다(예: memory=capture+recall, calendar=recall+action). **양방향 sync 금지**.
- **명명 규칙 — 이름=도메인, kinds=기능**: 스킬 이름은 "무엇에 대한 스킬인가"(도메인 명사: notes/git/memory/calendar)만 표현하고, "무엇을 하는가"는 `Skill.kinds`(`capture`/`recall`/`action`, 복수 가능)가 표현한다. 한 스킬 = 한 이름 = 패키지 폴더 = 스킬 id = config 키 = CLI 서브커맨드 = Notion `Source` 값. 이름에 기능을 박으면(예: `~-capture` 접미형 이름) 그 스킬에 읽기 verb가 추가되는 순간 이름이 거짓이 된다 — 실제로 두 스킬의 이름을 이 규칙에 맞게 도메인 명사만 남도록 정리한 적이 있다.
- **LLM API 키 없음** — 추론은 구독형 agent 런타임(**claude/codex만**) 경유.
- **Notion 단일 백엔드**(Obsidian 제외).
- Python 3.13 + Flask + PyYAML + pytest.

## 마일스톤

- **M1 — 플랫폼 골격** ✅ 완료: core(config·skill_base·integrations·registry) + 웹 대시보드(스킬 버튼 그리드, 미연결=비활성). 스킬 0개로도 동작.
- **M2 — notes 이식** ✅ 완료: 기존 NoteSync 파이프라인을 이식(Obsidian 제거, LLM→agent 런타임 교체), 비동기 job + 로그 폴링으로 대시보드에서 실행 가능.
- **M3 — memory direct mode** ✅ 완료: `notionmemory remember/recall/forget` CLI가 Notion Second Brain DB에 직접 저장·검색 + 사용자 레벨 훅(SessionStart 자동 주입, Stop/PreCompact 리마인더) + memory 에이전트 스킬(사용자 레벨 미러).
- **M4 — 보안+UI 마감** ✅ 완료: app.js 자동 이스케이프 태그 템플릿(XSS 차단), config 원자적 쓰기(디스크=단일 소스), number 렌더링, 이월 minors 청소, agentmemory 흔적 제거 — `docs/superpowers/plans/2026-07-18-m4-security-ui-polish.md`.
- **§3 리팩터 — NotionSession 통일** ✅ 완료: exporter→NotionSession 통일(byte-send 429 재시도 포함), VERSION 단일화, fingerprint 화이트리스트 재편 — `docs/superpowers/specs/2026-07-18-s3-refactor-notion-session-design.md`.
- **git — 커밋 자동 캡처** ✅ 완료: post-commit 훅 + 로컬 큐 + 세션 Stop 리마인더/`git flush` 배치 요약으로 커밋을 Second Brain에 기록(위 "git" 절 참고, 설계 문서는 `docs/superpowers/specs/` 아래 해당 날짜 파일).
- **calendar — 일정 조회·등록** ✅ 완료: 전용 Calendar DB에 recall+action(list/add/update/cancel/setup, 위 "calendar" 절 참고) — `docs/superpowers/specs/2026-07-20-calendar-design.md`.

## 참고 위치

- 원본 NoteSync 레포(이식 대상): `~/Documents/Projects/NoteSync`
