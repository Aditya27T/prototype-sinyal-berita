"""Ekspor laporan: markdown → HTML → PDF, dengan bagian Rekomendasi dibuang.

Rekomendasi bersifat internal tim monitoring; PDF yang dibagikan ke luar hanya
memuat fakta, eksposur, sentimen, potensi, dan status.
"""
from __future__ import annotations

import io
import logging
import re

import markdown
from xhtml2pdf import pisa

# xhtml2pdf mencetak setiap <a>/<br> dan peringatan glyph ke log; cukup error saja
for _name in ("xhtml2pdf", "xhtml2pdf.xhtml2pdf_reportlab", "reportlab"):
    logging.getLogger(_name).setLevel(logging.ERROR)

# Font standar PDF tidak punya glyph emoji → ganti dengan warna pada kata di belakangnya.
_EMOJI_COLOR = {
    "🔴": "#c62828",
    "🟠": "#ef6c00",
    "🟡": "#f9a825",
    "🟢": "#2e7d32",
    "⚪": "#616161",
}

_CSS = """
@page { size: A4; margin: 2cm 1.8cm; }
body { font-family: Helvetica, Arial, sans-serif; font-size: 10.5pt; line-height: 1.45; color: #1a1a1a; }
h2 { font-size: 16pt; margin: 0 0 4pt 0; }
h3 { font-size: 12.5pt; margin: 18pt 0 6pt 0; padding-top: 8pt; border-top: 1px solid #d0d0d0; }
p { margin: 0 0 6pt 0; }
ul { margin: 0 0 6pt 14pt; padding: 0; }
li { margin: 0 0 2pt 0; }
a { color: #0f766e; text-decoration: none; }
em { color: #555; }
"""


def strip_recommendation(md: str) -> str:
    """Hapus blok "**Rekomendasi**" (baris judul + paragraf sampai baris kosong) dari markdown."""
    out: list[str] = []
    skipping = False
    for line in md.splitlines():
        if line.strip() == "**Rekomendasi**":
            skipping = True
            continue
        if skipping:
            if line.strip() == "":
                skipping = False  # baris kosong penutup blok ikut dibuang
            continue
        out.append(line)
    return "\n".join(out) + ("\n" if md.endswith("\n") else "")


def _colorize_emoji(md: str) -> str:
    """"🔴 Negatif" → "<span style='color:#c62828'>Negatif</span>" agar tetap terbaca di PDF."""
    for emoji, color in _EMOJI_COLOR.items():
        md = re.sub(
            rf"{emoji}\s*([^\n*]+)",
            lambda m, c=color: f'<span style="color:{c};font-weight:bold">{m.group(1).strip()}</span>',
            md,
        )
    return md


def markdown_to_html(md: str, title: str = "Laporan") -> str:
    # "**Sentimen:** x  " + newline = hard break markdown; xhtml2pdf merapatkannya,
    # jadi tiap baris atribut dijadikan paragraf sendiri agar tetap terpisah di PDF.
    md = md.replace("  \n", "\n\n")
    body = markdown.markdown(_colorize_emoji(md), extensions=["extra", "sane_lists"])
    return f"<html><head><meta charset='utf-8'><title>{title}</title><style>{_CSS}</style></head><body>{body}</body></html>"


def markdown_to_pdf(md: str, title: str = "Laporan", include_recommendation: bool = False) -> bytes:
    if not include_recommendation:
        md = strip_recommendation(md)
    buf = io.BytesIO()
    result = pisa.CreatePDF(markdown_to_html(md, title), dest=buf, encoding="utf-8")
    if result.err:
        raise RuntimeError(f"render PDF gagal ({result.err} error)")
    return buf.getvalue()
