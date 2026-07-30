# onboard — 안내 설정 (참고 번역)

에이전트가 챗에서 진행하는 첫 설정 흐름. settings 대시보드가 아니라 `onboard` 가 몰고 간다
(대시보드는 Notion 토큰 저장만). state-aware·멱등: `notionmemory status` 로 먼저 상태를
보고 이미 된 단계는 건너뛰며, 미설정만 구조화 선택지로 안내한다.

- 선택 단계는 Claude Code 에선 `AskUserQuestion`(진짜 객관식 UI), Codex 등 미지원 하네스는
  번호 메뉴 폴백. PAT 단계는 지시(대시보드 붙여넣기)라 객관식 아님.
- 순서: PAT(대시보드→`status` 재확인 게이트, raw 토큰 챗 금지) → memory(새로/URL연결/건너뛰기,
  `memory connect --new|--url`, strict) → calendar(동일, `calendar connect`, 타입충돌 거부) →
  library(스캔 예/아니오, `library refresh`) → templates(사용법 한 줄, 설정 없음).
