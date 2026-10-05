"""Eval relevansi LLM vs label manual (milik Person 2).

Ground truth: fixtures/relevance_labels.json (30 posting real 2026-10-05,
dilabel manual sesuai aturan PLAN). Skip bila tanpa GEMINI_API_KEY.
Target PLAN: precision indikatif ~80%.
"""
import json
import time
from pathlib import Path

import pytest

from ai.relevance import analyze, provider
from collectors.source_one import _to_post

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "fixtures" / "instagram_2026-10-05.json"
LABELS = ROOT / "fixtures" / "relevance_labels.json"

KEYMAP = {
    "malangraya_info": ("malangraya_info", "instagram"),
    "infomalangan": ("infomalangan", "instagram"),
    "jawaposradarmalang": ("jawaposradarmalang", "instagram"),
    "instagram:account:malangraya_info": ("malangraya_info", "instagram"),
    "instagram:account:infomalangan": ("infomalangan", "instagram"),
    "instagram:account:jawaposradarmalang": ("jawaposradarmalang", "instagram"),
    "instagram:hashtag:malang": ("#malang", "instagram"),
    "threads:search:malang": ("malang", "threads"),
}


def _candidates():
    snap = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    posts = []
    for key, items in snap.items():
        sq, plat = KEYMAP.get(key, (key, "instagram"))
        for raw in items:
            p = _to_post(raw, sq, plat)
            if p and p.text.strip():
                posts.append(p)
    by_src: dict[str, list] = {}
    for p in posts:
        by_src.setdefault(p.source_query, []).append(p)
    picked = []
    i = 0
    while len(picked) < 30 and any(len(v) > i for v in by_src.values()):
        for sq, lst in by_src.items():
            if len(lst) > i:
                picked.append(lst[i])
        i += 1
    return picked


def test_llm_precision_on_real_posts():
    if provider() != "gemini":
        pytest.skip("tanpa GEMINI_API_KEY — eval LLM dilewati")
    cands = _candidates()
    labels = {l["idx"]: l for l in json.loads(LABELS.read_text(encoding="utf-8"))}
    assert len(cands) == len(labels) == 30
    tp = fp = fn = tn = 0
    wrong = []
    for n, post in enumerate(cands):
        exp = labels[n]
        got = analyze(post)
        if n < len(cands) - 1:
            time.sleep(4)  # free-tier throttle
        if got.is_relevant and exp["relevant"]:
            tp += 1
        elif got.is_relevant and not exp["relevant"]:
            fp += 1
            wrong.append((n, "FP", post.text[:70], got.location, got.issue_hint))
        elif not got.is_relevant and exp["relevant"]:
            fn += 1
            wrong.append((n, "FN", post.text[:70], got.location, got.issue_hint))
        else:
            tn += 1
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    print(f"\nprecision={precision:.2f} recall={recall:.2f} (tp={tp} fp={fp} fn={fn} tn={tn})")
    for w in wrong:
        print(" ", w)
    assert precision >= 0.8, f"precision {precision:.2f} di bawah target 0.8"
