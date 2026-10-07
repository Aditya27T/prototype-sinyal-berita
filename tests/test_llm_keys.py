"""Pool key Gemini: round-robin, key habis kuota dilewati, habis semua → None."""
import httpx

from ai.llm_keys import KeyPool, gemini_keys, is_gemini_quota_error


def _env(monkeypatch, **kv):
    # hapus semua varian key, bukan hanya _1.._3 — kalau .env punya _4, key asli
    # bocor ke test ini karena monkeypatch.setenv tidak menimpa yang lain
    for k in ("GEMINI_API_KEY", "GEMINI_API_KEYS", *(f"GEMINI_API_KEY_{i}" for i in range(2, 10))):
        monkeypatch.delenv(k, raising=False)
    for k, v in kv.items():
        monkeypatch.setenv(k, v)


def test_keys_collected_from_numbered_and_csv(monkeypatch):
    _env(monkeypatch, GEMINI_API_KEY="a", GEMINI_API_KEY_2="b", GEMINI_API_KEYS="c, a")
    assert gemini_keys() == ["c", "a", "b"]


def test_round_robin_and_exhaustion(monkeypatch):
    _env(monkeypatch, GEMINI_API_KEY="k1", GEMINI_API_KEY_2="k2", GEMINI_API_KEY_3="k3")
    pool = KeyPool()
    assert [pool.next_key() for _ in range(4)] == ["k1", "k2", "k3", "k1"]
    pool.mark_exhausted("k2")
    assert set(pool.next_key() for _ in range(4)) == {"k1", "k3"}
    assert not pool.all_exhausted()
    pool.mark_exhausted("k1")
    pool.mark_exhausted("k3")
    assert pool.all_exhausted() and pool.next_key() is None


def test_quota_error_detection():
    req = httpx.Request("POST", "https://x")
    resp429 = httpx.Response(429, request=req, text='{"error":{"status":"RESOURCE_EXHAUSTED"}}')
    assert is_gemini_quota_error(httpx.HTTPStatusError("x", request=req, response=resp429))
    resp500 = httpx.Response(500, request=req, text="boom")
    assert not is_gemini_quota_error(httpx.HTTPStatusError("x", request=req, response=resp500))


def test_gemini_generate_switches_key_on_429(monkeypatch):
    """429 pada key pertama → key kedua dipakai tanpa tidur; hasil tetap kembali."""
    _env(monkeypatch, GEMINI_API_KEY="k1", GEMINI_API_KEY_2="k2")
    import ai.relevance as rel

    rel.GEMINI_POOL.reset()
    used = []

    class _Resp:
        def __init__(self, key):
            self.key = key

        def raise_for_status(self):
            if self.key == "k1":
                req = httpx.Request("POST", "https://x")
                raise httpx.HTTPStatusError("429", request=req, response=httpx.Response(429, request=req, text="quota"))

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}}]}

    class _Client:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, headers=None, json=None):
            used.append(headers["x-goog-api-key"])
            return _Resp(headers["x-goog-api-key"])

    monkeypatch.setattr(rel.httpx, "Client", _Client)
    monkeypatch.setattr(rel.time, "sleep", lambda s: (_ for _ in ()).throw(AssertionError("tidak boleh tidur")))
    assert rel.gemini_generate({"contents": []}) == '{"ok": true}'
    assert used == ["k1", "k2"]
    assert rel.GEMINI_POOL.available() == ["k2"]
    rel.GEMINI_POOL.reset()
