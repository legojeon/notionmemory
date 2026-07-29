---
name: calendar
description: Notion Calendar DB에서 내 일정을 조회·등록·변경·취소한다. 사용자가 "내일/이번 주 일정 뭐야", "회의 잡아줘/일정 등록해줘", "일정 옮겨줘/취소해줘"라고 말할 때 사용한다. 과거 결정·기억 검색은 memory 스킬.
---

# calendar — list / add / update / cancel

실행 명령 (설치 시 PATH에 등록되는 notionmemory 명령 — 어느 프로젝트에서든 그대로 실행):

```bash
notionmemory calendar list [--from YYYY-MM-DD] [--to YYYY-MM-DD] [--days N]
notionmemory calendar add "<title>" --start "YYYY-MM-DD HH:MM" [--end "YYYY-MM-DD HH:MM"] [--location "<장소>"] [--link <url>] [--notes "<메모>"] [--source claude|codex]
notionmemory calendar update <event_id> [--title "..."] [--start "..."] [--end "..."] [--location "..."] [--link <url>] [--status Scheduled|Done|Canceled]
notionmemory calendar cancel <event_id>
notionmemory calendar setup
```

## 규약

1. 상대 시간 표현("내일 오후 3시", "다음 주 월요일")은 **에이전트가 현재 날짜 기준으로 `YYYY-MM-DD HH:MM`으로 변환**해 전달한다. 시각 없이 날짜만 주면 종일 일정이 된다.
2. update/cancel 전 반드시 `list`로 대상을 찾아 사용자에게 보여주고 **명시적 확인**을 받는다.
3. add/update 후 출력된 event_id를 사용자에게 에코한다.
4. 저장 주체 표시: Claude Code 세션이면 `--source claude`, Codex면 `--source codex`.
5. **일정 원문을 Second Brain에 복사하지 않는다.** 일정에서 태어난 결정·사실만 memory 스킬로 저장하고, 그때 add가 출력한 Notion 페이지 URL을 memory의 `--link`로 연결한다.
6. cancel은 Status=Canceled 기록 후 페이지를 Notion 휴지통으로 보낸다(캘린더 앱에서도 사라짐, 30일 내 복원 가능) — 이를 사용자에게 알린다.
7. CLI가 Notion Calendar 앱 연결 안내를 출력하면(최초 DB 생성 시) 사용자에게 그대로 전달한다. 사용자가 "앱에 안 보인다/연결 방법"을 물으면 `calendar setup`을 실행해 안내를 보여준다 — 앱 설정은 API가 없어 자동 적용이 불가능하다.

## 어디에 쓸지 — 조회와 다르다

조회는 여러 소스를 합칠 수 있지만 쓰기는 **한 곳을 골라야** 한다. `notionmemory calendar add`가
exit 2와 함께 후보 목록을 돌려주면, 그것은 "어디에 쓸지 정해지지 않았다"는 뜻이다.
**임의로 고르지 말고 사용자에게 물어라.**

```
어디에 추가할까요?
  1. Calendar DB (내장)
  2. my-planner 템플릿의 Tasks DB
→ 이번만 / 앞으로 계속
```

답을 명령으로 옮긴다:

| 사용자의 답 | 실행할 것 |
|---|---|
| 이번만 · Calendar DB | `notionmemory calendar add ... --here` |
| 이번만 · 템플릿 | `notionmemory templates show <slug>` 로 속성 확인 → `notionmemory templates add <slug> <db-key> --set ...` |
| 앞으로 계속 · Calendar DB | `notionmemory calendar target calendar` 후 다시 `calendar add` |
| 앞으로 계속 · 템플릿 | `notionmemory calendar target template:<slug>/<db-key>` |

**"앞으로 계속"이라고 사용자가 말했을 때만 `calendar target`을 쓴다.** 일회성 답을 영구
기본값으로 승격하면 몇 주 뒤 "왜 여기 들어가지?"를 사용자가 추적할 수 없다.

쓰기 대상이 템플릿으로 지정돼 있으면 `calendar add`는 실행할 명령을 알려주고 거부한다 —
calendar는 다른 템플릿의 데이터베이스에 **쓰지 않는다.** 그 안내대로 `templates` 쪽 명령을
쓰면 된다. 속성 이름은 반드시 `templates show <slug>`로 확인하고 추측하지 마라.

## 연결 & 온보딩

calendar 작업 전(특히 세션의 첫 작업 전) 연결 상태를 확인한다:
`notionmemory status`(전체 현황) 또는 `notionmemory calendar connection`(이 스킬만).

- **PAT 없음(Notion 미연결)**: 직접 고치려 하지 말고 settings 대시보드(`settings` 스킬
  또는 `notionmemory serve` → `http://localhost:8765`)로 안내해 거기서 Notion을 연결하게
  한다. **raw PAT/토큰을 채팅에 붙여넣게 해선 절대 안 된다** — PAT 입력용 CLI는 없고,
  채팅에서 물어보는 순간 대시보드를 쓰는 이유가 사라진다. 사용자가 완료했다고 하면
  `notionmemory status`를 다시 실행한다 — 이건 실제로 연결을 재검증(live verify)하므로
  연결됨으로 나올 때만 진행한다. 이 통과 전에는 DB 설정을 시도하지 않는다.
- **연결됐지만 미바인딩**(`calendar connection`이 "not bound"로 나옴): 메뉴를 제시한다 —
  1) 새 Calendar DB 생성: `notionmemory calendar connect --new`
  2) 기존 DB 연결: `notionmemory calendar connect --url <url>`
  3) 지금은 건너뛰기.
  `connect --url`은 기존 DB를 채택하며, calendar 스키마에 필요한 누락 컬럼을 추가하지만
  **타입이 충돌하면**(같은 이름의 속성이 있는데 타입이 안 맞는 경우 등) 추측하지 않고
  거부한다. 결과 DB 링크와 추가된 컬럼을 보고한다. 거부되면 사유를 그대로 전달하고 메뉴를
  다시 제시한다 — 임의로 고치려 하지 않는다.
- **설정 순서**: 여러 가지가 한꺼번에 미설정이면 이 순서로 처리한다 —
  PAT(settings 대시보드) → memory → calendar → library("검색용으로 색인할까요?" →
  `notionmemory library refresh`) → templates(사용법 안내만, 설정 불필요).

## 내용은 library로 찾는다

"이거 어디 정리했지 / 전에 X 어떻게 했지"처럼 **내용으로 찾는 것**은 이 스킬이 아니라
`library`가 한다 — `notionmemory library search "<질의>"`. Second Brain·등록 템플릿·일반
문서를 가로질러 출처 붙여 찾아준다. 한 소스만 보고 "없습니다"라고 결론짓지 마라.
(날짜·상태 **필터** 조회는 여전히 이 스킬의 몫이다 — library는 텍스트 내용만 찾는다.)
