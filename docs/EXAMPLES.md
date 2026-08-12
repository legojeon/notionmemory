<p align="center"><b>English</b> | <a href="EXAMPLES.ko.md">한국어</a></p>

# Examples

None of these ship built-in. Each is one of **your own** Notion databases or pages,
registered once with the **templates** skill — and, for the richer ones, an **attached
prompt** that tells the agent how to author into it. After that you just talk, and the
agent follows your spec.

Every card below has two parts: a **base template** (a public Notion template you can
duplicate into your own workspace) and, where used, the **attached prompt** — the
notionmemory layer that lives in your config, not in the Notion page. The prompts shown are
the author's actual Korean prompts; adapt or translate them freely.

> The screenshots are placeholders for now — the author will add them.

---

## 📚 A reading list that tracks itself

*Plain DB — no prompt.*

> *"Add this paper to my reading list — DOI 10.1088/…, tag it exoplanets, status To-read."*

The agent writes the row into your tracker DB **by property name** — status, tags, DOI — and
later *"show me everything still unread"* filters it back by those same properties. This is
the baseline templates move: register any Notion DB and CRUD it in plain language, with no
schema wiring on your side.

- **Base template:** [Research Paper Tracker](https://www.notion.com/templates/research-paper-tracker)
- **Attached prompt:** none — property CRUD only.

---

## 💡 An idea bank that researches itself

*Attached prompt.*

> *"Log this idea: a CLI that turns shell history into a runbook."*

Instead of saving a bare title, the agent follows the template's prompt and fills the page
body across four sections — **the problem & who it's for**, a real **web search of similar
tools and reusable libraries**, a critical **feasibility & risk** read (it's told to name at
least one reason it *won't* work), and **next steps** — then sets Feasibility / Impact /
Effort to match its findings. Say *"just stash it"* and it skips the research and only files
the row.

- **Base template:** [Idea Bank Database](https://www.notion.com/templates/idea-bank-database)
- **Attached prompt:** ↓

<details>
<summary>Attached prompt (author's, in Korean) — click to expand</summary>

```text
이 템플릿(Idea Bank)에 새 아이디어를 등록할 때는 한 줄만 적고 끝내지 말고, 아래 4개 축을
직접 조사해 **속성 + 페이지 본문**에 채운다. 목적은 "떠오른 착상"을 "판단·실행 가능한 형태"로
만드는 것이다. (사용자가 "그냥 빨리 담아만 둬"라고 하면 속성만 채우고 본문 조사는 건너뛴다.)

## 절차
1. `add`로 행을 만들며 속성을 채우고 **행 id**를 받는다.
2. 그 행 id에 `block add --markdown-file <경로>`(또는 `-`=stdin)로 아래 4개 섹션 본문을 붙인다.
   본문에는 링크·코드펜스가 들어가므로 셸에 `--markdown "..."` 직접 전달 금지 — 반드시 파일/stdin.
3. 조사로 알게 된 것에 맞춰 평가 속성(Feasibility·Potential Impact·Effort·Priority)을 다시 정리한다.

## 속성 채우기
- Idea Name: 짧고 검색 가능한 이름 / Description: 핵심 가치 한 줄
- Category(Tech·Business·Education·Lifestyle 등, 없으면 새로 만들되 기존 것 우선) / Tags
- Date Added, Inspiration Source, Link(출처 있으면)
- Status: 기본 `Spark` / Next Step: 가장 먼저 할 검증 한 줄
- **조사 후** Feasibility(Easy/Moderate/Challenging/Unknown) · Potential Impact(Small/Medium/Big/Game-Changer)
  · Effort Estimate(숫자, 예: 사람-주) — 아래 본문 근거와 반드시 일치시킨다.

## 본문 4개 섹션 (## 헤딩 그대로, 한국어·간결·객관)

### ## 💡 아이디어 구체화
- 해결하려는 문제 / 대상 사용자(누가 왜 아쉬워하나)
- 핵심 동작 — 어떻게 작동하는지 한두 문단으로 구체화(입력→처리→출력)
- MVP 범위와 "성공했다"의 기준

### ## 🔍 시장 조사
- 유사 서비스·제품: 이름 + 링크 + 한 줄 특징(최소 2~3개, 웹으로 실제 검색). 없으면 "못 찾음"이라 명시.
- 활용 가능한 오픈소스·모델·라이브러리·API: 이름 + 링크 + 무엇을 대신해 주는지.
- 차별점: 기존 것으로 왜 부족한가 / 이 아이디어가 새로 주는 것.

### ## ⚖️ 현실성 & 평가
- 기술 난이도, 필요한 데이터·리소스·비용, 예상 공수.
- 주요 리스크·불확실성·규제/개인정보 이슈(있으면).
- Feasibility / Potential Impact / Effort 판단 근거를 한 줄씩 — 위 속성값과 같게.
- **비판적으로**: 단점·안 될 이유를 반드시 하나 이상 적는다(과장 금지).

### ## 🚀 확장 & 개선
- 다음 단계: 가장 작고 빠르게 검증할 방법 1개.
- 발전·확장 방향(기능·시장·수익화 등).
- 결합 가능한 다른 아이디어 — Idea Bank 안의 관련 항목이 있으면 이름으로 언급.

## 규칙
- 시장조사·유사서비스·오픈소스는 **에이전트 자신의 웹검색/도구로 실제 확인**한다. 추측이면 "(추정)"이라 표기하고, 확인 못 한 것은 "확인 못 함"이라 솔직히 쓴다. 지어내지 않는다.
- 톤은 홍보문이 아니라 냉정한 검토 노트. 링크는 실제 URL만.
- 사용자가 기존 행을 "구체화/조사해줘"라고 하면: 그 행을 `read`해 이미 있는 섹션을 확인하고, 위 4개 섹션을 같은 형식으로 채우거나 갱신한다(중복 생성 금지).
```

</details>

---

## 📁 A portfolio that reads your actual code

*Attached prompt.*

> *"Add my side project to the portfolio."*

The agent inspects the **real repo** — dependencies with versions, directory layout,
`git log` for the development arc and the fix/refactor commits, CI and Docker files,
screenshot folders — reports what it found, asks you the few things code can't answer
(motivation, real metrics, deploy status), then authors an **evidence-based** project card
with real snippets and cropped figures. It's explicitly forbidden from writing anything not
grounded in the code or commits, so there are no template-filler guesses.

- **Base template:** [Personal Portfolio](https://www.notion.com/templates/personal-portfolio)
- **Attached prompt:** ↓

<details>
<summary>Attached prompt (author's, in Korean) — click to expand</summary>

```text
해당 포트폴리오의 각 프로젝트 페이지는 별도로 조사하여 작성해야하며
아래 순서대로 진행할 것.

━━━━━━━━━━━━━━━━━━━━
[1단계] 조사

다음을 모두 확인해:
- README, package.json / requirements.txt 등 의존성 파일 (버전 포함)
- 디렉토리 구조와 주요 모듈의 역할
- git log --oneline 으로 전체 개발 흐름 및 첫/마지막 커밋 날짜
- fix / refactor / perf / hotfix 관련 커밋들
- .github/ 워크플로우, Dockerfile, docker-compose, 인프라 설정 파일
- git remote get-url origin 으로 저장소 주소
- assets / images / screenshots / docs / static / public 등
  이미지가 모여 있을 만한 폴더와 README 내 이미지 경로

조사 결과를 "📋 조사 결과" 섹션으로 먼저 출력해:
1. 이 프로젝트가 뭘 하는 서비스인지
2. 기술 스택 (버전 포함) — 실제 코드에서 확인된 것만
3. 주요 기능 목록과 각 기능의 진입점 파일
4. 기술적으로 가장 공들인 것으로 보이는 로직 1~2개와 해당 파일 경로
5. 커밋/코드에서 발견된 기술적 문제 해결 흔적 (구체적 커밋 해시와 함께)
6. 발견된 스크린샷/데모 이미지 파일 경로 (없으면 "없음"이라고 명시)
7. 내가 판단하기 어려운 부분 → 질문 목록

━━━━━━━━━━━━━━━━━━━━
[2단계] 확인 필요 항목

위 7번 질문 목록을 "❓ 확인 필요" 섹션으로 다시 정리해.
(예: 프로젝트 동기, 실제 성과 수치, 배포 여부, 향후 계획)
내가 답하면 그 내용을 반영해 3단계 문서를 갱신할 거야.

━━━━━━━━━━━━━━━━━━━━
[3단계] 문서 작성

노션에 붙여넣을 거라 GitHub 전용 문법(뱃지, <details> 태그)은 쓰지 마.
아래 섹션을 이 순서 그대로, 내용이 없어도 제목은 남기고 "[확인 필요]"로 표시할 것.

## 프로젝트 정보
   - 기간: git log 첫/마지막 커밋 날짜 기준
   - GitHub: remote URL
   - 배포 링크: README나 워크플로우에서 확인, 없으면 [확인 필요]

## 한 줄 소개
   - 대표 사진: 한 줄 소개 섹션의 제목 바로 아래, 소개 문장보다 앞에 프로젝트를 대표하는 이미지 1장을 반드시 삽입. 포트폴리오 카드 미리보기로 사용되므로 데모 스크린샷과 구분해 선택. 대표 이미지를 찾을 수 없으면 발견한 데모 이미지 중 프로젝트 성격을 가장 잘 보여주는 1장을 사용.

## 데모
   1단계에서 이미지 파일을 찾았으면 그 경로를 마크다운 이미지로 삽입.
   못 찾았으면 "![데모 스크린샷 - 직접 삽입 필요]" 자리표시자만 남길 것.
   이미지 파일을 임의로 만들어내지 마.
   데모 스크린샷들은 접이식 토글 안에 넣어 기본은 접힌 상태로 구성한다
   (문서가 스크린샷으로 길어지지 않도록). 토글은 표준 마크다운으로 만들
   수 없으므로, "## 데모" 제목만 마크다운으로 넣은 뒤 toggle 블록을 만들고
   그 자식으로 이미지들을 넣는다(Notion API 직접 호출). 대표 이미지(한 줄
   소개)와 비교용 이미지는 토글 밖에 그대로 둔다.

## 개요
   - 왜 만들었나 (2~3줄)
   - 어떻게 해결했나 (2~3줄)
   - 기존 방식이나 유사 서비스와 다른 접근이 있다면 1~2줄.
     코드로 뒷받침되는 경우에만 쓰고, 없으면 이 항목 생략.

## 기술 스택
   표 형식: 분류 | 기술(버전) | 역할
   분류는 Frontend / Backend / DB / Infra
   "역할" 칸에는 이 프로젝트에서 해당 기술이 무엇을 담당하는지만 간단히 쓴다.
     예) Redis 7.2 | 세션 저장 및 토큰 화이트리스트
     예) Prisma 5.x | ORM, 스키마 마이그레이션 관리
   선택 이유나 장점 설명은 쓰지 마.
   기술 선택에 실제 고민이 있었던 항목은 [기술적 의사결정] 섹션에서 다룬다.

## 아키텍처
   Mermaid 코드블록으로 시스템 구성도를 그려줘.
   (클라이언트 / 서버 / DB / 외부 API 간 흐름)
   노션이 mermaid 코드블록을 지원하니 그대로 쓰면 된다.
   실제 코드에서 확인된 컴포넌트만 그릴 것.

## 주요 기능
   3~5개. 각 항목마다:
   - 기능명 + 1줄 설명 + 진입점 파일 경로
   - 구현상 특이점 1줄 (일반적인 구현과 다른 점이 있을 때만)

## 핵심 로직
   기술적으로 가장 공들인 부분 1~2개를 깊이 설명.
   - 동작 흐름을 단계별로 (복잡하면 Mermaid sequenceDiagram 사용)
   - 왜 단순한 방법으로는 안 되는지, 어떤 제약이 있었는지
   - 핵심 코드 스니펫 10줄 이내로 인용 (파일 경로 명시)
   흔한 CRUD 말고, 직접 고민해서 짠 부분을 고를 것.

## 기술적 의사결정
   설계상 고민이 있었던 지점 2~3개.
   "무엇을 선택했나 → 어떤 대안이 있었나 → 왜 이걸 골랐나" 구성.
   근거가 된 파일 경로나 커밋 해시를 함께 표기.

## 트러블슈팅
   1~3개. 각각 문제 → 원인 → 해결 → 결과 4단 구성.
   근거가 된 커밋 해시나 파일 경로를 함께 표기.

## 회고
   2~4문단, 평서체("~했다")로 작성.
   - 이 프로젝트로 새로 배운 것 (기술이든 설계 판단이든)
   - 이 프로젝트의 한계점(아쉬운 점)과 그 이유
   자기평가나 감상("좋은 경험이었다", "많이 성장했다") 금지.
   구체적인 기술 판단에 대한 회고만 쓸 것.

━━━━━━━━━━━━━━━━━━━━
[선택 섹션] 해당되는 경우에만 추가, 아니면 아예 뺄 것

- ERD: DB 스키마가 있고 테이블 관계가 복잡하면 Mermaid erDiagram으로
- API 명세: REST API가 있으면 핵심 엔드포인트 3~5개만 표로
   (메서드 | 경로 | 설명). 전체 나열 금지.

━━━━━━━━━━━━━━━━━━━━
[문체 규칙]

문체는 개조식으로 통일한다.
- "~했습니다", "~입니다" (X)
- "~함", "~로 구성", "~를 적용", "~ 방식 채택" (O)
- 명사형 종결도 허용 ("Redis 기반 캐시 레이어")
단, [회고] 섹션만 평서체("~했다")로 쓴다.

문서는 "내가 만든 프로젝트를 소개하는" 관점으로 쓸 것.
"README에 따르면", "코드를 보면", "확인 결과", "~라고 기술되어 있음" 같은
레포를 분석한 제3자 시점의 표현을 쓰지 마.
근거로 사용한 파일 경로·커밋 해시·소스 출처는 본문에 괄호로 표기하지 마.

━━━━━━━━━━━━━━━━━━━━
[작성 규칙] — 반드시 지킬 것

1. 코드·커밋·설정에서 확인되지 않은 사실은 절대 쓰지 마.
2. 성과 수치(응답속도, 처리량, 사용자 수)는 근거 파일이나 측정 기록이
   실제로 있을 때만 쓴다. 없으면 "[확인 필요: 측정값]"으로 남긴다.
3. 트러블슈팅과 기술적 의사결정은 지어내지 마.
   커밋 이력이나 코드에서 실제로 확인된 것만.
   찾은 게 없으면 "[확인 필요: 기억나는 이슈 알려주세요]"로 둔다.
4. "~를 구현"보다 "~때문에 ~방식 채택"처럼 의사결정이 드러나게.
5. "효율적인", "강력한", "최적화된" 같은 형용사 남발 금지.

━━━━━━━━━━━━━━━━━━━━
[최종 검증]

문서 작성 후 아래 항목을 반드시 확인하고 수정할 것.
- 괄호 안에 커밋 해시, 파일 경로, 소스 출처가 남아 있지 않은지 확인
- 해당 표기가 있으면 삭제하고, 코드 스니펫의 파일 경로 주석도 제거
- 기술적 의사결정·트러블슈팅은 근거를 나열하지 않고 판단과 결과만 서술
- 기간·버전·제품명처럼 내용 이해에 필요한 일반 괄호 표기는 유지 가능
```

</details>

---

## 📝 Lecture notes from raw slides

*Blueprint — prompt-only, reused per subject.*

> *"Turn this lecture PDF into notes."*

A prompt-only **blueprint** stamps out a fresh, structured note each time. You read the
PDF/slides; the agent writes a personal knowledge note **in the source's own language** —
reorganized by concept rather than slide order, key terms glossed on first use, important
figures cropped in beside the paragraph that explains them, and nothing invented that isn't
in the source. Because it's prompt-only, there's no page to duplicate — you recreate it by
attaching the prompt below to a `lecture-note` blueprint.

- **Base template:** none — it's a prompt-only blueprint (no Notion page).
- **Attached prompt:** ↓

<details>
<summary>Attached prompt (author's, in Korean) — click to expand</summary>

```text
강의·논문·학습 자료(PDF/이미지/슬라이드)를 읽어, 몇 달 뒤 다시 봐도 쓸모 있는 개인 지식 노트로 정리한다. 자료에 없는 정보를 아는 척하지 않는다.

[권위·근거]
- 원본 자료가 유일한 사실 근거다. 배경지식·예시·인용·성능 수치·저자 의도·인과 설명을 모델 기억에서 덧붙이지 않는다.
- 명료함을 위해 과감히 재구성·환언하되, 원본의 조건·예외·불확실성·수식·용어·비교 방향은 보존한다.
- 판독이 불확실하면 추측해 완성하지 말고 생략하거나 불확실하다고 명시한다. 의미 없는 오인식 글자는 넣지 않는다.

[용어]
- 핵심 기술 용어·정리·정의·변수 유형은 처음 나올 때 영어 원어와 한국어를 병기한다: `Random variable (확률변수)`. 헤딩·정의 문단·표 레이블·각 절 첫 등장에서 병기형을 쓴다.
- 원본이 한국어 대응어를 주지 않으면 억지로 번역어를 만들지 않는다 — 원어와 약어를 그대로 둔다. 원본의 대소문자·약어·수학 표기를 보존한다.

[구조 — 자료 유형에 맞춰]
- 자료 유형을 원본에서 추론하고, 모든 문서를 같은 틀에 억지로 끼우지 않는다.
  - 강의/개념 노트: 범위 → 선행 개념 → 핵심 개념과 관계 → 원본에 실제로 있는 예제 → 한계·흔한 혼동 → 간결한 종합.
  - 논문: 서지 정보 → 연구 질문 → 동기/공백 → 방법·가정 → 실험 설정 → 결과 → 한계 → 분야와의 관계.
  - 실험/과제/프로젝트: 목표 → 설정·변수 → 절차 → 관찰·결과 → 결과에 근거한 해석 → 실패·불확실성 → 원본에 명시된 다음 단계.
- 공통: 맨 앞에 범위·핵심 질문·절들의 연결을 밝히는 2~4문장 개요를 둔다. 슬라이드/페이지 순서가 아니라 **개념과 논증 구조**로 재편성한다. 용어는 첫 사용 시 정의하고, 그다음 메커니즘·조건·인접 개념과의 관계를 설명한다. 추론은 문단으로, 진짜 병렬 항목·절차·점검표만 리스트로 쓴다. 예시는 원본에 있을 때만 넣는다(가짜 예시 금지). 마지막은 원본에서 따라 나오는 결론의 종합으로 맺고, 일반적 동기부여성 결론을 붙이지 않는다. 빈 헤딩이나 명사 조각만 있는 헤딩을 만들지 않는다.

[문체·문장 품질]
- 자료 자체를 리뷰하지 말고 **주제를 직접 서술**한다. 강의·문서·슬라이드·발표자를 주어로 삼지 않는다. "이 강의는 …", "슬라이드는 …을 보여 준다", "이 자료는 …" 같은 출처보고형 서술을 쓰지 말고 "X는 …로 정의된다", "그림에서 X는 …"처럼 대상에 대한 직접 진술로 쓴다.
- 기본 톤: 담담한 교과서체. 문장은 '–이다/–한다/–이라 한다'로 끝내고, '~해보자/살펴보자/기억하자'처럼 독자를 부르거나 감탄·과장하는 표현은 쓰지 않는다. 군더더기 수식어 없이 사실 위주로 단정하게.
- 한 문단은 한 역할만 맡는다. 1~2문장, 대략 220자를 넘기지 않고, 정의→함의, 조건→예시, 예시→해석, 대조·예외·계산으로 넘어갈 때 빈 줄로 나눈다. 문장은 대략 12~25어절의 직접적 문장을 선호하고, 여러 정의·조건·수식·결론을 한 문장에 몰아넣지 않는다. 전환은 실제 관계(원인·대조·전제·특수화·순서)를 드러낸다. OCR 줄바꿈은 의미로 복원한 뒤 쓰고, 슬라이드 조각을 문장처럼 옮기지 않는다.

[형식]
- 내용 성격에 맞는 마크다운을 고른다(노션이 블록으로 변환한다). 핵심 정의·정리는 별도의 짧은 문단으로 두고 핵심 용어만 굵게 쓴다 — `정의 —`, `Definition —` 같은 접두어나 인용블록을 기계적으로 붙이지 않는다.
- 짧은 정의식은 인라인 LaTeX로, 긴 유도식은 설명 문단 바로 다음 독립된 `$$...$$` 블록으로 둔다. 식 뒤에는 기호를 나열하지 말고 관계·적용 조건을 1~2문장으로 설명한다.
- 비교·속성 정리는 **표**, 순서·절차·알고리즘은 **번호 리스트**, 병렬 나열은 **불릿**, 코드는 언어 지정 **코드블록**, 할 일은 **체크박스**로 쓴다.

[그림]
- 중요한 그림·다이어그램·차트는 원본에서 crop 해, 그것을 해석하는 문단 **바로 다음**에 삽입한다. 그림을 노트 끝에 몰아두지 않는다. 장식용 로고·배경·목차·본문과 완전히 중복되는 페이지는 넣지 않는다.
- 손글씨 메모가 있으면 낱개로 띄우지 말고 관련 문장에 붙여 녹인다. 판독이 불확실한 필기는 추측하지 말고 생략한다.

[Notion 출력 문법]
- `[[위키링크]]`는 노션에서 렌더되지 않으니 쓰지 않는다 — 개념 연결은 일반 문장(중요 용어 굵게)으로.
- 헤딩은 `#`~`###` 3단계까지만, 리스트 중첩은 1단계까지만. 표·인용(`>`)·체크박스·코드블록·수식은 지원된다.
- 노션 슬래시 명령(`/code`, `/table`)이나 HTML 태그를 본문에 쓰지 않는다 — 코드블록·표는 마크다운 문법으로.

[제목]
- 표지/첫 제목 페이지에서 제목을 끌어온다(일반 파일명이나 지어낸 요약이 아니라). 강의 번호와 주제 제목이 보이면 `Lecture N — 원제목` 형태로, 원본의 언어·표현을 보존한다. 없는 강의 번호나 제목을 지어내지 않는다.

[마무리 점검]
- 원본으로 추적되지 않는 주장은 모두 제거한다. 수치·이름·비교·그림이 근거를 갖는지 확인한다. 끊긴 문장·급한 절 전환을 고친다.
```

</details>

---

## Build your own

Register a page or DB — *"register this Notion page as a template"* (paste the URL) — and,
when you want the agent to author into it a certain way, **attach a prompt**: set it in the
settings dashboard, or just tell the agent what the prompt should say. That's the whole
setup. See the [templates skill](../README.md#agents) for the full surface.
