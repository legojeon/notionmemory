---
name: memory
description: Notion Second Brain에 장기 기억을 저장·검색·삭제한다. 사용자가 "기억해/remember this/save this/note that"라고 말할 때, 지속 가치가 있는 결정·패턴·선호를 배웠을 때, 과거 맥락이 도움이 될 때("전에 어떻게 했지/did we ever") 사용한다.
---

# memory — remember / recall / forget

실행 명령 (설치 시 PATH에 등록되는 notionmemory 명령 — 어느 프로젝트에서든 그대로 실행):

```bash
notionmemory remember "<content>" --type <t> --concepts "a,b,c" [--files "x.py,y.ts"] [--project <p>] [--source claude|codex] [--related <mem_id>] [--link <notion_page_url>] [--supersedes <mem_id>] [--auto]
notionmemory recall "<query>" [--type <t>] [--project <p>] [--top N]
notionmemory recall --get <mem_id>
notionmemory forget <mem_id>
```

## remember 규약

1. content는 사용자 표현을 보존한다 — 재해석·과잉 요약 금지.
2. concepts는 **2~5개, 소문자, 구체적으로**: `jwt-refresh-rotation` ⭕ / `auth` ❌.
3. 참조한 파일 경로가 있으면 `--files`에 기록한다(실제 경로만, 추측 금지).
4. `--type` 선택: pattern(반복 코드 패턴) / preference(사용자 선호) / architecture(구조 결정) / bug(버그와 해결) / workflow(작업 절차) / fact(그 외 사실).
5. 저장 주체 표시: Claude Code 세션이면 `--source claude`, Codex면 `--source codex`.
6. **에이전트가 스스로 판단해 저장할 때는 반드시 `--auto`를 붙인다.** 사용자가 명시적으로 요청한 저장은 `--auto` 없이. exit 2("자동 저장 꺼짐")가 나오면 저장을 포기하고 조용히 넘어간다.
7. 기존 기억을 대체하면 `--supersedes <mem_id>`(원본은 Superseded로 보존), 관련 기억은 `--related <mem_id>`, 관련 Notion 페이지는 `--link <url>`.
8. 저장 후 출력된 mem_id와 concepts를 사용자에게 그대로 에코한다 — 그것이 미래의 검색어다.

## recall 규약

- 사용자의 표현을 그대로 query로 쓴다. 프로젝트/주제가 언급되면 `--project`/`--type`으로 좁힌다.
- **결과는 조작 금지**: 있는 그대로 보고하고, "결과 없음" 폴백이면 없다고 말한 뒤 대체 검색어 2~3개를 제안한다. 지어내지 않는다.
- 본문 전체가 필요하면 `recall --get <mem_id>`.

## forget 규약

- 삭제 전 반드시 recall로 대상을 찾아 사용자에게 보여주고 **명시적 확인**을 받는다.
- Status=Forgotten 처리(하드 삭제 아님)임을 알린다.

## 안티패턴

WRONG: `--concepts "stuff, code, notes"` — 나중에 아무것도 못 찾는다.
RIGHT: `--concepts "jwt-refresh-rotation, token-revocation"` — 구체적·검색 가능.

WRONG: recall 결과가 없는데 "아마 지난주에 논의했던 것 같다"고 추정으로 답한다.
RIGHT: "일치하는 기억이 없습니다. `refresh token`, `session expiry`로 다시 검색해볼까요?"

## 체크리스트

- content가 사용자 표현을 보존했다.
- concepts 2~5개·소문자·구체적.
- 스스로 판단한 저장에 `--auto`가 붙었다.
- recall 결과를 있는 그대로 보고했다.

## 내용은 library로 찾는다

"이거 어디 정리했지 / 전에 X 어떻게 했지"처럼 **내용으로 찾는 것**은 이 스킬이 아니라
`library`가 한다 — `notionmemory library search "<질의>"`. Second Brain·등록 템플릿·일반
문서를 가로질러 출처 붙여 찾아준다. 한 소스만 보고 "없습니다"라고 결론짓지 마라.
(날짜·상태 **필터** 조회는 여전히 이 스킬의 몫이다 — library는 텍스트 내용만 찾는다.)
