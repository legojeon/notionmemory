# templates 문서편집 → Notion Markdown Content API 이관 (1단계)

- 상태: 설계 확정 대기(사용자 리뷰)
- 작성일: 2026-08-25
- 분류: 아키텍처 (스킬 표면·내부 인터페이스 재설계)
- 브랜치: `feat/templates-markdown-api`

## 배경·동기

notionmemory는 페이지 본문을 다룰 때 손수 짠 변환기(`core/notion_markdown.py`의
`markdown_to_blocks`)로 마크다운→블록 JSON을 만들고, 역으로 블록을 마크다운으로
렌더(`templates/document.py`의 `block_markdown`/`render_blocks`)해 읽는다. 이 방식은
알려진 한계가 있다: H4~H6이 H3로 뭉개지고, 리스트 중첩이 1단으로 평탄화되며,
callout/toggle/columns/TOC를 아예 만들 수 없다.

Notion이 2026-03-11 API 버전에서 **Markdown Content API**(페이지 본문을
Notion-flavored Markdown으로 읽고/쓰고/편집)를 제공한다. notionmemory의 Notion
클라이언트는 **이미 그 버전을 전송**한다(`notion_auth.py:14`), 즉 버전 업 없이 사용
가능하다.

사용자 결정(정책): **"가장 통일되고 공식 API에서 모두 지원하는 방식."** 여러 기능을
하나의 일관된 공식 API로 동등하게 지원하면 최신 API로 이관한다. 실측으로 기능 패리티가
확인됐다(아래 "검증된 사실").

## 범위 (이 spec = 1단계)

전면 통일의 **1단계**로, `templates`의 문서 본문 편집 표면(`DocumentStore`)만
블록-id 주소지정 → **텍스트 주소지정(Markdown API)** 으로 이관한다.

### 포함
- `templates` 문서 연산: read / page add(create) / replace / append / edit(find-replace) / delete(find)

### 제외 (후속 단계 또는 영구 유지)
- **memory 본문**(`skills/memory/notion_db.py`) — 2단계 sub-project
- **library 크롤**(`skills/library/crawl.py`) — 3단계 sub-project
- **introspect**(`templates/introspect.py`) — 스키마 **구조**를 읽어야 하므로 통일 대상 아님(영구 블록 API)
- **이미지 업로드/삽입**(`upload_image`/`add_image`) — Files API + 블록 API 유지 (근거: 검증에서 마크다운 `![](file_upload:id)`는 빈 external 이미지로 깨짐 — 마크다운 이미지 참조는 공개 URL 전용)
- **DB 행/속성**(`templates/store.py`의 query/add/update, `coerce`/`filters`) — data_source API, 본문 아님
- **`core/notion_markdown.markdown_to_blocks`** — memory/library가 2·3단계까지 사용하므로 **제거하지 않음**

### 성공 기준
1. templates 문서편집이 Markdown API만으로 동작(이미지 삽입 제외).
2. 순수 유닛 회귀 스위트 통과 + 라이브 스모크 통과.
3. SKILL.md 워크플로우가 텍스트-주소지정으로 일관 재작성.
4. 설치 계약(`tests/test_artifact_contract.py`) 무영향(새 ArtifactSpec 없음).

## 접근 결정

세 접근(1: API와 1:1 완전 텍스트-주소지정 / 2: read-modify-write 최소 / 3: 하이브리드)
중 **접근 3(하이브리드)** 채택.

- 백본: `read` + `replace`(전체, 항상 성공) + `append`(안전) — 견고한 기본 경로.
- 편의: `edit --find/--replace`, `delete --find` — 외과적이되 실패 시 **큰 소리로**
  (`No matches`/`Multiple matches`) 죽어 조용한 손상이 없음.
- 버림: `insert_content`의 `after` 생략선택자, `replace_content_range` — API에서 가장
  취약하고 거의 불필요.

## 명령 표면 (verbs)

모든 본문 verb는 대상으로 `<slug|page-id>`를 받는다(일관성). slug면 프로필의 루트
페이지로 해석하고(현 `read`와 동일), 명시적 page-id면 그 페이지를 대상으로 한다.

| 명령 | API | 파괴적 |
|---|---|---|
| `templates read <slug\|page-id>` | GET `/pages/:id/markdown` | 아니오 |
| `templates page add <parent> --title … [--markdown/-file]` | POST `/pages {markdown}` | 아니오(생성) |
| `templates append <slug\|page-id> --markdown/-file` | `insert_content` end | 아니오 |
| `templates replace <slug\|page-id> --markdown/-file` | `replace_content` | **예** → 미리보기+`--yes` |
| `templates edit <slug\|page-id> --find … --replace … [--all]` | `update_content`(+`replaceAllMatches`) | **예** → 미리보기+`--yes` |
| `templates delete <slug\|page-id> --find … [--all]` | `update_content` new="" | **예** → 미리보기+`--yes` |

제거: `templates block add/set/remove`, 블록-id, `read`의 `[bid]` 주석.
(참고: `read`의 기존 `[<page-id>]` 2번째 인자는 단일 `<slug|page-id>`로 흡수 — 프롬프트
전용 청사진 템플릿은 루트 페이지가 없으니 명시적 page-id를 요구하는 기존 안내 유지.)

유지되는 안전장치:
- 파괴적 연산은 `--yes` 없으면 **미리보기 후 exit 2, 변이 0건**. 미리보기는 서버
  dry-run이 없으므로 `read()`(GET, 읽기전용)로 현재 본문을 받아 **로컬에서** `find`
  매치 수·바뀔 부분을 계산해 보여준다(무매치/다중매치를 --yes 이전에 경고).
- 입력은 `_text_or_file`(인라인/`--markdown-file`/stdin) 그대로 — 셸 인용 안전.
- `edit`는 기본 단일-매치 강제, 의도적 전체치환은 `--all`.

## 내부 아키텍처 (`templates/document.py` 재작성)

`DocumentStore` 재구성:

**마크다운 텍스트 연산 (신규 — Markdown API)**
- `read(page_id) -> str` : GET `/pages/:id/markdown`의 `markdown`. `truncated` 처리(아래).
- `add_page(parent, title, markdown="") -> {id,url}` : POST `/pages {markdown}` (+ properties.title)
- `append(page_id, markdown)` : `insert_content` position:end
- `replace(page_id, markdown)` : `replace_content` (truncated면 거부)
- `edit(page_id, find, replace, all=False)` : `update_content`; 0/다중 매치 시 `MarkdownEditError`
- `delete(page_id, find, all=False)` : `update_content` new=""

**이미지 연산 (변경 없음 — 블록 API 유지)**
- `upload_image(path)` : Files API `POST /file_uploads`
- `add_image(...)` : `PATCH /blocks/:id/children` image 블록 (마크다운이 file_upload 참조 불가)

**제거**: `block_markdown`, `render_blocks`, `get_block`, `add_blocks`, `set_block`,
`remove_block`, children 페이지네이션 read, `_PREFIX`, `DOC_NODE_CAP`.
**유지**: `_req`, `PageNotFound`.

**신규 에러 `MarkdownEditError`**: API 400 메시지를 감싸 cli가 exit 2 + 명확 안내로 변환.

**truncation 안전장치(중요)**: 큰 페이지는 `read`가 `truncated:true`로 잘려 온다.
잘린 뷰에서 `replace`(전체 재작성) 시 꼬리 소실. → `read`는 잘리면 눈에 띄는 마커를
붙이고, `replace`는 `truncated` 상태에서 **거부**한다. append/edit(부분)는 안전.

## 연산 → API 매핑 (실측 검증된 요청 바디)

```
read     GET  /pages/{id}/markdown → {markdown, truncated, unknown_block_ids}
create   POST /pages {parent, properties.title, markdown}
append   PATCH /pages/{id}/markdown {type:"insert_content",
                                     insert_content:{content, position:{type:"end"}}}
replace  PATCH ... {type:"replace_content", replace_content:{new_str}}
edit     PATCH ... {type:"update_content",
                    update_content:{content_updates:[{old_str,new_str}]}}
           0 match → 400 "No matches found" | >1 → 400 "Multiple matches ... Found N"
           --all → 각 update에 replaceAllMatches:true
delete   PATCH ... {type:"update_content",
                    update_content:{content_updates:[{old_str, new_str:""}]}}
image    upload: POST /file_uploads → send bytes; insert: PATCH /blocks/{id}/children
archive  DELETE /blocks/{id}  (in_trash; 하드딜리트 아님)
```

## 검증된 사실 (라이브 스모크로 실측, 스크래치 페이지는 전부 archive)

- read/create/append/replace/edit/delete 전부 internal PAT로 동작(HTTP 200).
- `edit` 무매치 → 400 `No matches found`; 다중매치 → 400 `Multiple matches ... Found N.
  Set replaceAllMatches to true ...` (조용히 하나 안 고침).
- Notion-flavored 방언 확인: 블록 수식은 `$$`를 **독립 줄**에 둘 때만 블록으로 보존;
  toggle은 `<details>`/`<summary>`를 **독립 줄**에 둘 때 네이티브 생성; callout/columns/TOC
  다 네이티브 생성; H4(`####`)는 정식 블록(클래식 blocks API엔 heading_4 없음 — B 전용 이득);
  중첩 리스트 3단 보존.
- 선두 `# H1`은 페이지 **제목**으로 흡수(비-선두 H1은 본문 유지) — 문서화된 규칙.
- 마크다운 `![](file_upload:id)` → 빈 `external` 이미지(깨짐). 업로드 이미지 삽입은
  블록 API 유지 확정.
- 2026 API는 `PATCH /pages {archived:true}` 거부 → archive는 `DELETE /blocks/{id}`(=in_trash).

## 테스트 전략 (하이브리드)

**순수 유닛테스트 (오프라인, 세션 monkeypatch — 대부분)**
- 각 연산의 요청 바디 정확성(§매핑 그대로 전송).
- `edit --all` → `replaceAllMatches:true`.
- `--yes` 게이트: --yes 없으면 변이 호출 0건 + exit 2 + 미리보기(로컬 계산 old→new·매치 수).
- 에러 매핑: 스텁 400 "No/Multiple matches" → `MarkdownEditError` → cli exit 2 + 명확 메시지.
- truncation: read `truncated:true` → 마커; `replace`는 거부.
- `_text_or_file`(인라인/파일/stdin), `PageNotFound`(404).

**라이브 스모크 (새 pytest 마커 `live_notion`, 기본 제외 — 기존 `harness` 패턴)**
- 실제 왕복 1건: create→append→edit→delete→replace→read→archive(스크래치 페이지).
  PAT·부모페이지 필요, fast 스위트 불포함. 구현 중 직접 실행 검증.

## SKILL.md 재작성 + 마이그레이션

- SKILL.md `templates` 문서편집 섹션을 텍스트-주소지정 워크플로우로 재작성
  (read 순수 마크다운 → edit/append/delete/replace; 파괴적 연산 미리보기 후 --yes).
- CLI help/예시 갱신.
- 기존 페이지 데이터 이관 불필요 — GET markdown이 아무 기존 페이지나 읽음.
- `markdown_to_blocks` 유지(2·3단계까지).
- 설치 계약 무영향(새 ArtifactSpec 없음). SKILL.md 내용 변경 → 다음 `install` 때
  미러 재복사(버전-드리프트 넛지가 안내 — 별도 브랜치 `feat/version-drift-guard`).

## 향후 작업 (이 spec 아님, 종착점 선언)

- 2단계: memory 본문 authoring/read를 Markdown API로.
- 3단계: library 크롤 읽기를 GET markdown으로.
- 완료 후: 소비자가 사라진 `markdown_to_blocks`/블록 렌더 정리 검토.

## 미해결/리스크

- 텍스트-주소지정 편집은 `find`가 API의 정규화된 표현과 정확히 일치해야 함(예: 블록 사이
  빈 줄 정규화). 실패는 명시적 400이라 조용한 손상은 없으나, 다중 블록에 걸친 `find`는
  실패하기 쉬움 — 미리보기 게이트가 이를 --yes 전에 드러냄으로 완화.
- 변환이 서버로 이동 → 순수 유닛테스트 대상이 "요청 조립·에러 분기"로 좁아지고, 실제
  렌더 정합은 라이브 스모크가 담당(하이브리드 전략이 이를 수용).
