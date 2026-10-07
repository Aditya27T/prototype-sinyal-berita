"""Ekspor laporan: Rekomendasi dibuang dari PDF/MD-bagikan, PDF valid, endpoint API."""
from api.report_export import markdown_to_pdf, strip_recommendation

MD = """## LAPORAN MONITORING ISU MEDIA SOSIAL
**Periode: 6 Oktober 2026**

### 🔴 Kecelakaan Lalu Lintas di Jalan Veteran
**Kategori:** Keamanan & Kriminalitas  
**Lokasi:** Jalan Veteran

**Potensi Isu**  
Pemberitaan dapat meningkatkan perhatian.

**Rekomendasi**  
Lakukan monitoring lanjutan.
Naikkan prioritas bila perlu.

**Status:** 🟡 Monitor
"""


def test_strip_recommendation_removes_block_only():
    out = strip_recommendation(MD)
    assert "Rekomendasi" not in out
    assert "monitoring lanjutan" not in out
    assert "**Potensi Isu**" in out and "**Status:** 🟡 Monitor" in out


def test_strip_recommendation_at_end_of_document():
    md = "**Status:** ok\n\n**Rekomendasi**  \nTerakhir tanpa baris kosong."
    assert strip_recommendation(md).strip() == "**Status:** ok"


def test_markdown_to_pdf_produces_pdf_without_recommendation():
    pdf = markdown_to_pdf(MD, title="t")
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 1000


def test_report_pdf_and_md_endpoints(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import database.connection as conn
    from database.models import Report

    url = f"sqlite:///{tmp_path / 'r.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    conn._engine = None
    conn._SessionLocal = None
    conn.init_db(url)
    with conn.get_session_factory(url)() as s:
        r = Report(period="2026-10-06", body_md=MD, status="draft")
        s.add(r)
        s.commit()
        rid = r.id

    from api.main import app

    client = TestClient(app)
    pdf = client.get(f"/reports/{rid}.pdf")
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")

    md_full = client.get(f"/reports/{rid}.md").text
    assert "Rekomendasi" in md_full
    md_share = client.get(f"/reports/{rid}.md?with_recommendation=false").text
    assert "Rekomendasi" not in md_share

    assert client.get(f"/reports/{rid}").json()["status"] == "draft"
    assert client.get("/reports/tidak-ada.pdf").status_code == 404
