"""Milik Person 3 — jangan `from pipeline.run import run` di sini (menimpa submodule)."""


def run(*args, **kwargs):
    from pipeline.run import run as _run

    return _run(*args, **kwargs)


__all__ = ["run"]
