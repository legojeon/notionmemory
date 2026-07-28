"""calendar 핵심 — 일정 검증·타임존·요약(순수 함수) + CalendarStore(add/list/update/cancel).

입력 형식은 결정적(`YYYY-MM-DD[ HH:MM]`)만 받는다 — 상대 표현("내일 3시") 해석은
에이전트 몫(SKILL.md 규약). 시각이 없으면 자동 종일 일정.
"""
from __future__ import annotations

import os
import secrets
import string
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from notionmemory.core.config import Config, SkillMeta
from notionmemory.skills.calendar.notion_db import CalendarDB, rt

_BASE36 = string.digits + string.ascii_lowercase


def new_event_id(now_ms: int | None = None, rand: str | None = None) -> str:
    ts = int(time.time() * 1000) if now_ms is None else now_ms
    digits = ""
    while ts:
        ts, d = divmod(ts, 36)
        digits = _BASE36[d] + digits
    rand = rand or "".join(secrets.choice(_BASE36) for _ in range(12))
    return f"evt_{digits or '0'}_{rand}"


def parse_when(raw: str) -> tuple[str, bool]:
    """`YYYY-MM-DD`(종일) 또는 `YYYY-MM-DD HH:MM`(T 허용) → (정규화 값, all_day)."""
    s = (raw or "").strip().replace("T", " ")
    try:
        if len(s) == 10:
            datetime.strptime(s, "%Y-%m-%d")
            return s, True
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M")
        return dt.strftime("%Y-%m-%dT%H:%M:%S"), False
    except ValueError:
        raise ValueError(f"날짜 형식이 올바르지 않습니다: {raw!r} "
                         "(YYYY-MM-DD 또는 YYYY-MM-DD HH:MM)")


def local_timezone(localtime_path: str = "/etc/localtime") -> str | None:
    """IANA 타임존 이름 — /etc/localtime 심링크 → TZ 환경변수 → None."""
    candidates: list[str] = []
    try:
        target = os.readlink(localtime_path)
        if "zoneinfo/" in target:
            candidates.append(target.split("zoneinfo/", 1)[1])
    except OSError:
        pass
    candidates.append(os.environ.get("TZ", ""))
    for name in candidates:
        if not name:
            continue
        try:
            ZoneInfo(name)
            return name
        except (KeyError, ValueError):
            continue
    return None


def _utc_offset() -> str:
    raw = datetime.now().astimezone().strftime("%z")  # 예: +0900
    return raw[:3] + ":" + raw[3:]


def date_payload(start: str, end: str, all_day: bool, tz_name: str | None,
                 offset: str | None = None) -> dict:
    """Notion date 속성 값. timed는 IANA time_zone 동반(그때 오프셋 미포함 규약),
    IANA를 못 얻으면 로컬 UTC 오프셋 ISO 폴백(Notion이 오프셋 해석)."""
    suffix = ""
    if not all_day and not tz_name:
        if offset is None:
            offset = _utc_offset()
        suffix = offset
    payload = {"start": start + suffix}
    if not all_day and tz_name:
        payload["time_zone"] = tz_name
    if end:
        payload["end"] = end + suffix
    return payload


def _plain(rich) -> str:
    return "".join(i.get("plain_text", "") for i in rich or [])


def event_summary(page: dict) -> dict:
    props = page.get("properties", {})
    d = props.get("Date", {}).get("date") or {}
    return {
        "event_id": _plain(props.get("Event ID", {}).get("rich_text")),
        "title": _plain(props.get("Title", {}).get("title")),
        "start": d.get("start") or "",
        "end": d.get("end") or "",
        "status": (props.get("Status", {}).get("select") or {}).get("name", ""),
        "location": _plain(props.get("Location", {}).get("rich_text")),
        "link": props.get("Link", {}).get("url") or "",
        "page_id": page.get("id", ""),
        "url": page.get("url", ""),
    }


def build_range_filter(date_from: str, date_to: str) -> dict:
    # Status는 스키마에 시드되어 있어 select 필터가 안전하다(memory build_filter 주석 참조)
    return {"and": [
        {"property": "Date", "date": {"on_or_after": date_from}},
        {"property": "Date", "date": {"on_or_before": date_to}},
        {"property": "Status", "select": {"does_not_equal": "Canceled"}},
    ]}


def _fmt_when(start: str, end: str) -> str:
    def fmt(v: str) -> str:
        return v[:16].replace("T", " ") if len(v) > 10 else v
    if not end:
        return fmt(start)
    s, e = fmt(start), fmt(end)
    if len(start) > 10 and len(end) > 10 and s[:10] == e[:10]:
        return f"{s}–{e[11:]}"  # 같은 날 timed → "2026-07-21 14:00–15:00"
    return f"{s}–{e}"


def format_event_line(s: dict) -> str:
    """`evt_x · 2026-07-21 14:00–15:00 · 제목 @장소 [Scheduled] (링크)`"""
    title = s["title"] + (f" @{s['location']}" if s["location"] else "")
    line = " · ".join([s["event_id"], _fmt_when(s["start"], s["end"]), title])
    line += f" [{s['status']}]"
    if s["link"]:
        line += f" ({s['link']})"
    return line


def _raw_from_notion(value: str, all_day: bool) -> str:
    """Notion date.start/end("2026-07-21T14:00:00.000+09:00") → parse_when 입력형."""
    return value[:10] if all_day else value.replace("T", " ")[:16]


class CalendarStore:
    def __init__(self, session, config: Config, log=None):
        self.db = CalendarDB(session, log=log)
        self.config = config
        self.meta = SkillMeta(config, "calendar")

    def _data_source(self, *, create: bool = True) -> str:
        opts = self.config.skill_options("calendar")
        return self.db.ensure(str(opts.get("parent_page_id") or ""), self.meta,
                              create=create)

    @staticmethod
    def _validated_range(start_raw: str, end_raw: str) -> tuple[str, str, bool]:
        s_val, s_allday = parse_when(start_raw)
        if not end_raw:
            return s_val, "", s_allday
        e_val, e_allday = parse_when(end_raw)
        if e_allday != s_allday:
            raise ValueError("start와 end는 형식이 같아야 합니다 "
                             "(둘 다 날짜만 또는 둘 다 시각 포함)")
        if e_val < s_val:
            raise ValueError(f"end가 start보다 빠릅니다: {end_raw!r} < {start_raw!r}")
        return s_val, e_val, s_allday

    def check_write_target(self, title: str = "", start: str = "", *,
                           force_builtin: bool = False) -> None:
        """쓰기 대상 게이트. `add` 진입 첫 줄에서 부른다 — Notion 을 건드리기 전이다."""
        from notionmemory.skills.calendar import routing
        from notionmemory.skills.templates import profile as tprofile
        raw = str(self.config.skill_options("calendar").get(routing.OPTION) or "")
        parsed = routing.parse_target(raw)
        if parsed is not None:
            slug, db_key = parsed
            try:
                routing.validate_target(raw)
            except ValueError as exc:
                raise ValueError(
                    f"{exc} — `notionmemory calendar target calendar` 로 내장 DB 로 "
                    "되돌리거나 올바른 대상을 지정하세요")
            raise routing.blocked(slug, db_key, title, start)
        if force_builtin or raw == routing.BUILTIN:
            return
        candidates = routing.overlapping(tprofile.load_all())
        if candidates:
            raise routing.ambiguous(candidates)

    def add(self, title: str, *, start: str, end: str = "", location: str = "",
            link: str = "", notes: str = "", source: str = "manual",
            force_builtin: bool = False) -> dict:
        self.check_write_target(title, start, force_builtin=force_builtin)
        s_val, e_val, all_day = self._validated_range(start, end)
        ds = self._data_source()
        event_id = new_event_id()
        payload = date_payload(s_val, e_val, all_day, local_timezone())
        props = {
            "Title": {"title": rt(title)},
            "Event ID": {"rich_text": rt(event_id)},
            "Date": {"date": payload},
            "Status": {"select": {"name": "Scheduled"}},
            "Source": {"select": {"name": source}},
        }
        if location:
            props["Location"] = {"rich_text": rt(location)}
        if link:
            props["Link"] = {"url": link}
        page = self.db.create_page(ds, props, notes)
        return {"event_id": event_id, "title": title, "start": payload["start"],
                "end": payload.get("end", ""), "status": "Scheduled",
                "location": location, "link": link,
                "page_id": page.get("id", ""), "url": page.get("url", "")}

    def list_events(self, *, date_from: str = "", date_to: str = "", days: int = 7,
                    today: str = "") -> list[dict]:
        ds = self._data_source(create=False)
        if not ds:
            return []          # 아직 Calendar DB 가 없다 — 조회가 만들지는 않는다
        start_raw = date_from or today or date.today().isoformat()
        s_val, s_allday = parse_when(start_raw)
        if not s_allday:
            s_val += _utc_offset()
        if date_to:
            e_val, e_allday = parse_when(date_to)
            if not e_allday:
                e_val += _utc_offset()
        else:
            e_val = (date.fromisoformat(s_val[:10]) + timedelta(days=days)).isoformat()
        pages = self.db.query(ds, build_range_filter(s_val, e_val))
        summaries = [event_summary(p) for p in pages]
        summaries.sort(key=lambda s: s["start"])
        return summaries

    def update(self, event_id: str, *, title=None, start=None, end=None,
               location=None, link=None, status=None) -> dict | None:
        ds = self._data_source()
        page = self.db.find_page_by_event_id(ds, event_id)
        if page is None:
            return None
        cur = event_summary(page)
        props: dict = {}
        warning = ""
        if title is not None:
            props["Title"] = {"title": rt(title)}
        if location is not None:
            props["Location"] = {"rich_text": rt(location)}
        if link is not None:
            props["Link"] = {"url": link or None}  # `--link ""` → 링크 제거
        if status is not None:
            props["Status"] = {"select": {"name": status}}
        if start is not None or end is not None:
            cur_allday = "T" not in cur["start"]
            s_raw = start if start is not None else _raw_from_notion(cur["start"], cur_allday)
            e_raw = end if end is not None else (
                _raw_from_notion(cur["end"], cur_allday) if cur["end"] else "")
            try:
                s_val, e_val, all_day = self._validated_range(s_raw, e_raw)
            except ValueError:
                if end is not None:
                    raise  # 사용자가 준 end가 문제 — 그대로 검증 오류
                # 기존 end가 새 start와 안 맞으면(형식 전환·역전) end를 버리고 경고
                s_val, e_val, all_day = self._validated_range(s_raw, "")
                warning = "새 start와 기존 end가 맞지 않아 end를 제거했습니다"
            props["Date"] = {"date": date_payload(s_val, e_val, all_day, local_timezone())}
        self.db.update_page(page["id"], props)
        return {"event_id": event_id, "warning": warning}

    def cancel(self, event_id: str) -> bool:
        page = self.db.find_page_by_event_id(self._data_source(), event_id)
        if page is None:
            return False
        # Status 기록 + 휴지통 이동을 한 PATCH로 — 살아있는 항목만 보여주는
        # Notion Calendar 앱에서도 함께 사라진다 (30일 내 휴지통 복원 가능)
        self.db.trash_page(page["id"], {"Status": {"select": {"name": "Canceled"}}})
        return True
