from __future__ import annotations
import argparse
import subprocess
import sys
from pathlib import Path

import requests

from notionmemory.app import build_app, build_registry
from notionmemory.core import i18n, paths, status as status_probe
from notionmemory.core.config import Config
from notionmemory.core.i18n import tui
from notionmemory.core.notion_client import NotionSession
from notionmemory.skills.memory import consolidate as mem_consolidate
from notionmemory.skills.memory import reindex as mem_reindex
from notionmemory.skills.memory.notion_db import (
    CAPTURE_TYPES, NotASecondBrainError, SecondBrainDB, db_url as mem_db_url)
from notionmemory.skills.memory.store import MemoryStore
from notionmemory.skills.git import hooks as gc_hooks
from notionmemory.skills.git import queue as gc_queue
from notionmemory.skills.git.flusher import flush as gc_flush
from notionmemory.skills.library import crawl as library_crawl
from notionmemory.skills.library import index as library_index
from notionmemory.skills.library import retrieve as library_retrieve
from notionmemory.skills.templates import coerce as templates_coerce
from notionmemory.skills.templates import filters as templates_filters
from notionmemory.skills.templates import introspect as templates_introspect
from notionmemory.skills.templates import profile as templates_profile
from notionmemory.skills.templates import render as templates_render
from notionmemory.skills.templates.document import DocumentStore, PageNotFound
from notionmemory.skills.templates.store import ProfileGone, TemplateStore

DEFAULT_CONFIG = str(paths.config_path())


def _parse_kv(tokens: list[str]) -> dict:
    """`--key value`, `--key=value`, 값 없는 `--flag`(→"true")를 dict 로.
    하이픈은 언더스코어로 정규화해 options_schema 키(dry_run 등)와 맞춘다."""
    opts: dict = {}
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if not tok.startswith("--"):
            i += 1
            continue
        body = tok[2:]
        if "=" in body:
            key, val = body.split("=", 1)
            opts[key.replace("-", "_")] = val
            i += 1
            continue
        key = body.replace("-", "_")
        if i + 1 < len(tokens) and not tokens[i + 1].startswith("--"):
            opts[key] = tokens[i + 1]
            i += 2
        else:
            opts[key] = "true"
            i += 1
    return opts


def _cmd_run(rest: list[str], config_path: str) -> int:
    if not rest:
        print("사용법: notionmemory run <skill-id> [input_dir] [--옵션 값 ...]")
        return 2
    skill_id = rest[0]
    tail = rest[1:]
    positional = None
    if tail and not tail[0].startswith("--"):
        positional, tail = tail[0], tail[1:]
    options = _parse_kv(tail)
    if "config" in options:
        print("주의: --config 는 skill-id 앞에 두어야 합니다 "
              "(예: notionmemory run --config path/config.yaml <skill-id>). "
              "뒤에 두면 스킬 옵션으로 흡수됩니다.")
        return 2
    if positional is not None:
        options.setdefault("input_dir", str(Path(positional).expanduser()))

    registry = build_registry(config_path)
    skill = registry.get(skill_id)
    if skill is None:
        ids = ", ".join(sorted(c.id for c in registry.cards())) or "(없음)"
        print(f"알 수 없는 스킬: {skill_id}. 사용 가능: {ids}")
        return 2
    card = next((c for c in registry.cards() if c.id == skill_id), None)
    if card is not None and card.status != "available":
        print(f"'{skill_id}' 실행 불가 — 연결 필요: {', '.join(card.missing) or card.status}")
        return 2

    result = skill.run(options, print)
    print(result.message)
    return 0 if result.ok else 1


def _split_csv(raw: str) -> list[str]:
    return [t.strip() for t in (raw or "").split(",") if t.strip()]


def _print_summary(s: dict, indent: str = "") -> None:
    print(f"{indent}[{s['type']}] {s['mem_id']} · {s['title']}")
    if s["concepts"]:
        print(f"{indent}  concepts: {', '.join(s['concepts'])}")
    if s.get("excerpt"):
        print(f"{indent}  {s['excerpt'][:200].replace(chr(10), ' ')}")
    # 포인터 — "그 코드가 어디 있다"를 에이전트에 전달한다. 이게 있으면 에이전트가
    # 알아서 Read/gh 로 원본을 연다(우리는 열람 능력이 아니라 위치만 준다).
    # 없는 기억이 대부분이므로 있을 때만 찍는다 — session_start 주입도 이 함수를 탄다.
    if s.get("files"):
        files = s["files"]
        shown = ", ".join(files[:8])
        # 잘랐으면 잘랐다고 말한다 — 8개까지만 찍고 끝내면 그게 전부인 것처럼 읽힌다.
        if len(files) > 8:
            shown += f" (외 {len(files) - 8}개)"
        print(f"{indent}  files: {shown}")
    if s.get("url"):
        print(f"{indent}  link: {s['url']}")


def _cmd_remember(args) -> int:
    config = Config.load(args.config)
    opts = config.skill_options("memory")
    # fail-closed: "auto"(또는 미설정)만 자동 저장을 허용한다. 그 외 값(오타, 임의
    # POST 값 등)은 전부 manual과 동일하게 --auto 를 거부한다 — 정책 토글이므로
    # 알 수 없는 값을 자동 허용(fail-open) 쪽으로 해석하면 안 된다.
    capture_mode = str(opts.get("capture_mode") or "auto")
    if args.auto and capture_mode != "auto":
        print("자동 저장 꺼짐 — 사용자가 요청한 경우만 저장 (capture_mode=manual)")
        return 2
    store = MemoryStore(NotionSession(), config)
    concepts = _split_csv(args.concepts)
    # 수동 특권: --auto 없이 저장한 건 사용자가 직접 요청한 것이므로 Active로
    # 바로 들어간다. --auto (에이전트 자체 판단)는 Draft — consolidation 전까지
    # 회수는 되지만(빌드 필터가 Draft도 포함) 아직 "확정"은 아니다.
    # Strength도 같은 특권을 반영한다: 사용자가 명시적으로 "기억해" 라고 한 건
    # 정의상 고신호이므로 SessionStart의 top_memories 게이트(≥8)를 바로 넘긴다.
    # --auto 초안은 7(플레이스홀더) — consolidation이 실제 값을 매길 때까지는
    # Draft라 애초에 top_memories 대상이 아니다(Status=Active만 본다). 이걸 안
    # 하면 수동 저장이 Active-7로 영구 고정돼 SessionStart에서 다시는 안 보이는
    # 회귀가 난다(consolidation은 Draft만 승격하고 이미 Active인 행은 건드리지
    # 않으며, Strength를 다시 매길 CLI도 없다).
    status = "Draft" if args.auto else "Active"
    strength = 7 if args.auto else 8
    result = store.remember(
        args.content, mem_type=args.type, concepts=concepts,
        project=args.project or str(opts.get("default_project") or ""),
        files=_split_csv(args.files), source=args.source,
        related=_split_csv(args.related), links=args.link,
        supersedes=args.supersedes, url=args.url, status=status, strength=strength)
    line = f"Saved {result['mem_id']} with {len(result['concepts'])} concepts"
    if result["concepts"]:
        line += ": " + ", ".join(result["concepts"])
    print(line)
    if result.get("supersede_error"):
        print(f"경고: supersede 마킹 실패 — {result['supersede_target']}는 여전히 Active, "
              f"수동 처리 필요 ({result['supersede_error']})")
        return 1
    return 0


def _cmd_recall(args) -> int:
    if args.top < 0:
        print(f"--top 은 0 이상이어야 합니다 (0=설정 기본값 사용): {args.top}")
        return 2
    config = Config.load(args.config)
    opts = config.skill_options("memory")
    store = MemoryStore(NotionSession(), config)
    if args.get:
        found = store.get(args.get)
        if found is None:
            print(f"메모리 없음: {args.get}")
            return 1
        _print_summary(found)
        print()
        print(found["content"])
        return 0
    top = args.top or int(opts.get("top_n") or 5)
    out = store.recall(args.query, mem_type=args.type, project=args.project, top=top)
    if out["fallback"] and out["results"]:
        print(f"결과 없음 — 최근 {len(out['results'])}건:")
    for s in out["results"]:
        _print_summary(s)
    if not out["results"]:
        print("(저장된 memory 없음)")
    return 0


def _cmd_forget(args) -> int:
    config = Config.load(args.config)
    store = MemoryStore(NotionSession(), config)
    if not store.forget(args.mem_id):
        print(f"메모리 없음: {args.mem_id}")
        return 1
    print(f"Forgotten: {args.mem_id} (Status=Forgotten — 하드 삭제 아님)")
    return 0


def _git_toplevel() -> str:
    """현재 작업 디렉터리가 속한 git 리포의 toplevel 경로.
    실패(git 리포 아님 등) 시 빈 문자열을 반환한다."""
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _cmd_git(args) -> int:
    from pathlib import Path as P
    if args.action == "uninstall" and getattr(args, "all", False):
        rows = gc_hooks.status(args.config)
        if not rows:
            print("등록된 리포 없음 — 제거할 훅이 없습니다")
            return 0
        for r in rows:
            gc_hooks.uninstall(P(r["repo"]), args.config)
            print(f"git 훅 제거: {r['repo']}")
        print(f"총 {len(rows)}개 리포에서 제거 완료 (+자동 설치 제외 등록)")
        return 0
    if args.action in ("install", "uninstall"):
        repo = P(args.path).resolve()
        try:
            fn = gc_hooks.install if args.action == "install" else gc_hooks.uninstall
            fn(repo, args.config)
        except RuntimeError as e:
            print(str(e))
            return 1
        verb = "설치" if args.action == "install" else "제거(+자동 설치 제외 등록)"
        print(f"git 훅 {verb}: {repo}")
        if args.action == "install" and not gc_queue.queue_root_writable():
            print(f"경고: 큐 디렉터리를 만들 수 없습니다({gc_queue.queue_root()}) — "
                  "훅이 커밋을 기록하지 못합니다. 상위 디렉터리 권한을 확인하세요.")
        return 0
    if args.action == "status":
        rows = gc_hooks.status(args.config)
        if not gc_queue.queue_root_writable():
            print(f"경고: 큐 디렉터리를 만들 수 없습니다({gc_queue.queue_root()}) — "
                  "훅이 커밋을 기록하지 못합니다. 상위 디렉터리 권한을 확인하세요.")
        if not rows:
            print("등록된 리포 없음 — notionmemory git install <repo>")
        for r in rows:
            state = "OK" if r["installed"] else ("훅 없음" if r["exists"] else "리포 없음")
            print(f"[{state}] {r['repo']}")
            if args.repair and r["exists"] and not r["installed"]:
                gc_hooks.install(P(r["repo"]), args.config)
                print(f"  → 재설치됨")
        return 0
    if args.action == "list":
        scope = None
        if not args.all:
            scope = _git_toplevel() or str(P.cwd())
        entries = gc_queue.list_entries(scope)
        for e in entries:
            print(f"{e['hash']} [{P(e['repo']).name}/{e['branch']}] {e['subject']}"
                  + (f" (files: {','.join(e['files'])})" if e["files"] else ""))
        if not entries:
            print("(큐 비어 있음)")
        return 0
    if args.action == "ack":
        removed = gc_queue.ack(args.hashes)
        print(f"큐에서 {removed}건 제거")
        return 0
    if args.action == "flush":
        return gc_flush(Config.load(args.config), print, repo=args.repo)
    return 2


def _binding_line(skill_id: str, b: dict, lang: str) -> str:
    """`status.probe()`의 한 스킬 바인딩(`{"bound","url"}`)을 사람이 읽는 한 줄로.

    `notionmemory status`(`_format_status`)와 `notionmemory memory connection`이
    이 하나만 공유한다 — 둘 다 같은 "bound/not bound" 개념이므로 문구를 두 벌로 두면
    `language: ko` 사용자가 `status`에서는 `연결됨`을 보고 `connection`에서는 하드코딩된
    영어 `bound`를 보는 드리프트가 난다(Fix round 1)."""
    if b["bound"]:
        return f"{skill_id}: {tui(lang, 'ui.status.bound', 'bound')} → {b['url']}"
    return f"{skill_id}: {tui(lang, 'ui.status.not_bound', 'not bound')}"


def _connect_db(db, config, skill_id: str, args, *, new_kwargs: dict, exc_types: tuple,
                url_fn) -> int:
    """memory 공용 connect 핸들러.

    `--new` → `ensure(parent, meta, **new_kwargs)`(생성+바인딩). `--url` → `extract_page_id`
    로 URL/ID 를 32-hex 로 파싱한 뒤 `adopt(dbid, meta)`(기존 DB 채택). argparse 가
    `--new`/`--url` 을 상호배타 필수 그룹으로 강제하므로 여기서는 어느 쪽인지만 분기한다.
    파싱 실패("" 반환, 즉 URL/ID 도 아닌 임의 문자열)는 adopt 를 부르기 *전에* 걸러
    사용자에게 명확히 안내한다. adopt/ensure 가 던지는 깨끗한 예외(스키마 충돌·second
    brain 아님 등, 전부 ValueError 하위)는 여기서 잡아 메시지만 찍고 traceback 없이
    exit 2 — 원시 API 호출을 CLI 표면에 그대로 노출하지 않는다.

    성공하면 `meta.get_meta("database_id")`로 갓 바인딩된 DB id를 되읽어 `url_fn`으로
    링크를 붙인다 — 결과(생성/채택된 DB)를 알리는 것도 계약의 일부다(Fix round 1)."""
    from notionmemory.core.config import SkillMeta
    meta = SkillMeta(config, skill_id)
    dbid = ""
    if args.url:
        dbid = templates_introspect.extract_page_id(args.url)
        if not dbid:
            print("유효한 Notion DB URL/ID 가 아닙니다")
            return 2
    try:
        if args.new:
            parent = str(config.skill_options(skill_id).get("parent_page_id") or "")
            db.ensure(parent, meta, **new_kwargs)
            tail = "(새로 생성)"
        else:
            added = db.adopt(dbid, meta)
            tail = f" — 속성 추가: {', '.join(added)}" if added else ""
        bound_id = str(meta.get_meta("database_id") or "")
        link = f" → {url_fn(bound_id)}" if bound_id else ""
        print(f"{skill_id} DB 연결 완료{tail}{link}")
        return 0
    except exc_types as e:
        print(str(e))
        return 2


def _cmd_memory(args) -> int:
    """`memory` 신규 서브파서 그룹 — `connect`/`connection`/`consolidate`/`reindex` 를
    담는다. remember/recall/forget 은 top-level 로 그대로 둔다(브리프 명시: 여기로
    옮기지 않는다)."""
    config = Config.load(args.config)
    if args.action == "connection":
        lang = i18n.language(config)
        print(_binding_line("memory", status_probe.probe(config, verify=False)["memory"],
                            lang))
        return 0
    if args.action == "connect":
        return _connect_db(SecondBrainDB(NotionSession(), log=print), config, "memory", args,
                           new_kwargs={},
                           exc_types=(NotASecondBrainError, ValueError, RuntimeError),
                           url_fn=mem_db_url)
    if args.action == "consolidate":
        if args.auto:
            # 훅이 detached 로 스폰한 백그라운드 경로 — stdout 이 없다(DEVNULL).
            # 락을 여기서 잡고 반드시 여기서 놓는다(autorun.maybe_spawn 은
            # pre-check 만 하고 락을 잡지 않으므로, 실제 상호배제는 이 블록의 몫).
            # 실패해도 조용히 0 반환 — 큐는 보존되고 다음 회차에 재시도, 자세한
            # 내용은 file_log 로만 남는다(터미널로 노출되면 안 됨).
            from notionmemory.skills.memory import autorun
            if not autorun.acquire_lock():
                return 0
            try:
                mem_consolidate.run(config, autorun.file_log, project=args.project or "",
                                    auto=True)
            except Exception as exc:
                # 백그라운드 프로세스의 유일한 관측 창구가 file_log 다 — run() 내부
                # per-project try/except 를 벗어난 예외(예: 루프 진입 전 큐/원장
                # 로드 실패)가 stderr=DEVNULL 로 조용히 삼켜지면 실패 흔적이 아예
                # 남지 않는다. 여기서 잡아 로그에 남기고도 return 0 은 유지한다
                # (백그라운드 경로는 절대 실패 종료코드를 내지 않는다 — 큐는 보존됨).
                autorun.file_log(f"consolidate --auto 실패: {exc!r}")
            finally:
                autorun.release_lock()
            return 0
        res = mem_consolidate.run(config, print, project=args.project or "")
        if res.get("error"):
            return 1
        print(f"승격 {res['promoted']}건 · 드롭 {res['dropped']}건 · 병합 {res['merged']}건"
             f" · 발굴 {res.get('mined', 0)}건"
             f" · 브리프 갱신 {'예' if res['brief_updated'] else '아니오'}")
        return 0
    if args.action == "reindex":
        count = mem_reindex.run(config, print)
        if count < 0:
            return 1
        print(f"memory reindex 완료 — {count}건 색인")
        return 0
    return 2


def _templates_register(args) -> int:
    from notionmemory.core.agent_runtime import AgentRuntimeError, build_runtime
    try:
        runtime = build_runtime(Config.load(args.config))
    except AgentRuntimeError as exc:
        print(f"agent 런타임 미감지({exc}) — 사용 노트 없이 등록합니다")
        runtime = None
    try:
        p = templates_introspect.register(NotionSession(), args.target, slug=args.slug,
                                          runtime=runtime, log=print)
    except templates_introspect.AmbiguousTarget as exc:
        print(str(exc))
        for c in exc.candidates:
            print(f"  · {c['title']} — {c['url'] or c['id']}")
        return 2
    print(f"{p.slug} 등록 완료 — 데이터베이스 {len(p.databases)}개")
    return 0


def _templates_show(args) -> int:
    p = templates_profile.load(args.slug)
    print(f"{p.slug} — {p.name} [{p.health}]")
    if p.summary:
        print(f"  {p.summary}")
    if p.prompt:
        print(f"  프롬프트: {p.prompt}")
    if p.capabilities:
        print(f"  capabilities: {', '.join(p.capabilities)}")
    for db in p.databases:
        mark = " (사라짐)" if db.get("missing") else ""
        print(f"\n  {db['key']}{mark} — {db['title']}")
        for prop in db.get("properties") or []:
            line = f"    {prop['name']}: {prop['type']}"
            if not prop.get("writable"):
                line += " (읽기 전용)"
            if not prop.get("filterable"):
                line += " (조회 불가)"
            if args.full and prop.get("choices"):
                line += f" [{', '.join(prop['choices'])}]"
            if args.full and prop.get("relates_to"):
                line += f" → {prop['relates_to']}"
            print(line)
    if args.full and p.body:
        print("\n" + p.body.rstrip())
    if p.pages:
        print("\n  구조:")
        for node in p.pages:
            indent = "    " + "  " * node.get("depth", 0)
            head = ", ".join(node.get("headings") or []) or "(헤딩 없음)"
            print(f"{indent}[{node['page_id']}] {node.get('title') or '(제목없음)'}"
                  f" — {head}")
    # API 한계를 매번 알린다 — 사용자가 --notes 에 넣은 내용은 어떤 조건으로도 못 찾는다
    print("\n주의: Notion API 는 페이지 본문을 검색하지 못합니다 — "
          "찾아야 하는 내용은 속성에 넣으세요.")
    return 0


def _templates_display_fields(fields: list) -> list:
    """`render.render_rows` 에 넘길 컬럼 이름 — reserved 이름은 실제 row 딕셔너리의
    키(`"<name> (property)"`)로 맞춰준다.

    `render.flatten` 은 대상 DB에 사용자가 만든 `id`/`url` 속성이 있으면 진짜 page
    id/url 과 충돌하지 않도록 그 값을 `"<name> (property)"` 키로 옮겨 보존한다
    (`render._RESERVED_ROW_KEYS`). 여기서 원래 이름 그대로 컬럼을 만들면
    `render_rows` 가 그 이름을 진짜 id 컬럼과 같은 것으로 오인해 지워버리거나
    (`"id"`) 진짜 page url 값을 사용자 속성 칸에 잘못 채워 넣는다(`"url"`) —
    사용자 데이터가 조용히 사라지거나 뒤바뀌는 사고다. `render` 의 사이드카 상수를
    그대로 참조해 두 벌의 이름 목록이 따로 벌어지지 않게 한다.
    """
    return [f"{f} (property)" if f in templates_render._RESERVED_ROW_KEYS else f
            for f in fields]


def _is_prompt_only(p) -> bool:
    """연결된 페이지가 없는 프롬프트 전용(청사진) 템플릿인가 — DB·구조 연산이 없다."""
    return not p.page_id


def _templates_query(args) -> int:
    p = templates_profile.load(args.slug)
    if _is_prompt_only(p):
        print(f"'{p.slug}' 은 프롬프트 전용 템플릿이라 조회할 데이터베이스가 없습니다 "
              "— 등록된 DB 템플릿에 쓰세요.")
        return 2
    store = TemplateStore(NotionSession(), log=print)
    wheres = [templates_filters.parse_where(w) for w in args.where]
    fields = [f.strip() for f in args.fields.split(",") if f.strip()] if args.fields else None
    if args.count:
        print(store.count(p, args.db, wheres=wheres, search=args.search))
        return 0
    sorts = [templates_filters.parse_sort(s) for s in args.sort]
    out = store.query(p, args.db, wheres=wheres, search=args.search, sorts=sorts,
                      limit=args.limit, fetch_all=args.all, fields=fields)
    if args.json:
        print(templates_render.render_json(out["rows"]))
    else:
        cols = _templates_display_fields(out["fields"])
        print(templates_render.render_rows(out["rows"], cols))
    stalled = bool(out.get("stalled", False))
    note = templates_render.truncation_note(capped=out["capped"], cap=out["cap"],
                                            sorted_=out["sorted"], stalled=stalled)
    # 잘림 원인이 안전 상한(`--all`)이 아니라 사용자(혹은 기본값) `--limit` 이면
    # "조건을 좁히세요"는 반대 방향 조언이라 거짓말이 된다 — `--limit`을 올리거나
    # `--all`을 쓰라는 게 맞는 조언이다. `stalled`는 애초에 이 문구를 안 쓰니
    # 손대지 않는다(carry-forward #3).
    if note and out["capped"] and not stalled and not args.all:
        note = note.replace(
            "조건을 좁히세요", "더 큰 --limit 을 쓰거나 --all 을 쓰세요")
    if note:
        # --json 경로에서는 절단 문구를 stdout 에 붙이면 유효 JSON 뒤에 한국어 줄이 이어져
        # json.loads 가 깨진다 — 절단 신호가 가장 필요한 순간(에이전트가 --json 을 읽을 때)에
        # 파싱 불가로 도착하는 셈이다. 신호는 stderr 로 보내 stdout 을 순수 JSON 으로 유지한다.
        print(note, file=sys.stderr if args.json else None)
    return 0


def _templates_write(args) -> int:
    p = templates_profile.load(args.slug)
    if _is_prompt_only(p):
        print(f"'{p.slug}' 은 프롬프트 전용 템플릿이라 데이터베이스 행 연산(추가/수정/"
              "아카이브)이 없습니다 — 에이전트가 이 프롬프트로 새 페이지를 만들어 채웁니다.")
        return 2
    store = TemplateStore(NotionSession(), log=print)
    if args.action == "archive":
        store.archive(p, args.db, args.row_id)
        print(f"Archived: {args.row_id} (휴지통 이동 — Notion 에서 30일 내 복원 가능)")
        return 0
    pairs = [templates_coerce.parse_set(s) for s in args.set]
    if not pairs:
        print("변경할 항목이 없습니다 — --set \"속성=값\" 을 하나 이상 지정하세요")
        return 2
    if args.action == "add":
        row = store.add(p, args.db, pairs, notes=args.notes,
                        allow_new_option=args.allow_new_option)
        print(f"Added: {row['id']}")
        if row["url"]:
            print(row["url"])
        return 0
    store.update(p, args.db, args.row_id, pairs, allow_new_option=args.allow_new_option)
    print(f"Updated: {args.row_id}")
    return 0


def _resolve_page_target(target: str) -> str:
    """`<slug|page-id>` → page_id. URL/ID 면 그대로, 아니면 등록 slug 의 루트 페이지."""
    pid = templates_introspect.extract_page_id(target)
    if pid:
        return pid
    p = templates_profile.load(target)   # 미등록이면 ValueError → exit 2
    if not p.page_id:
        # 프롬프트 전용(청사진)은 읽거나 편집할 루트 페이지가 없다 — GET
        # /blocks//children 으로 가서 혼란스러운 Notion 오류를 내는 대신 명확히
        # 안내한다(최종 리뷰 Important).
        raise ValueError(
            f"'{target}' 은 프롬프트 전용 템플릿이라 연결 페이지가 없습니다 — "
            "읽거나 편집할 page-id 를 직접 지정하세요.")
    return p.page_id


def _templates_read(args) -> int:
    target = _resolve_page_target(args.target)
    store = DocumentStore(NotionSession(), log=print)
    print(store.read(target))
    return 0


def _templates_append(args) -> int:
    md = _text_or_file(args.markdown, args.markdown_file)
    if md is None:
        print("--markdown 또는 --markdown-file 이 필요합니다")
        return 2
    target = _resolve_page_target(args.target)
    DocumentStore(NotionSession(), log=print).append(target, md)
    print(f"추가됨: {target}")
    return 0


def _text_or_file(inline, file_path):
    """인라인 문자열 또는 파일에서 텍스트를 읽는다(`-` = stdin).

    백틱·따옴표·`$()` 가 든 마크다운/프롬프트를 셸 인용 문제 없이 넘기기 위한
    우회구다 — 에이전트가 본문을 파일로 써 `--markdown-file` 로 전달하면 셸이
    backtick 을 명령 치환으로 오인하는 일이 없다. 파일 인자가 없으면 인라인 값을
    그대로 돌려준다(None 이면 None — 미지정 판정은 호출부 몫)."""
    if file_path:
        if file_path == "-":
            return sys.stdin.read()
        try:
            return Path(file_path).read_text(encoding="utf-8")
        except OSError as e:
            # 이 플래그의 주 사용자는 본문을 임시 파일로 쓰는 에이전트다 — 지워진/오타
            # 경로는 예상된 실패이므로 traceback 이 아니라 되물음(exit 2)이어야 한다.
            raise ValueError(f"파일을 읽을 수 없습니다: {file_path} ({e.strerror or e})")
    return inline


def _templates_page(args) -> int:
    store = DocumentStore(NotionSession(), log=print)
    if args.page_action == "add":
        md = _text_or_file(args.markdown, args.markdown_file) or ""
        r = store.add_page(args.parent_page_id, args.title, md)
        print(f"페이지 생성: {r['id']}")
        if r["url"]:
            print(r["url"])
        return 0
    return 2


def _cmd_templates(args) -> int:
    if args.action == "register":
        return _templates_register(args)
    if args.action == "list":
        profiles = templates_profile.load_all()
        if not profiles:
            print("등록된 템플릿이 없습니다 — "
                  "`notionmemory templates register <페이지 URL>` 로 등록하세요")
            return 0
        for p in profiles:
            state = p.health + ("" if p.enabled else ", 비활성")
            kind = "프롬프트 전용" if not p.page_id else f"DB {len(p.databases)}개"
            print(f"{p.slug} [{state}] — {p.summary or p.name} ({kind})")
        return 0
    if args.action == "show":
        return _templates_show(args)
    if args.action == "prompt":
        p = templates_profile.load(args.slug)
        new = _text_or_file(args.set, args.set_file)
        if new is not None:
            p.prompt = new
            templates_profile.save(p)
            print(f"{p.slug} 프롬프트 저장")
            return 0
        print(p.prompt or "(프롬프트 없음 — --set \"<지시문>\" 으로 설정)")
        return 0
    if args.action == "new-prompt":
        slug = templates_introspect.slugify(args.slug)   # 공백·이상문자 → 안전한 파일명(web 생성과 일관)
        if templates_profile.exists(slug):
            print(f"이미 '{slug}' 이름의 템플릿이 있습니다 — 프롬프트만 바꾸려면 "
                  f"`templates prompt {slug} --set ...`")
            return 2
        prompt = _text_or_file(args.prompt, args.prompt_file) or ""
        p = templates_profile.Profile(slug=slug, name=args.name, page_id="",
                                      prompt=prompt)
        templates_profile.save(p)
        print(f"프롬프트 전용 템플릿 생성: {p.slug} — {p.name}\n"
              f"연결된 페이지 없음(청사진) — 에이전트가 쓸 때마다 새 페이지를 만들어 "
              f"이 프롬프트로 채웁니다. 프롬프트 편집: `templates prompt {p.slug} --set ...`")
        return 0
    if args.action == "query":
        return _templates_query(args)
    if args.action in ("add", "update", "archive"):
        return _templates_write(args)
    if args.action == "refresh":
        p = templates_profile.load(args.slug)
        if _is_prompt_only(p):
            print(f"'{p.slug}' 은 프롬프트 전용 템플릿이라 갱신할 연결 구조가 없습니다 "
                  "— 구조는 에이전트가 매번 새로 만듭니다.")
            return 2
        runtime = None
        if args.refresh_notes:
            # 스키마 재조회는 항상 하고, 사용 노트 재생성은 명시했을 때만 — 에이전트
            # 호출이 수십 초 걸리므로 드리프트 복구의 기본 경로를 느리게 만들지 않는다.
            from notionmemory.core.agent_runtime import AgentRuntimeError, build_runtime
            try:
                runtime = build_runtime(Config.load(args.config))
            except AgentRuntimeError as exc:
                print(f"agent 런타임 미감지({exc}) — 스키마만 갱신합니다")
        p = templates_introspect.refresh(NotionSession(), args.slug, runtime=runtime,
                                         log=print)
        print(f"{p.slug} 스키마 갱신 — DB {len(p.databases)}개 [{p.health}]")
        return 0
    if args.action == "read":
        return _templates_read(args)
    if args.action == "append":
        return _templates_append(args)
    if args.action == "page":
        return _templates_page(args)
    if args.action == "image":
        store = DocumentStore(NotionSession(), log=print)
        blk = store.add_image(args.page_id, args.image_path, caption=args.caption)
        if blk is None:
            print("이미지 삽입 실패 — 위 경고를 확인하세요")
            return 1
        print(f"이미지 삽입됨 → {args.page_id}")
        return 0
    if args.action == "remove":
        if not templates_profile.delete(args.slug):
            print(f"등록되지 않은 템플릿입니다: {args.slug}")
            return 2
        print(f"{args.slug} 등록 해제 — Notion 페이지·데이터는 그대로 둡니다")
        return 0
    if args.action == "create-page":
        store = DocumentStore(NotionSession(), log=print)
        # 새 페이지에 제목 헤딩을 앵커로 심는다 — register 는 "블록도 DB도 하위페이지도
        # 없는 진짜 빈 페이지"를 거부하므로(introspect._build), 저작을 시작할 블록이 최소
        # 하나 있어야 등록된다. 실기 검증에서 빈 페이지가 등록 거부로 막힌 것을 수정.
        page = store.add_page(args.parent, args.title, markdown=f"# {args.title}")
        target = page.get("url") or page.get("id", "")
        p = templates_introspect.register(NotionSession(), target,
                                          slug=args.slug, log=print)
        print(f"페이지 생성·등록됨: {p.slug} — {p.name}\n"
              f"이제 `templates block`/`templates image` 로 저작하고 "
              f"`templates prompt {p.slug} --set ...` 로 프롬프트를 붙이세요.")
        return 0
    return 2


def _library_sources(value: str) -> tuple:
    mapping = {"all": ("content", "memory"), "content": ("content",),
               "memory": ("memory",)}
    if value not in mapping:
        raise ValueError(f"--source 는 all/content/memory 중 하나여야 합니다: {value!r}")
    return mapping[value]


def _cmd_library(args) -> int:
    if args.action == "search":
        hits = library_retrieve.search(NotionSession(), Config.load(args.config),
                                       args.query, limit=args.limit,
                                       sources=_library_sources(args.source))
        if not hits:
            print("찾은 것이 없습니다 — 오래됐으면 `notionmemory library refresh`")
            return 0
        for h in hits:
            loc = f" > {h['section']}" if h["section"] else ""
            print(f"{h['source']:8}· [{h['id']}] {h['title']}{loc}")
        return 0
    if args.action == "read":
        # 등록 무관 — 전역 유일 page-id 만으로 본문을 라이브로 읽는다.
        store = DocumentStore(NotionSession(), log=print)
        try:
            print(store.read(args.page_id))
        except PageNotFound:
            # 라이브 404 = 그 페이지가 삭제/공유해제됨(read-repair). 색인에 있으면
            # 지연삭제(자가치유)하고 드리프트를 표시 → SessionStart 가 floor 를 넘겼을
            # 때 `--full` 을 넛지한다. 나머지 안 건드린 유령 항목은 그 스윕이 정리.
            idx = library_index.load()
            pruned = library_index.remove(idx, args.page_id)
            if pruned:
                library_index.mark_dirty(idx)
                library_index.save(idx)
            print(f"library: {args.page_id} 는 더 이상 없습니다(삭제/공유해제) — "
                  + ("색인에서 정리했습니다. " if pruned else "")
                  + "다른 죽은 항목은 `notionmemory library refresh --full` 로 정리하세요")
        return 0
    if args.action == "refresh":
        summary = library_crawl.refresh(NotionSession(), full=args.full, log=print)
        print(f"library: {summary['total']}건 훑어봄 (이번에 {summary['indexed']}건 새로, "
              f"{summary['pruned']}건 정리)")
        return 0
    if args.action == "status":
        idx = library_index.load()
        if not library_index.was_refreshed(idx):
            print("library: 아직 안 훑어봄 — `notionmemory library refresh` 로 훑어두세요")
            return 0
        n = library_index.count(idx)
        if not n:
            print("library: 0건 훑어봄 (공유된 페이지가 없습니다)")
            return 0
        print(f"library: {n}건 훑어봄, 마지막 갱신 {library_index.watermark(idx) or '(미상)'}")
        return 0
    return 2


def _format_status(p: dict, lang: str) -> list[str]:
    """`status.probe()` 결과를 사람이 읽는 줄로 — CLI·에이전트가 그대로 눈으로 확인."""
    lines = []
    n = p["notion"]
    n_state = (tui(lang, "ui.status.notion.connected", "connected") if n["connected"]
              else tui(lang, "ui.status.notion.not_connected", "not connected"))
    lines.append(f"Notion: {n_state} ({n['detail']})" if n["detail"] else f"Notion: {n_state}")
    for key in ("memory",):
        lines.append(_binding_line(key, p[key], lang))
    lib = p["library"]
    lines.append(f"{tui(lang, 'ui.status.library.label', 'library scan')}: {lib['detail']}")
    return lines


def _cmd_status(args) -> int:
    """온보딩 상태 probe — PAT·바인딩·색인 나이를 한 화면에. DB 를 만들지 않는다.
    실패해도 생 traceback 을 내지 않는다(견고성 계약) — `lang` 을 try 밖에서 기본값으로
    잡아둬 Config.load 자체가 실패해도(예: config.yaml 파손) 예외 메시지를 en 으로라도
    사람이 읽게 낸다."""
    lang = "en"
    try:
        cfg = Config.load(args.config)
        lang = i18n.language(cfg)
        p = status_probe.probe(cfg)
        for line in _format_status(p, lang):
            print(line)
        return 0
    except Exception as e:  # noqa: BLE001 — 사람이 읽는 실패 메시지, traceback 금지
        print(tui(lang, "ui.status.probe_failed", "status check failed: {err}", err=str(e)))
        return 1


def _cmd_language(args) -> int:
    """`language <en|ko|zh|ja>` 로 저장 언어를 기록, 인자 없으면 현재값 출력.

    이 값은 일차적으로 **메모리가 적히는 언어**다(consolidate 출력 템플릿). UI 문구
    (대시보드·CLI·훅)는 en/ko 카탈로그만 있어서 zh/ja 를 고르면 영어로 폴백된다 —
    설정 시 그 사실을 한 줄로 알려준다. 온보딩 첫 스텝이 사용자의 선택을 이걸로
    기록한다."""
    from notionmemory.core.config import Config, save_language
    if getattr(args, "lang", None):
        save_language(args.config, args.lang)
        note = ("" if args.lang in i18n.VALID
                else " (memories in this language; UI falls back to English)")
        print(f"language set to {args.lang}{note}")
        return 0
    raw = str(Config.load(args.config).get("language") or "en")
    shown = raw if raw in i18n.OUTPUT_LANGS else i18n.DEFAULT
    print(f"language: {shown}")
    return 0


def _resolve_install_language(args) -> None:
    """install 언어 우선순위: 플래그 > 기존 config > TTY 프롬프트 > 없음.
    헤드리스(비-TTY)는 절대 프롬프트로 막지 않는다 — 리졸버가 en 을 기본으로 한다."""
    import sys
    from notionmemory.core import paths
    from notionmemory.core.config import Config, save_language
    p = str(paths.config_path())
    if getattr(args, "language", None):
        save_language(p, args.language)
        return
    if Config.load(p).get("language") in i18n.OUTPUT_LANGS:
        return
    if not sys.stdin.isatty():
        return
    choice = input(
        "Select memory language / 저장 언어 선택 (UI: English/한국어 only):\n"
        "  1) English\n  2) 한국어\n  3) 中文 (UI: English)\n  4) 日本語 (UI: English)\n> "
    ).strip()
    save_language(p, {"2": "ko", "3": "zh", "4": "ja"}.get(choice, "en"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="notionmemory")
    sub = parser.add_subparsers(dest="cmd", required=True)

    serve = sub.add_parser("serve")
    serve.add_argument("--config", default=DEFAULT_CONFIG)
    serve.add_argument("--port", type=int, default=8765)

    broker = sub.add_parser("broker", help="run the private Keychain-backed Notion request broker")
    broker_sub = broker.add_subparsers(dest="broker_cmd", required=True)
    broker_sub.add_parser("serve")

    run_p = sub.add_parser("run")
    run_p.add_argument("--config", default=DEFAULT_CONFIG)
    run_p.add_argument("rest", nargs=argparse.REMAINDER)

    rem = sub.add_parser("remember")
    rem.add_argument("content")
    rem.add_argument("--type", required=True, choices=list(CAPTURE_TYPES))
    rem.add_argument("--concepts", default="")
    rem.add_argument("--project", default="")
    rem.add_argument("--files", default="")
    rem.add_argument("--source", default="manual", choices=["manual", "claude", "codex", "git"])
    rem.add_argument("--related", default="")
    rem.add_argument("--link", action="append", default=[])
    rem.add_argument("--url", default="")
    rem.add_argument("--supersedes", default="")
    rem.add_argument("--auto", action="store_true")
    rem.add_argument("--config", default=DEFAULT_CONFIG)

    rec = sub.add_parser("recall")
    rec.add_argument("query", nargs="?", default="")
    rec.add_argument("--type", default="")
    rec.add_argument("--project", default="")
    rec.add_argument("--top", type=int, default=0)
    rec.add_argument("--get", default="")
    rec.add_argument("--config", default=DEFAULT_CONFIG)

    fg = sub.add_parser("forget")
    fg.add_argument("mem_id")
    fg.add_argument("--config", default=DEFAULT_CONFIG)

    gc = sub.add_parser("git")
    gc_sub = gc.add_subparsers(dest="action", required=True)
    for act in ("install", "uninstall"):
        p = gc_sub.add_parser(act)
        p.add_argument("path", nargs="?", default=".")
        if act == "uninstall":
            p.add_argument("--all", action="store_true",
                           help="레지스트리의 모든 리포에서 훅 일괄 제거")
        p.add_argument("--config", default=DEFAULT_CONFIG)
    st = gc_sub.add_parser("status")
    st.add_argument("--repair", action="store_true")
    st.add_argument("--config", default=DEFAULT_CONFIG)
    ls = gc_sub.add_parser("list")
    ls.add_argument("--all", action="store_true")
    ak = gc_sub.add_parser("ack")
    ak.add_argument("hashes", nargs="+")
    fl = gc_sub.add_parser("flush")
    fl.add_argument("--repo", default="")
    fl.add_argument("--config", default=DEFAULT_CONFIG)

    mem = sub.add_parser("memory")
    mem_sub = mem.add_subparsers(dest="action", required=True)
    mcn = mem_sub.add_parser("connect")
    mcn_grp = mcn.add_mutually_exclusive_group(required=True)
    mcn_grp.add_argument("--new", action="store_true",
                         help="새 Second Brain DB 를 만들어 바인딩")
    mcn_grp.add_argument("--url", default="", help="기존 Notion DB URL/ID 를 채택")
    mcn.add_argument("--config", default=DEFAULT_CONFIG)
    mcon = mem_sub.add_parser("connection")
    mcon.add_argument("--config", default=DEFAULT_CONFIG)
    mco = mem_sub.add_parser("consolidate")
    mco.add_argument("--project", default="",
                     help="이 프로젝트의 큐 잡만 처리(미지정이면 큐에 있는 전체 프로젝트)")
    mco.add_argument("--auto", action="store_true",
                     help="훅 스폰용 — 락을 잡고, stdout 대신 상태 로그 파일에 기록")
    mco.add_argument("--config", default=DEFAULT_CONFIG)
    mri = mem_sub.add_parser("reindex")
    mri.add_argument("--config", default=DEFAULT_CONFIG)

    tpl = sub.add_parser("templates")
    tpl_sub = tpl.add_subparsers(dest="action", required=True)
    tr = tpl_sub.add_parser("register")
    tr.add_argument("target")
    tr.add_argument("--slug", default="")
    tr.add_argument("--config", default=DEFAULT_CONFIG)
    tpl_sub.add_parser("list")
    ts = tpl_sub.add_parser("show")
    ts.add_argument("slug")
    ts.add_argument("--full", action="store_true")
    tpr = tpl_sub.add_parser("prompt")
    tpr.add_argument("slug")
    tpr.add_argument("--set", default=None)
    tpr.add_argument("--set-file", default="",
                     help="프롬프트를 파일에서 읽는다(`-`=stdin) — 백틱·따옴표 든 내용용")
    tnp = tpl_sub.add_parser("new-prompt")
    tnp.add_argument("slug")
    tnp.add_argument("--name", required=True)
    tnp.add_argument("--prompt", default="")
    tnp.add_argument("--prompt-file", default="",
                     help="프롬프트를 파일에서 읽는다(`-`=stdin)")
    tq = tpl_sub.add_parser("query")
    tq.add_argument("slug")
    tq.add_argument("db")
    tq.add_argument("--where", action="append", default=[])
    tq.add_argument("--search", default="")
    tq.add_argument("--sort", action="append", default=[])
    tq.add_argument("--limit", type=int, default=25)
    tq.add_argument("--all", action="store_true")
    tq.add_argument("--fields", default="")
    tq.add_argument("--count", action="store_true")
    tq.add_argument("--json", action="store_true")
    ta = tpl_sub.add_parser("add")
    ta.add_argument("slug")
    ta.add_argument("db")
    ta.add_argument("--set", action="append", default=[])
    ta.add_argument("--notes", default="")
    ta.add_argument("--allow-new-option", action="store_true")
    tu = tpl_sub.add_parser("update")
    tu.add_argument("slug")
    tu.add_argument("db")
    tu.add_argument("row_id")
    tu.add_argument("--set", action="append", default=[])
    tu.add_argument("--allow-new-option", action="store_true")
    tz = tpl_sub.add_parser("archive")
    tz.add_argument("slug")
    tz.add_argument("db")
    tz.add_argument("row_id")
    tf = tpl_sub.add_parser("refresh")
    tf.add_argument("slug")
    tf.add_argument("--refresh-notes", action="store_true",
                    help="사용 노트(본문)까지 다시 생성 — agent 호출이 껴서 수십 초 걸린다")
    tf.add_argument("--config", default=DEFAULT_CONFIG)
    trd = tpl_sub.add_parser("read")
    trd.add_argument("target")            # <slug|page-id>
    tap = tpl_sub.add_parser("append")
    tap.add_argument("target")
    tap.add_argument("--markdown", default=None)
    tap.add_argument("--markdown-file", default="",
                     help="마크다운을 파일에서 읽는다(`-`=stdin)")
    tp = tpl_sub.add_parser("page")
    tp_sub = tp.add_subparsers(dest="page_action", required=True)
    tpa = tp_sub.add_parser("add")
    tpa.add_argument("parent_page_id")
    tpa.add_argument("--title", required=True)
    tpa.add_argument("--markdown", default="")
    tpa.add_argument("--markdown-file", default="",
                     help="본문 마크다운을 파일에서 읽는다(`-`=stdin)")
    tim = tpl_sub.add_parser("image")
    tim.add_argument("page_id")
    tim.add_argument("image_path")
    tim.add_argument("--caption", default="")
    tm = tpl_sub.add_parser("remove")
    tm.add_argument("slug")
    tcp = tpl_sub.add_parser("create-page")
    tcp.add_argument("--parent", required=True)
    tcp.add_argument("--title", required=True)
    tcp.add_argument("--slug", default="")

    lib = sub.add_parser("library")
    lib_sub = lib.add_subparsers(dest="action", required=True)
    ls = lib_sub.add_parser("search")
    ls.add_argument("query")
    ls.add_argument("--limit", type=int, default=25)
    ls.add_argument("--source", default="all")      # all/content/memory
    ls.add_argument("--config", default=DEFAULT_CONFIG)
    lr = lib_sub.add_parser("read")
    lr.add_argument("page_id")
    lf = lib_sub.add_parser("refresh")
    lf.add_argument("--full", action="store_true")
    lf.add_argument("--config", default=DEFAULT_CONFIG)
    lib_sub.add_parser("status")

    stc = sub.add_parser("status")
    stc.add_argument("--config", default=DEFAULT_CONFIG)

    lang_p = sub.add_parser("language")
    lang_p.add_argument("lang", nargs="?", choices=list(i18n.OUTPUT_LANGS))
    lang_p.add_argument("--config", default=DEFAULT_CONFIG)

    hook = sub.add_parser("hook")
    hook.add_argument("name", choices=["session-start", "save-reminder", "session-stop",
                                       "user-prompt", "session-end"])
    hook.add_argument("--harness", choices=["claude", "codex"], default="claude",
                      help="호출한 하네스 — 훅 stdout 형태가 이벤트별로 달라서 필요"
                           "(기본값 claude, 안 주면 지금까지 동작 그대로)")

    inst = sub.add_parser("install")
    inst.add_argument("--claude", action="store_true")
    inst.add_argument("--codex", action="store_true")
    inst.add_argument("--trust-codex-hooks", action="store_true",
                      help="Codex config.toml 에 우리 훅의 trusted_hash 를 기록한다")
    inst.add_argument("--skip-skills", action="store_true",
                      help="스킬 미러를 생략하고 훅/신뢰만 설치한다 "
                           "(스킬을 플러그인으로 배포하는 Codex 사용자용)")
    inst.add_argument("--language", choices=list(i18n.OUTPUT_LANGS),
                      help="저장(메모리) 언어를 config 에 기록한다 (기본 en). "
                           "UI 문구는 en/ko 만 — zh/ja 는 UI 영어 폴백")

    td = sub.add_parser("teardown")
    td.add_argument("--claude", action="store_true")
    td.add_argument("--codex", action="store_true")
    td.add_argument("--purge-config", action="store_true")
    td.add_argument("--purge-secrets", action="store_true")
    td.add_argument("--yes", action="store_true")
    td.add_argument("--dry-run", action="store_true")

    args = parser.parse_args(argv)
    if args.cmd == "serve":
        build_app(args.config).run(port=args.port)
        return 0
    if args.cmd == "broker":
        from notionmemory.core import notion_broker
        notion_broker.serve_forever()
        return 0
    if args.cmd == "run":
        return _cmd_run(args.rest, args.config)
    if args.cmd in ("remember", "recall", "forget"):
        handler = {"remember": _cmd_remember, "recall": _cmd_recall,
                   "forget": _cmd_forget}[args.cmd]
        try:
            return handler(args)
        except (RuntimeError, ValueError) as e:
            print(str(e))
            return 1
        except requests.RequestException as e:
            print(f"Notion API 요청 실패: {e}")
            return 1
    if args.cmd == "git":
        try:
            return _cmd_git(args)
        except (RuntimeError, ValueError) as e:
            print(str(e))
            return 1
        except requests.RequestException as e:
            print(f"Notion API 요청 실패: {e}")
            return 1
    if args.cmd == "memory":
        try:
            return _cmd_memory(args)
        except (NotASecondBrainError, ValueError, RuntimeError) as e:
            print(str(e))
            return 2
        except requests.RequestException as e:
            print(f"Notion API 요청 실패: {e}")
            return 1
    if args.cmd == "templates":
        try:
            return _cmd_templates(args)
        # `ProfileGone` 은 `RuntimeError` 의 하위 클래스다 — 재등록 안내를 담은
        # 예외라 일반 `RuntimeError` 보다 반드시 먼저 잡는다. 순서가 바뀌면 이 분기가
        # 죽은 코드가 되고(파이썬은 첫 매칭 except 만 탄다) 재등록 안내가 스스로는
        # 절대 못 도달하는 코드로 조용히 묻힌다(carry-forward #1).
        except ProfileGone as e:
            print(str(e))
            return 1
        except ValueError as e:
            print(str(e))
            return 2
        except RuntimeError as e:
            print(str(e))
            return 1
        except requests.RequestException as e:
            print(f"Notion API 요청 실패: {e}")
            return 1
    if args.cmd == "library":
        try:
            return _cmd_library(args)
        except ValueError as e:
            print(str(e))
            return 2
        except RuntimeError as e:
            print(str(e))
            return 1
        except requests.RequestException as e:
            print(f"Notion API 요청 실패: {e}")
            return 1
    if args.cmd == "status":
        return _cmd_status(args)
    if args.cmd == "language":
        return _cmd_language(args)
    if args.cmd == "hook":
        from notionmemory.hooks import (save_reminder, session_end, session_start,
                                        session_stop, user_prompt)
        return {"session-start": session_start.main,
                "save-reminder": save_reminder.main,
                "session-stop": session_stop.main,
                "user-prompt": user_prompt.main,
                "session-end": session_end.main}[args.name](harness=args.harness)
    if args.cmd == "install":
        from notionmemory.core.install import runner
        _resolve_install_language(args)
        targets = [t for t, on in (("claude", args.claude), ("codex", args.codex)) if on]
        if not targets:
            targets = ["claude", "codex"]     # 무플래그 = 가능한 전부
        if "codex" in targets and args.trust_codex_hooks:
            print("주의: Codex 는 승인되지 않은 훅을 실행하지 않습니다. "
                  "--trust-codex-hooks 는 이 승인을 대신 기록합니다 "
                  "(우리가 설치한 항목만, 다른 훅은 건드리지 않습니다).")
        try:
            for line in runner.install(targets, trust_codex=args.trust_codex_hooks,
                                       skip_skills=args.skip_skills):
                print(line)
        except RuntimeError as e:
            print(str(e))
            return 1
        return 0
    if args.cmd == "teardown":
        from notionmemory.core.install import teardown
        targets = [t for t, on in (("claude", args.claude), ("codex", args.codex)) if on]
        if not targets:
            targets = ["claude", "codex"]
        # 미리보기와 실제 실행이 같은 결과를 서술해야 확인 게이트를 신뢰할 수
        # 있다 — purge 플래그를 두 미리보기 호출 모두에 반드시 넘긴다(리뷰 Important).
        if args.dry_run:
            for line in teardown.run(targets, purge_config=args.purge_config,
                                     purge_secrets=args.purge_secrets, dry_run=True):
                print(line)
            return 0
        if not args.yes:
            for line in teardown.run(targets, purge_config=args.purge_config,
                                     purge_secrets=args.purge_secrets, dry_run=True):
                print(line)
            try:
                answer = input("위 항목을 제거합니다. 계속할까요? [y/N] ").strip().lower()
            except EOFError:
                print("입력을 받을 수 없어 취소합니다.")
                return 1
            if answer != "y":
                print("취소했습니다.")
                return 1
        for line in teardown.run(targets, purge_config=args.purge_config,
                                 purge_secrets=args.purge_secrets):
            print(line)
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
