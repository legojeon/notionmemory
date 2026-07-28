# notionmemory 작업 규약

## 설치물 계약 — 새 기능을 붙일 때 반드시 읽을 것

notionmemory는 사용자 시스템에 파일을 심는다(스킬 미러, 세션 훅, git 훅, 큐).
심은 것은 `notionmemory teardown` 한 번으로 **전부** 지워져야 한다. 이건 좋은 습관이
아니라 계약이고, `tests/test_artifact_contract.py`가 강제한다.

### 규칙

1. **시스템에 무언가를 심는 기능은 `manifest.build()`에 `ArtifactSpec`을 추가한다.**
   `notionmemory/core/install/manifest.py`. teardown은 매니페스트를 통해서만 설치물을
   찾는다 — 여기 없는 것은 영원히 지워지지 않는다.
2. **아무것도 심지 않는다면 `manifest.OWNS_NOTHING`에 명시한다.** 침묵은 답이 아니다.
   계약 테스트는 둘 중 하나를 고르기 전까지 실패한다.
3. **설치물에는 소유 마커를 남긴다.** 디렉터리는 `.notionmemory-owned` 사이드카,
   JSON/셸 블록은 마커 문자열. 이름만으로 소유권을 판단하지 말 것 — 사용자가 직접 만든
   동명 디렉터리를 지우는 사고가 난다.
4. **마커를 rename하면 구 마커를 레거시 목록에 남긴다.** 구버전이 설치한 것이 고아가
   되어 영원히 제거 불가능해진다. 예: `manifest.HOOK_MARKERS`,
   `skills/git/hooks.py`의 `LEGACY_MARKERS`.
5. **사용자 데이터는 teardown 대상이 아니다.** Notion DB·페이지는 절대 삭제하지 않는다.
   config와 keyring PAT는 기본 보존이고 `--purge-config` / `--purge-secrets`에서만 지운다.

### 스킬인가 아닌가

**시스템에 설치물과 생명주기를 소유하는가**가 판정 기준이다. `git`은 소유한다(리포별
훅·큐·레지스트리) — 그래서 memory의 옵션으로 합칠 수 없다. `gh`는 아무것도 소유하지
않는 외부 도구다 — 그래서 스킬이 아니고, 에이전트가 필요할 때 부르면 된다.

스킬에는 표면 구분이 있다(`Skill.surface`): `agent`는 SKILL.md로 에이전트가 호출하고,
`service`는 SKILL.md 없이 훅으로 돈다(`git`). 새 스킬은 둘 중 하나를 선언한다.

### 이름 규칙

이름은 **도메인 명사**, 기능은 `Skill.kinds`(복수: `capture`/`recall`/`action`)로 표현한다.
이름에 기능을 박으면 verb가 늘어나는 순간 거짓이 된다(`notes-capture` → `notes`).
한 스킬 = 한 이름이 패키지 폴더·스킬 id·config 키·CLI 서브커맨드·`agent_skills` 폴더·
Notion `Source` 값 전부에 동일하게 적용된다.

## 검증

- `./venv/bin/python -m pytest` 전체 통과가 기본.
- 설치·생성물이 관련된 변경은 `./scripts/verify_clean_clone.sh`로 **깨끗한 체크아웃에서**
  재현할 것. 생성물을 커밋하지 않아 작업 트리에서만 통과한 사고가 실제로 있었다.
