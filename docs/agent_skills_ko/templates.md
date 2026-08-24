---
name: templates
description: 등록된 Notion 템플릿/데이터베이스를 조회·추가·수정·작성할 때 사용. "리딩리스트에 추가해줘", "지원 현황 보여줘", "이 템플릿 등록해줘"처럼 사용자가 자기 Notion 템플릿·DB를 언급하면 이 스킬로 notionmemory CLI를 실행한다.
---

# templates

임의의 Notion 템플릿을 등록해 두고 그 스키마대로 CRUD 한다. 우리가 만든 DB(second
brain)와 달리 **스키마를 코드가 모른다** — 그래서 매번 프로필을 읽고 그 안의 이름을
그대로 써야 한다.

## 3단계 규약 — 순서를 지킨다

```
1. notionmemory templates list            # 어떤 템플릿이 등록돼 있나
2. notionmemory templates show <slug>     # DB key·속성명·타입 확인
3. 2에서 본 이름 그대로 add / query / update
```

**2번을 건너뛰고 속성명이나 선택지를 추측하지 마라.** 값 강제 레이어가 어차피 막지만
왕복이 늘어난다. 거부 메시지에는 허용 목록 전체가 들어 있으니 그것을 보고 고쳐 재시도하면 된다.

선택지·관계 대상까지 봐야 하면 `templates show <slug> --full`.

## 조회

```
notionmemory templates query <slug> <db>
  --where "속성 연산자 값"     # 여러 번 = AND
  --search "자유 텍스트"        # 토큰 AND × 텍스트 속성 OR
  --sort "속성 asc|desc"
  --limit N | --all
  --fields "A,B,C" | --count | --json
```

연산자: `=` `!=` `>` `<` `>=` `<=` `contains` `!contains` `starts` `ends` `in` `empty` `!empty`

- **`--limit`을 쓸 거면 `--sort`도 준다.** 정렬 없이 자르면 임의 순서의 앞 N건이다 —
  "최근 5건"을 물었는데 아무 5건이 나온다. 출력이 잘렸으면 그 사실이 마지막 줄에 나온다.
- **날짜는 절대 날짜로 계산해서 넘긴다.** `--where "Due >= 2026-07-22"`. 상대 표현은
  이 CLI가 해석하지 않는다.
- `in`이 OR의 유일한 표면이다: `--where "Status in Todo,Doing"`.
- relation은 이름으로 쓴다: `--where "Company contains Acme"` — id를 찾을 필요 없다.
- 결과의 진짜 row id는 항상 `id` 키다. 대상 DB에 사용자가 만든 `id`/`url`이라는
  이름의 속성이 있으면 그 값은 지워지지 않고 `"id (property)"` / `"url (property)"`
  키로 옮겨져 보존된다 — 그런 이름의 속성을 요청했다면 결과에서 이 키로 찾아라.

## 추가 · 수정 · 아카이브

```
notionmemory templates add <slug> <db> --set "속성=값" [--set ...] [--notes "마크다운"]
notionmemory templates update <slug> <db> <row-id> --set "속성=값"
notionmemory templates archive <slug> <db> <row-id>
```

- `<row-id>`는 `query` 출력의 첫 열이다. 조회 없이 수정하려 하지 마라.
- 선택지에 없는 값은 거부된다. **사용자가 새 옵션을 만들라고 명시했을 때만**
  `--allow-new-option`을 붙인다 — 그냥 붙이면 사용자 워크스페이스에 오타 옵션이 쌓인다.
- 삭제는 없다. `archive`는 휴지통 이동이라 Notion에서 30일 내 복원할 수 있다.

## 등록 · 갱신 · 해제

```
notionmemory templates register <페이지 URL | 페이지 ID | 이름>   # --slug 로 재등록
notionmemory templates refresh <slug>     # 사용자가 Notion에서 스키마를 바꿨을 때
notionmemory templates refresh <slug> --refresh-notes  # 스키마 + 사용 노트(본문)까지 재생성 — 느림
notionmemory templates remove <slug>      # 프로필만 삭제, Notion은 안 건드림
```

- 등록 전에 **그 페이지를 integration에 공유했는지** 확인시킨다(가장 흔한 실패다):
  페이지 우상단 ••• → 연결 → notionmemory.
- 이름으로 등록할 때 후보가 여러 건이면 exit 2와 함께 목록이 나온다 — 사용자에게 되묻는다.
- "속성이 없다"는 에러를 만나면 사용자가 Notion에서 이름을 바꾼 것이다. `refresh`를 먼저 돌린다.

**새 DB를 만들어야 하면** — notionmemory에는 DB 생성 명령이 **없다(의도적)**. 스키마 저작은
네 몫이다: `NotionSession` 으로 Notion API를 직접 호출해 원하는 스키마의 DB를 만들고, 그 URL을
`register` 로 편입해 CRUD 하면 된다. 속성 타입·옵션을 우리 CLI로 가두지 않으니 자유도가 높다.

```python
from notionmemory.core.notion_client import NotionSession
NotionSession().request("POST", "/databases", json={
    "parent": {"page_id": "<부모 페이지 id>"},
    "title": [{"type": "text", "text": {"content": "<DB 이름>"}}],
    "properties": { "Name": {"title": {}}, "Status": {"select": {"options": [...]}} }})
# → 응답의 id/url 을 `notionmemory templates register <url>` 로 편입
```

## 문서 편집 — DB 없는 본문 다루기

템플릿은 데이터베이스만이 아니다. CV·포트폴리오·논문정리처럼 **본문(문단·헤딩·섹션)**이
내용인 페이지도 등록된다. `show <slug>`의 `구조:` 목록이 각 페이지의 헤딩 개요와 page-id를
알려준다.

```
templates read <slug|page-id>                                          # 라이브 본문 → 순수 마크다운 (block-id 없음)
templates append <slug|page-id> --markdown "..." | --markdown-file <경로|-> # 끝에 추가 (자유)
templates page add <parent-page-id> --title "..." [--markdown "..."]   # 하위 페이지 생성 (자유)
templates edit <slug|page-id> --find "..." --replace "..." [--all] --yes  # 찾아 바꾸기 (확인 필요)
templates delete <slug|page-id> --find "..." [--all] --yes                # 매치된 텍스트 삭제 (확인 필요)
templates replace <slug|page-id> --markdown "..." | --markdown-file <경로|-> --yes  # 본문 전체 재작성 (확인 필요)
```

block-id가 아니라 **텍스트로 주소를 지정한다** — 이 워크플로우 어디에도 block-id는 없다.
`read`는 본문을 순수 마크다운으로 출력하고, id 참조가 아니라 텍스트 매치로 내용을 찾아
편집한다.

본문에 **백틱(코드펜스)·따옴표·`$()`** 가 들면 `--markdown "..."` 로 셸에 직접 넘기지 말고
`--markdown-file <경로>`(또는 `--markdown-file -` 로 stdin)를 써라 — 셸이 backtick 을 명령
치환으로 오인하는 것을 피한다. `--find`/`--replace`, `prompt --set-file`,
`new-prompt --prompt-file` 도 동일(프롬프트에 백틱이 흔하다). 마크다운을 파일로 쓴 뒤 그
경로를 넘기는 게 안전하다.

`read` 출력은 순수 마크다운이고, `[db: id]`는 박힌 DB(→ `query`로 다뤄라), `[page: id]`는
하위 페이지(→ 따로 `read`).

**행 본문도 문서다.** DB의 각 행은 그 자체가 페이지다. "논문 추가하고 요약 써줘"는
`add`로 행을 만들어 **행 id**를 받고, 그 id에 `append`로 본문을 채운다 —
CRUD(행) + 문서 편집(본문)의 조합이다.

### 세 가지 규칙

1. **`edit`/`delete`는 위치가 아니라 텍스트로 매치한다.** `--find`에 유일하게 특정될
   만큼 충분한 주변 텍스트를 준다. 매치 0건, 또는 `--all` 없이 다중 매치면 **변경 없이**
   그대로 안내된다 — 현재 본문을 다시 읽어 좁히거나(`--all`로 전체 치환) 재시도한다.
2. **`--yes`는 지름길이 아니다.** `edit`/`delete`/`replace`를 `--yes` 없이 부르면 미리보기
   (무엇이 몇 건 바뀌는지)와 함께 exit 2를 낸다. **사용자에게 그 미리보기를 보여주고
   승인받은 뒤에만** `--yes`로 다시 실행한다. 임의로 `--yes`를 붙여 확인을 건너뛰지 않는다.
   `append`/`page add`는 자유. `replace`는 페이지가 커서 `read`가 본문 전체를 돌려주지
   못할 때는 `--yes`를 붙여도 그대로 거부된다 — 그런 페이지는 `edit`/`append`를 쓴다.
3. **새 항목은 기존 형제를 모방하라.** 새 하위 페이지나 행 본문을 만들 땐, 먼저 기존 형제 하나를
   `read`해 그 섹션 구조를 보고 같은 형태로 작성한다(Notion 데이터베이스 템플릿은 API로 발동할 수 없다).

편집할 그 페이지 하나만 `read`한다(전체 트리 아님). 섹션 구조는 `show`의 캐시된 개요로 이미 안다.

**Notion 방언 마크다운** — 몇몇 구문은 독립된 줄/태그가 필요하다: 블록 수식은 `$$` 를
텍스트와 섞지 않고 독립된 줄에 둔다. toggle 은 `<details><summary>제목</summary>` …
`</details>` 를 각각 독립된 줄에 쓴다. callout 은 `<callout>...</callout>`. columns 는
`<columns><column>...</column><column>...</column></columns>`. 목차는
`<table_of_contents/>`.

## 콘텐츠 저작 — 템플릿에 채우기

각 템플릿엔 **첨부 프롬프트**가 있다(있으면 `templates show`가 보여준다) — "이 템플릿엔
이렇게·이런 톤으로 채워라". 저작 전 반드시 읽고 따른다.

- 새 구조가 필요하면 `templates create-page --parent <id> --title <t> --slug <s>` 로 페이지를
  만들어 등록하고, `templates prompt <s> --set "<지시·톤>"` 으로 프롬프트를 붙인다.
- 본문은 `templates append`/`templates edit`/`templates page`(문서 편집)로, **이미지는
  `templates image <page-id> <로컬이미지> [--caption ...]`** 로 삽입한다(Notion 업로드는
  이 명령이 처리).
- 파일(PDF·코드·HTML)·그림 크롭은 **네 도구로 직접 읽고 만든다** — notionmemory 는 읽지
  않는다. 만든 이미지 파일 경로를 `templates image` 에 넘기면 된다.

### 예시 — 강의노트/논문 정리
"이 강의자료 폴더 정리해줘": (1) 폴더의 PDF/이미지를 네가 읽고(읽기·figure crop 은 네 도구 몫
— PyMuPDF·poppler 등이 없으면 설치하거나 사용자에게 요청한다. notionmemory 는 Notion 쓰기만
담당), (2) `templates page add <부모>` 로 노트 페이지를 만든 뒤, (3) 그 템플릿 프롬프트를 따라
`templates append` 으로 본문을, `templates image` 로 크롭한 그림을 채운다. 논문 정리도 동일 —
구조·톤은 템플릿·프롬프트가, 읽기·크롭은 네가.

`templates create-page` 는 만든 페이지를 **템플릿으로 등록**하는 명령이다 — 하나의 편집 대상
페이지(인스턴스)를 새로 만들 때만 쓴다. 청사진으로 매번 찍는 노트는 등록하면 안 되므로(레지스트리
오염) `templates page add` 를 쓴다.

## 프롬프트 전용 템플릿 (청사진) — 반복 생성

`page_id` 없이 프롬프트만 있는 템플릿은 **청사진**이다 — `templates show` 가 "프롬프트 전용"으로
보이면, 그건 하나의 페이지가 아니라 **매번 새 페이지를 찍는 정의**다.

- 만들기: `templates new-prompt <slug> --name "강의노트" --prompt "<지시·톤>"` (위치 안 정함).
- **쓰기**: "이 강의자료 정리해줘 (강의노트로)" → 그 템플릿의 프롬프트를 읽고, **사용자와 위치를
  정해** `templates page add <부모>` 로 새 페이지를 만든 뒤 그 프롬프트대로 `templates append`/`image`
  로 채운다(등록하지 않는다). 과목마다 반복 — 만든 노트는 독립적으로 존재하고, 나중에 찾는 건 `library`.
- **승격**: "이 노트들을 한 DB에 모으자" 가 되면 그 DB를 **같은 슬러그로 `templates register`**
  하면 인스턴스-DB가 되고(프롬프트 보존), 이후엔 과목마다 그 DB에 행 하나씩 추가한다.
- 프롬프트 전용엔 `query`/`add`/`refresh`(DB·구조 연산)가 없다 — 그 명령은 안내와 함께 막힌다.

### 시드 — 강의노트
은퇴한 note-capture 는 이 청사진으로 되살린다. 한 번 만들어 두면 과목마다 재사용한다.
`templates new-prompt lecture-notes --name "강의노트" --prompt "<아래 프롬프트>"` 로 만들되,
프롬프트는 아래 전문(옛 note-capture 정리 규칙을 증류)을 그대로 넣는다. 톤도 프롬프트 안에 있다
(템플릿 = 구조 + 첨부 프롬프트(톤 포함)):

```
강의·논문·학습 자료(PDF/이미지/슬라이드)를 읽어, 몇 달 뒤 다시 봐도 쓸모 있는 개인 지식 노트로
정리한다. 자료에 없는 정보를 아는 척하지 않는다.

[권위·근거] 원본 자료가 유일한 사실 근거다 — 배경지식·예시·인용·수치·저자 의도를 모델 기억에서
덧붙이지 않는다. 명료함을 위해 과감히 재구성·환언하되 원본의 조건·예외·불확실성·수식·용어·비교
방향은 보존한다. 판독이 불확실하면 추측해 완성하지 말고 생략하거나 불확실하다고 명시한다.

[용어] 핵심 기술 용어·정리·정의는 처음 나올 때 영어 원어와 한국어를 병기한다: `Random variable
(확률변수)`. 원본이 한국어 대응어를 주지 않으면 억지 번역어를 만들지 말고 원어·약어를 그대로 둔다.
대소문자·수학 표기를 보존한다.

[구조] 자료 유형을 원본에서 추론해 맞는 틀을 쓴다(강의: 범위→선행개념→핵심개념과 관계→원본에
있는 예제→한계·혼동→종합 / 논문: 서지→질문→동기→방법→설정→결과→한계 / 실험·과제·프로젝트:
목표→설정→절차→결과→해석→다음단계). 맨 앞에 범위·핵심질문을 밝히는 2~4문장 개요를 둔다.
슬라이드 순서가 아니라 개념·논증 구조로 재편성한다. 예시는 원본에 있을 때만 넣는다.

[문체] 자료 자체를 리뷰하지 말고 주제를 직접 서술한다("이 강의는…/슬라이드는…" 금지 → "X는 …로
정의된다"). 기본 톤은 담담한 교과서체(–이다/–한다), 독자 호출·감탄 금지. 한 문단은 한 역할만,
1~2문장·약 220자 이내로 두고 정의→함의, 조건→예시로 넘어갈 때 빈 줄로 나눈다.

[형식] 핵심 정의·정리는 짧은 문단으로 두고 핵심 용어만 굵게(`정의 —` 접두어·인용블록 남발 금지).
짧은 식은 인라인 LaTeX, 긴 유도식은 독립 `$$...$$`. 비교는 표, 절차는 번호 리스트, 병렬은 불릿,
코드는 언어 지정 코드블록, 할 일은 체크박스.

[그림] 중요한 그림·다이어그램은 crop 해 그것을 해석하는 문단 바로 다음에 삽입한다(끝에 몰지 않음).
장식 로고·목차·본문과 중복되는 페이지는 넣지 않는다. 손글씨는 관련 문장에 붙여 녹이되 판독 불확실한
것은 생략한다.

[Notion 문법] `[[위키링크]]` 쓰지 않는다(개념 연결은 일반 문장). 헤딩 `#`~`###` 3단계·리스트 중첩
1단계까지. 슬래시 명령·HTML 태그 금지 — 표·코드는 마크다운 문법으로.

[제목] 표지/첫 제목에서 끌어온다(파일명·지어낸 요약 아님). 강의번호와 주제가 보이면
`Lecture N — 원제목`, 없는 번호·제목은 지어내지 않는다.
```

## 연결 & 온보딩

memory와 달리 templates엔 내장 DB가 없어 여기서 PAT을 게이팅할 것도, 온보딩
설정 메뉴를 돌릴 것도 없다. 사용자의 Notion이 아직 미연결이면 그건 memory
온보딩(settings 대시보드)이 처리할 몫이지 이 스킬 몫이 아니다. 이 스킬이 처음 쓰일 때
필요한 건 한 줄 설명뿐이다: templates는 **사용자 자신의** Notion 페이지/DB(임의 스키마)를
등록해 이름으로 조회·편집할 수 있게 한다 — settings 대시보드의 "+ 템플릿" 버튼으로
등록하거나, 이 스킬에 `templates register <페이지 URL>`을 그대로 요청해도 된다.

## 다른 스킬과의 관계 — 병렬 소스다

내장 스킬(memory / git)과 등록 템플릿은 **경쟁 관계가 아니다.**
사용자는 자기 데이터가 어디 있는지 말하지 않는다.

1. 답하기 전에 세션 시작 시 주입된 `notionmemory templates:` 목록을 본다.
2. 요청 도메인과 겹치는 템플릿이 있으면 **둘 다 조회하고 출처를 붙여 합친다** —
   "reading-list 2건 · todo-list 1건".
3. **한 소스만 보고 "없습니다"라고 결론짓지 않는다.** 조용한 누락이 유일한 진짜 실패다.
4. 사용자가 템플릿을 지목했을 때만 좁힌다.

## 한계 — 미리 알고 있어야 하는 것

- **페이지 본문은 검색되지 않는다.** Notion API의 DB 필터는 속성만 본다. `--notes`로 넣은
  내용은 어떤 조건으로도 찾을 수 없다. 찾아야 하는 정보는 속성에 넣도록 안내한다.
- 뷰·필터·정렬 설정, relation 상대 행 자동 생성은 지원하지 않는다.

## 서브에이전트에 위임할 때

**세 조건이 모두 참일 때만** 위임한다.

1. 훑을 소스가 **3개 이상**
2. 원본 행이 아니라 **종합**이 필요
3. **읽기 전용**이고 뒤이은 수정이 예상되지 않음

③이 핵심이다 — 서브에이전트는 요약만 돌려주므로 **row id가 소실되고**, 그러면 이어지는
`update`/`archive`가 불가능해져 사용자에게 재조회를 요구하게 된다.

- 위임: "이번 분기에 내가 뭘 했지?" (git + memory + 템플릿 2개, 종합, 읽기 전용)
- 인라인: "지원 현황 보여줘" (소스 1개, 원본 필요, 이어서 수정 가능성)

먼저 `--fields`·`--count`·`--limit`으로 출력을 줄여라. 위임은 그 뒤에도 남는 경우의 수단이지
1차 방어선이 아니다.
