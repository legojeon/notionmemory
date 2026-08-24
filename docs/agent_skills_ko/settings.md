---
name: settings
description: notionmemory 웹 설정 대시보드를 연다. 사용자가 "notionmemory 설정 열어줘", "연결/설정 화면 띄워줘" 같이 말하면 이 스킬로 로컬 설정 서버를 (필요 시) 띄우고 브라우저를 연다.
---

# settings

사용자가 notionmemory의 설정(연결·스킬 옵션) 화면을 열려고 하면 아래 순서로 진행한다.

## 1. 이미 떠 있는지 확인

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:8765/api/skills
```

- `200` 이면 서버가 이미 실행 중이다 → 새로 띄우지 말고 3번으로 간다.

## 2. 안 떠 있으면 백그라운드로 기동

`notionmemory` 명령을 쓴다 (설치 시 PATH에 등록된다).

```bash
nohup notionmemory serve >/tmp/notionmemory-serve.log 2>&1 &
```

- 약 1초 기다린 뒤 1번의 `curl` 로 `200` 이 나오는지 확인한다. 안 뜨면 `/tmp/notionmemory-serve.log` 를 확인해 원인을 사용자에게 전달한다.

## 3. 브라우저 열기

```bash
open http://localhost:8765
```

## 4. 사용자에게 안내

- 접속 주소: `http://localhost:8765`
- 이 화면은 **설정 전용**이다 — 연결(Notion PAT 등), 스킬 옵션 기본값, 그리고 **템플릿별 프롬프트**(각 템플릿에 채울 방식·톤)를 저장한다. 자료를 읽어 Notion에 정리·저작하는 실제 작업은 `templates` 스킬(`templates create-page`로 구조 생성 → `templates append`/`templates edit`/`templates image`로 저작)로 한다.
- 종료하려면: `pkill -f "notionmemory serve"`

## 주의

- 포트는 `8765` 고정이다. 서버는 백그라운드로 계속 떠 있으니, 다 쓰면 위 `pkill` 로 종료하도록 안내한다.
