"""Kumpulan API key Gemini: round-robin antar key, key yang kuotanya habis dilewati.

Env: GEMINI_API_KEY, GEMINI_API_KEY_2, GEMINI_API_KEY_3, ... atau GEMINI_API_KEYS
(dipisah koma). Dipakai ai.relevance dan ai.insight supaya 3 key free-tier
dipakai bergiliran dan satu 429 tidak menghentikan seluruh run.
"""
from __future__ import annotations

import os
import threading


def gemini_keys() -> list[str]:
    keys: list[str] = []
    for raw in [os.getenv("GEMINI_API_KEYS", "")] + [
        os.getenv("GEMINI_API_KEY", ""),
        *(os.getenv(f"GEMINI_API_KEY_{i}", "") for i in range(2, 10)),
    ]:
        for k in raw.split(","):
            k = k.strip()
            if k and k not in keys:
                keys.append(k)
    return keys


class KeyPool:
    """Giliran key + daftar key yang kuotanya habis (per proses)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._idx = 0
        self._exhausted: set[str] = set()

    def available(self) -> list[str]:
        return [k for k in gemini_keys() if k not in self._exhausted]

    def next_key(self) -> str | None:
        """Key berikutnya secara round-robin; None bila semua habis / tidak ada."""
        with self._lock:
            keys = self.available()
            if not keys:
                return None
            key = keys[self._idx % len(keys)]
            self._idx += 1
            return key

    def mark_exhausted(self, key: str) -> None:
        with self._lock:
            if key not in self._exhausted:
                self._exhausted.add(key)
                print(
                    f"[ai] kuota Gemini key …{key[-4:]} habis — "
                    f"sisa key aktif: {len(self.available())}"
                )

    def all_exhausted(self) -> bool:
        return bool(gemini_keys()) and not self.available()

    def reset(self) -> None:
        with self._lock:
            self._exhausted.clear()
            self._idx = 0


GEMINI_POOL = KeyPool()


def is_gemini_quota_error(err: Exception) -> bool:
    """429 RESOURCE_EXHAUSTED / 'quota' = kuota key itu habis; pindah key, jangan retry."""
    text = str(err).lower()
    response = getattr(err, "response", None)
    if response is not None:
        try:
            text += " " + response.text.lower()
        except Exception:  # noqa: BLE001 — body tidak selalu bisa dibaca
            pass
    status = getattr(response, "status_code", None)
    return status == 429 or "resource_exhausted" in text or "quota" in text
