"""Suite default offline: paksa heuristic agar tidak menyentuh kuota LLM.

Test LLM asli tinggal di tests/test_relevance_eval.py yang menghapus
override ini dan skip bila tanpa key.
"""
import pytest


@pytest.fixture(autouse=True)
def _force_heuristic(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "heuristic")
