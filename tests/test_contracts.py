"""Test kontrak antar-modul (milik bersama)."""
from core.schemas import AnalysisResult, Post
from processing.deduplicate import dedup_key
from processing.normalize import clean


def _post(text: str, **kw) -> Post:
    base = {"platform": "threads", "text": text}
    base.update(kw)
    return Post(**base)


def test_clean_trims_and_drops_empty():
    p = _post("  halo   malang  ")
    assert clean(p).text == "halo malang"
    p2 = _post("placeholder")
    # kosongkan setelah validasi lolos — clean() harus return None
    p2.text = "   "
    assert clean(p2) is None


def test_dedup_key_priority():
    p1 = _post("banjir sawojajar", platform_post_id="123")
    assert dedup_key(p1) == "threads:123"
    p2 = _post("banjir sawojajar", url="https://x/y")
    assert dedup_key(p2).startswith("threads:url:")
    p3 = _post("Banjir Sawojajar")
    p4 = _post("  banjir   sawojajar ")
    assert dedup_key(p3) == dedup_key(p4)


def test_prd_four_cases_heuristic():
    from ai.relevance import analyze

    cases = [
        ("Sawojajar banjir maneh sam, banyune wes nutup dalan", True),
        ("Kos murah dekat Dinoyo, hubungi WA", False),
        ("Macet parah arah Suhat dari tadi", True),
        ("Promo makanan Batu diskon 30 persen", False),
    ]
    for text, expected in cases:
        r = analyze(_post(text))
        assert isinstance(r, AnalysisResult)
        assert r.is_relevant is expected, f"{text} -> {r}"
