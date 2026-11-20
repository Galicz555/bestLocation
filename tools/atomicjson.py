"""Atomic JSON write, shared by every script that rewrites data/out/.

Every fetch_*.py read-modify-writes the SAME 8 MB settlements.json. A plain
write_text truncates the file first, so a Ctrl-C or an OOM kill mid-write leaves
a corrupt canonical artifact — and it is gitignored, so recovery means re-fetching
~1 GB of hand-downloaded data/raw/.

Write to a sibling temp file and rename: os.replace is atomic on the same
filesystem, so a reader sees either the old file or the new one, never a truncated one.

Simplification: no fsync — this survives a killed process, not a power cut. Add
os.fsync(f.fileno()) before the replace if the machine's power ever matters.
"""
import json, os
from pathlib import Path


def write_json(path, obj, **kw):
    """json.dumps(obj, **kw) -> path, atomically. Returns path."""
    path = Path(path)
    tmp = path.with_name(f".{path.name}.tmp{os.getpid()}")
    try:
        tmp.write_text(json.dumps(obj, **kw), encoding="utf-8")
        os.replace(tmp, path)                    # same directory => same filesystem
    finally:
        if tmp.exists():
            tmp.unlink()
    return path


def demo():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "x.json"
        write_json(p, {"a": 1}, indent=1)
        assert json.loads(p.read_text()) == {"a": 1}
        write_json(p, {"a": 2})                  # overwrite in place
        assert json.loads(p.read_text()) == {"a": 2}
        assert list(Path(d).iterdir()) == [p], "temp file left behind"
        try:                                     # a failed dump must not touch the target
            write_json(p, {1: object()})
        except TypeError:
            pass
        assert json.loads(p.read_text()) == {"a": 2}, "target damaged by a failed write"
        assert list(Path(d).iterdir()) == [p], "temp file left behind after failure"
    print("self-check OK")


if __name__ == "__main__":
    demo()
