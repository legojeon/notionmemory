"""library 색인 — 로컬 파생 힌트(제목·헤딩만) + 어휘 검색."""
import pytest

from notionmemory.skills.library import index as I


@pytest.fixture(autouse=True)
def state_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def test_path_is_under_state_dir(state_home):
    from notionmemory.core import paths
    assert I.index_path().is_relative_to(paths.state_dir())
    assert I.index_path().name == "index.json"


def test_load_empty_when_absent():
    idx = I.load()
    assert idx == {"last_refreshed": "", "last_run": "", "last_full_run": "",
                   "dirty_since_full": False, "pages": {}}


def test_upsert_save_load_round_trip():
    idx = I.load()
    I.upsert(idx, "pg1", title="논문정리", headings=["요약", "핵심"],
             url="https://n/pg1", last_edited_time="2026-07-24T10:00:00.000Z")
    I.save(idx)
    got = I.load()
    assert got["pages"]["pg1"]["title"] == "논문정리"
    assert got["pages"]["pg1"]["headings"] == ["요약", "핵심"]


def test_upsert_overwrites_same_page():
    idx = I.load()
    I.upsert(idx, "pg1", title="옛 제목", headings=[], url="u", last_edited_time="t1")
    I.upsert(idx, "pg1", title="새 제목", headings=["a"], url="u", last_edited_time="t2")
    assert idx["pages"]["pg1"]["title"] == "새 제목"
    assert len(idx["pages"]) == 1


def test_remove():
    idx = I.load()
    I.upsert(idx, "pg1", title="x", headings=[], url="u", last_edited_time="t")
    assert I.remove(idx, "pg1") is True
    assert I.remove(idx, "pg1") is False
    assert idx["pages"] == {}


def test_tokenize_splits_on_non_word_and_lowercases():
    assert I.tokenize("Kubernetes 운영, k8s!") == ["kubernetes", "운영", "k8s"]


def test_search_scores_title_higher_than_headings():
    idx = I.load()
    I.upsert(idx, "pg1", title="쿠버네티스 운영 가이드", headings=["설치"],
             url="u1", last_edited_time="t")
    I.upsert(idx, "pg2", title="일반 노트", headings=["쿠버네티스 트러블슈팅"],
             url="u2", last_edited_time="t")
    hits = I.search(idx, "쿠버네티스", limit=25)
    assert [h["page_id"] for h in hits] == ["pg1", "pg2"]     # 제목(3) > 헤딩(1)
    assert hits[0]["score"] > hits[1]["score"]


def test_was_refreshed_distinguishes_never_run_from_empty_workspace():
    idx = I.load()
    assert I.was_refreshed(idx) is False          # 갓 만든 빈 색인 = 미갱신
    idx["last_run"] = "2026-07-25T00:00:00+00:00"  # refresh 가 돌면 찍히는 마커
    assert I.was_refreshed(idx) is True            # 공유 페이지 0개여도 '한 번 돌았다'


def test_was_refreshed_true_when_pages_present_even_without_marker():
    idx = I.load()                                 # 구버전 색인 하위호환(last_run 필드 없음)
    I.upsert(idx, "pg1", title="x", headings=[], url="u", last_edited_time="t")
    assert I.was_refreshed(idx) is True


def test_ascii_token_matches_on_word_boundary_not_substring():
    """ASCII 토큰은 단어 경계로만 — 짧은 토큰이 긴 단어 안에 걸리는 오탐을 막는다
    (실측: 'ray'→'array', 'dark'→'darkfw'). 진짜 단어 매칭은 유지된다."""
    idx = I.load()
    I.upsert(idx, "real", title="Future developments in gamma-ray astronomy",
             headings=[], url="u", last_edited_time="t")
    I.upsert(idx, "false", title="An S-band phased array feed for radio astronomy",
             headings=[], url="u", last_edited_time="t")
    I.upsert(idx, "darkfw", title="darkfw_enc_disable", headings=[], url="u",
             last_edited_time="t")
    ray = [h["page_id"] for h in I.search(idx, "ray")]
    assert ray == ["real"]                     # 'array' 안의 ray 는 안 걸린다
    assert I.search(idx, "dark") == []         # 'darkfw' 안의 dark 는 안 걸린다


def test_korean_token_still_matches_as_substring():
    """한글은 조사·어미가 공백 없이 붙으므로 부분 매칭을 유지해야 회수가 안 깎인다."""
    idx = I.load()
    I.upsert(idx, "pg1", title="쿠버네티스의 운영", headings=[], url="u", last_edited_time="t")
    assert [h["page_id"] for h in I.search(idx, "쿠버네티스")] == ["pg1"]


def test_search_returns_pointers_not_bodies():
    idx = I.load()
    I.upsert(idx, "pg1", title="쿠버네티스", headings=["요약"], url="u", last_edited_time="t")
    hit = I.search(idx, "쿠버네티스")[0]
    assert set(hit) == {"page_id", "title", "headings", "url", "score"}


def test_search_zero_matches_returns_empty_not_fallback():
    idx = I.load()
    I.upsert(idx, "pg1", title="고양이", headings=[], url="u", last_edited_time="t")
    assert I.search(idx, "쿠버네티스") == []      # content 검색은 무매칭=무결과(fallback 없음)


def test_search_respects_limit():
    idx = I.load()
    for i in range(30):
        I.upsert(idx, f"pg{i}", title="쿠버네티스", headings=[], url="u",
                 last_edited_time="t")
    assert len(I.search(idx, "쿠버네티스", limit=10)) == 10


def test_count_and_watermark():
    idx = I.load()
    I.upsert(idx, "pg1", title="x", headings=[], url="u", last_edited_time="t")
    idx["last_refreshed"] = "2026-07-24T10:00:00.000Z"
    assert I.count(idx) == 1
    assert I.watermark(idx) == "2026-07-24T10:00:00.000Z"
