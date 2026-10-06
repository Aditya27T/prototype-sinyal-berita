"""CLI graph: `python -m graph.run insight --date today`."""
from __future__ import annotations

import argparse

from database.connection import get_session_factory, init_db
from graph.insight_graph import run_insight


def main() -> None:
    ap = argparse.ArgumentParser(description="Telinga Digital — LangGraph runner")
    sub = ap.add_subparsers(dest="cmd", required=True)

    ins = sub.add_parser("insight", help="cluster → isu+urgency → draf laporan")
    ins.add_argument("--date", default="today", help="today | yesterday | YYYY-MM-DD")
    ins.add_argument("--min-score", type=float, default=0.0, help="ambang relevance_score")

    args = ap.parse_args()
    init_db()
    with get_session_factory()() as session:
        result = run_insight(session, window=args.date, min_score=args.min_score)
    print(f"[graph] insight {result}")


if __name__ == "__main__":
    main()