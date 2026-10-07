"""Test insight: cluster_rule + heuristic analyze_event + draft_report (tanpa LLM)."""
from datetime import datetime, timezone

from ai.insight import draft_report, heuristic_insight
from core.schemas import EventDraft
from graph.insight_graph import cluster_rule


def _p(**kw):
    base = {
        "id": "x",
        "text": "teks",
        "url": "https://threads.com/@a/post/1",
        "author": "a",
        "published_at": datetime(2026, 10, 6, 5, 0, tzinfo=timezone.utc),
        "location": None,
        "issue_hint": None,
        "kind": "root",
        "parent_post_id": None,
    }
    base.update(kw)
    return base


def test_cluster_groups_by_location_hint_day():
    posts = [
        _p(id="a1", location="Suhat", issue_hint="listrik"),
        _p(id="a2", location="Suhat", issue_hint="listrik", author="warga", kind="reply", parent_post_id="a1"),
        _p(id="b1", location="Tajinan", issue_hint="kebakaran"),
    ]
    drafts = cluster_rule(posts)
    assert len(drafts) == 2
    suhat = next(d for d in drafts if d.location == "Suhat")
    assert set(suhat.post_ids) == {"a1", "a2"}
    assert suhat.key.startswith("Suhat|listrik|2026-10-06|")


def test_cluster_separates_different_day():
    d1 = datetime(2026, 10, 6, 5, 0, tzinfo=timezone.utc)
    d2 = datetime(2026, 10, 5, 5, 0, tzinfo=timezone.utc)
    drafts = cluster_rule(
        [_p(id="a1", location="Suhat", issue_hint="listrik", published_at=d1),
         _p(id="b1", location="Suhat", issue_hint="listrik", published_at=d2)]
    )
    assert len(drafts) == 2


def test_cluster_caps_sample_texts_at_five():
    posts = [_p(id=f"p{i}", location="Suhat", issue_hint="listrik", text=f"teks {i}") for i in range(8)]
    drafts = cluster_rule(posts)
    assert len(drafts[0].post_ids) == 8
    assert len(drafts[0].sample_texts) == 5


def test_heuristic_issue_class_from_hint_and_urgency_from_count():
    ev = EventDraft(key="k", location="Suhat", issue_hint="listrik", post_ids=["a", "b", "c", "d"])
    ins = heuristic_insight(ev)
    assert ins.issue_class == "listrik_dan_air"
    assert ins.urgency == 2  # min(5, 1 + 4//3)

    many = EventDraft(key="k", location="Suhat", issue_hint="banjir", post_ids=list("abcdefghij"))
    assert heuristic_insight(many).urgency == 4


def test_heuristic_class_falls_back_to_text_then_lainnya():
    ev = EventDraft(key="k", issue_hint=None, post_ids=["a"], sample_texts=["Genangan air di gang"])
    assert heuristic_insight(ev).issue_class == "banjir"
    ev2 = EventDraft(key="k", issue_hint=None, post_ids=["a"], sample_texts=["Promo kopi diskon"])
    assert heuristic_insight(ev2).issue_class == "lainnya"


def test_analyze_event_never_touches_llm_when_provider_heuristic(monkeypatch):
    from ai import insight

    monkeypatch.setenv("AI_PROVIDER", "heuristic")
    ev = EventDraft(key="k", location="Suhat", issue_hint="listrik", post_ids=["a"])
    assert insight.analyze_event(ev).issue_class == "listrik_dan_air"
    assert insight.insight_model_version() == insight.HEURISTIC_VERSION


def test_draft_report_contains_event_and_sources():
    events = [
        {
            "key": "Suhat|listrik|2026-10-06",
            "location": "Suhat",
            "issue_class": "listrik_dan_air",
            "urgency": 3,
            "rationale": "listrik mati sejak pagi",
            "post_ids": ["a"],
            "sources": [
                {
                    "url": "https://threads.com/@a/post/1",
                    "text": "listrik mati",
                    "author": "warga",
                    "kind": "reply",
                }
            ],
        }
    ]
    md = draft_report(events, "2026-10-06", window_date="2026-10-06")
    assert "## LAPORAN MONITORING ISU MEDIA SOSIAL" in md
    assert "**Periode: 6 Oktober 2026**" in md
    assert "### 🟠 Listrik & Air Bersih di Suhat" in md  # judul heuristic bila narasi kosong
    assert "**Kategori:** Listrik & Air Bersih" in md
    assert "**Lokasi:** Suhat" in md
    assert "**Ringkasan Isu**" in md and "listrik mati sejak pagi" in md
    assert "**Eksposur Media Sosial**" in md
    assert "**Rekomendasi**" in md
    assert "**Status:** 🟡 Monitor" in md
    assert "(balasan)" in md
    assert "https://threads.com/@a/post/1" in md


def test_draft_report_uses_llm_narrative_when_present():
    events = [
        {
            "key": "k",
            "location": "Jalan Veteran, Kota Malang",
            "issue_class": "macet_lalu_lintas",
            "urgency": 4,
            "rationale": "ada korban jiwa",
            "post_ids": ["a", "b"],
            "sources": [
                {"url": "https://ig/1", "text": "x", "author": "malangraya_info", "platform": "instagram",
                 "published_at": "2026-10-06T01:00:00+00:00", "kind": "root"},
                {"url": "https://ig/2", "text": "y", "author": "infomalangan", "platform": "instagram",
                 "published_at": "2026-10-06T02:00:00+00:00", "kind": "root"},
            ],
            "narrative": {
                "title": "Kecelakaan Lalu Lintas di Jalan Veteran",
                "occurred_at": "5 Oktober 2026, sekitar pukul 23.50 WIB",
                "summary": "Terjadi kecelakaan antara sepeda motor dan truk.",
                "exposure": "Isu terpantau pada **2 unggahan** Instagram dari 2 akun (@infomalangan, @malangraya_info), pada 6 Oktober 2026.",
                "sentiment": "negatif",
                "attention_level": "sedang",
                "issue_character": "Insidental / kejadian lokal",
                "potential": "Dapat meningkatkan perhatian pada keselamatan lalu lintas.",
                "recommendation": "Pantau perkembangan komentar.",
                "status": "monitor",
            },
        }
    ]
    md = draft_report(events, "2026-10-06", window_date="2026-10-06")
    assert "### 🔴 Kecelakaan Lalu Lintas di Jalan Veteran" in md
    assert "**Waktu kejadian:** 5 Oktober 2026, sekitar pukul 23.50 WIB" in md
    assert "**Sentimen:** 🔴 Negatif" in md
    assert "**Level perhatian:** 🟠 Sedang" in md
    assert "Pantau perkembangan komentar." in md


def test_exposure_text_counts_accounts_and_replies():
    from ai.insight import exposure_text

    sources = [
        {"author": "malangraya_info", "platform": "instagram", "published_at": "2026-10-06T01:00:00+00:00", "kind": "root"},
        {"author": "infomalangan", "platform": "instagram", "published_at": "2026-10-05T20:00:00+00:00", "kind": "root"},
        {"author": "warga", "platform": "threads", "published_at": "2026-10-06T03:00:00+00:00", "kind": "reply"},
    ]
    text = exposure_text(sources)
    assert "**2 unggahan** Instagram dari 2 akun (@infomalangan, @malangraya_info)" in text
    assert "**1 balasan/komentar warga** di Threads" in text
    assert "pada 6 Oktober 2026" in text  # 05T20:00Z = 6 Okt WIB


def test_format_period_id():
    from ai.insight import format_period_id

    assert format_period_id(["2026-10-06"]) == "6 Oktober 2026"
    assert format_period_id(["2026-10-05", "2026-10-06"]) == "5–6 Oktober 2026"
    assert format_period_id(["2026-09-30", "2026-10-01"]) == "30 September 2026 – 1 Oktober 2026"


def test_merge_similar_joins_same_accident_across_location_spellings():
    veteran = (
        "Kecelakaan lalu lintas di Jalan Veteran depan Asrama Soka melibatkan sepeda motor "
        "dan truk, penumpang meninggal dunia"
    )
    posts = [
        _p(id="a", location="Klojen", issue_hint="kecelakaan lalu lintas", text=veteran),
        _p(id="b", location="Jalan Veteran, Malang", issue_hint="kriminalitas/kecelakaan",
           text="Laka di Jalan Veteran: sepeda motor CBR vs truk, penumpang 19 tahun meninggal dunia"),
        _p(id="c", location="Tajinan", issue_hint="kebakaran", text="Kebakaran lahan tebu di Tajinan 3 hektare"),
        _p(id="d", location="Klojen", issue_hint="pohon tumbang", text="Pohon tumbang menimpa mobil di Klojen"),
    ]
    drafts = cluster_rule(posts)
    keys = {tuple(sorted(d.post_ids)) for d in drafts}
    assert ("a", "b") in keys          # satu kecelakaan → satu event
    assert ("c",) in keys and ("d",) in keys  # kelas lain tidak ikut tergabung
    acc = next(d for d in drafts if "a" in d.post_ids)
    assert acc.location == "Klojen"    # lokasi terpendek (nama kecamatan) dipertahankan


def test_merge_similar_keeps_distinct_events_same_class():
    posts = [
        _p(id="a", location="Suhat", issue_hint="macet", text="Macet parah arah Suhat karena proyek drainase"),
        _p(id="b", location="Dinoyo", issue_hint="macet", text="Antrean panjang di Dinoyo imbas pasar tumpah pagi ini"),
    ]
    assert len(cluster_rule(posts)) == 2


def test_same_generic_hint_broad_location_stays_separate():
    """Dua berita kebijakan Pemkot dengan hint generik yang sama bukan satu event."""
    posts = [
        _p(id="a", location="Malang Kota", issue_hint="kebijakan pemerintah daerah",
           text="Target Pendapatan Asli Daerah Kota Malang naik tiga tahun terakhir, Pemkot optimistis"),
        _p(id="b", location="Malang Kota", issue_hint="kebijakan pemerintah daerah",
           text="Skema insentif Satuan Pelayanan Pemenuhan Gizi berubah mulai 5 Oktober, tak lagi flat"),
    ]
    drafts = cluster_rule(posts)
    assert len(drafts) == 2
    assert len({d.key for d in drafts}) == 2  # key unik walau lokasi+hint sama


def test_duplicate_texts_merge_even_with_broad_location():
    same = "Malang Raya yang dikenal sejuk kini justru terasa menyengat dalam beberapa hari terakhir"
    posts = [_p(id="a", location="Malang Raya", issue_hint="cuaca panas", text=same),
             _p(id="b", location="Malang Raya", issue_hint="cuaca panas", text=same)]
    assert len(cluster_rule(posts)) == 1


def _draft(key, loc, hint, ids, texts, authors=("a",)):
    return EventDraft(
        key=key, location=loc, issue_hint=hint, post_ids=list(ids), sample_texts=list(texts),
        sources=[{"author": a, "platform": "instagram", "kind": "root"} for a in authors],
    )


def test_apply_merge_groups_unions_members_and_sets_location():
    from ai.insight import apply_merge_groups

    drafts = [
        _draft("Klojen|laka|d", "Klojen", "kecelakaan", ["p1", "r1"], ["Laka di Jalan Veteran motor vs truk"]),
        _draft("Suhat|macet|d", "Suhat", "macet", ["p2"], ["Video konvoi, ternyata ada laka di Jalan Veteran"]),
        _draft("Jalan Veteran, Malang|laka|d", "Jalan Veteran, Malang", "laka", ["p3"], ["Innalilahi korban laka Jalan Veteran"]),
        _draft("Tajinan|kebakaran|d", "Tajinan", "kebakaran", ["p4"], ["Lahan tebu terbakar"]),
    ]
    groups = [
        {"members": [1, 2, 3], "location": "Klojen", "title": "Kecelakaan Jalan Veteran", "reason": "sama", "confidence": 0.93},
        {"members": [3, 4], "location": "X", "reason": "anggota 3 sudah terpakai → grup gugur", "confidence": 0.9},
        {"members": [4, 99], "reason": "indeks di luar rentang diabaikan", "confidence": 0.9},
    ]
    out = apply_merge_groups(drafts, groups)
    assert len(out) == 2
    veteran = next(d for d in out if "p1" in d.post_ids)
    assert set(veteran.post_ids) == {"p1", "r1", "p2", "p3"}  # balasan r1 ikut induknya
    assert veteran.location == "Klojen"
    assert len(veteran.sources) == 3
    assert next(d for d in out if "p4" in d.post_ids).location == "Tajinan"


def test_apply_merge_groups_respects_confidence_threshold():
    from ai.insight import apply_merge_groups

    drafts = [_draft("a", "A", "x", ["1"], ["t1"]), _draft("b", "B", "x", ["2"], ["t2"])]
    assert len(apply_merge_groups(drafts, [{"members": [1, 2], "reason": "ragu", "confidence": 0.5}])) == 2


def test_merge_events_llm_uses_llm_groups(monkeypatch):
    from ai import insight

    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "dummy")
    monkeypatch.setattr(insight, "llm_unavailable", lambda: False)
    seen = {}

    def fake_call(chunk):
        # kandidat diurutkan per kelas sebelum dikirim; nomor anggota mengacu urutan chunk itu
        seen["n"] = len(chunk)
        members = [i + 1 for i, d in enumerate(chunk) if d.post_ids[0] in ("p1", "p2")]
        return {"groups": [{"members": members, "location": "Klojen", "reason": "sama", "confidence": 0.9}]}

    monkeypatch.setattr(insight, "_merge_call", fake_call)
    drafts = [
        _draft("Klojen|laka|d", "Klojen", "kecelakaan", ["p1"], ["Laka Jalan Veteran"]),
        _draft("Suhat|laka|d", "Suhat", "kecelakaan", ["p2"], ["Konvoi lalu laka Jalan Veteran"]),
        _draft("Tajinan|kebakaran|d", "Tajinan", "kebakaran", ["p4"], ["Lahan tebu terbakar"]),
    ]
    out = insight.merge_events_llm(drafts)
    assert seen["n"] == 3
    assert len(out) == 2 and {tuple(sorted(d.post_ids)) for d in out} == {("p1", "p2"), ("p4",)}


def test_merge_events_llm_falls_back_when_llm_fails(monkeypatch):
    from ai import insight

    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "dummy")
    monkeypatch.setattr(insight, "llm_unavailable", lambda: False)
    monkeypatch.setattr(insight, "mark_llm_unavailable", lambda e: None)
    monkeypatch.setattr(insight, "_merge_call", lambda chunk: (_ for _ in ()).throw(RuntimeError("429")))
    drafts = [_draft("a", "A", "x", ["1"], ["t1"]), _draft("b", "B", "x", ["2"], ["t2"])]
    assert len(insight.merge_events_llm(drafts)) == 2


def test_merge_events_llm_skipped_in_heuristic_mode(monkeypatch):
    from ai import insight

    monkeypatch.setenv("AI_PROVIDER", "heuristic")
    monkeypatch.setattr(insight, "_merge_call", lambda chunk: (_ for _ in ()).throw(AssertionError("tidak boleh")))
    drafts = [_draft("a", "A", "x", ["1"], ["t1"]), _draft("b", "B", "x", ["2"], ["t2"])]
    assert insight.merge_events_llm(drafts) == drafts
