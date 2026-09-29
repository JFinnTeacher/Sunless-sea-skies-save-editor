"""Reader for Sunless Skies' binary ``qualities.bytes`` definitions file.

The file is Failbetter's own binary serialisation (the game is IL2CPP, so there is no managed
code to read the schema from). What we know:

* ``int32`` record count, then the records back to back.
* Strings are ``00`` for null, or ``01`` + 7-bit varint byte length + UTF-8 bytes.
* Every record *ends* with a fixed tail::

      int32 AllowedOn, int32 Nature, int32 Category,
      5 x string (level/change description texts etc.),
      string Name, int32 Id

  and the next record starts with ``01``.

The middle of a record contains variable-length lists we have not decoded, so we find each
record's tail by scanning forward from the record start for the first offset where the tail
parses and passes sanity checks. This recovers ~2080 of the 2109 declared records.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

_I32 = struct.Struct("<i")


@dataclass
class SkiesQualityRecord:
    id: int
    name: str
    nature: int
    category: int
    allowed_on: int


class _Reader:
    def __init__(self, data: bytes):
        self.b = data
        self.n = len(data)

    def i32(self, p: int) -> tuple[int, int]:
        return _I32.unpack_from(self.b, p)[0], p + 4

    def string(self, p: int) -> tuple[str | None, int]:
        marker = self.b[p]
        if marker == 0:
            return None, p + 1
        if marker != 1:
            raise ValueError("not a string")
        p += 1
        length = shift = 0
        while True:
            c = self.b[p]
            p += 1
            length |= (c & 0x7F) << shift
            shift += 7
            if c < 0x80:
                break
            if shift > 28:
                raise ValueError("bad varint")
        end = p + length
        if end > self.n:
            raise ValueError("string overruns file")
        return self.b[p:end].decode("utf-8"), end

    def tail(self, p: int) -> tuple[SkiesQualityRecord, int] | None:
        """Try to parse a record tail starting at ``p`` (the AllowedOn field)."""
        try:
            allowed, q = self.i32(p)
            nature, q = self.i32(q)
            category, q = self.i32(q)
            if not (0 <= allowed < 10 and 0 <= nature < 5 and category >= 0):
                return None
            for _ in range(5):
                _, q = self.string(q)
            name, q = self.string(q)
            if not name:
                return None
            qid, q = self.i32(q)
        except (ValueError, IndexError, struct.error, UnicodeDecodeError):
            return None
        if not 1 <= qid < 10_000_000:
            return None
        if q != self.n and self.b[q] != 1:
            return None
        return SkiesQualityRecord(qid, name, nature, category, allowed), q


def read_qualities(path: Path) -> dict[int, SkiesQualityRecord]:
    r = _Reader(Path(path).read_bytes())
    records: dict[int, SkiesQualityRecord] = {}
    p = 4
    while p < r.n:
        # The shortest records are well over 8 bytes before their tail.
        for s in range(p + 8, r.n - 16):
            hit = r.tail(s)
            if hit:
                rec, p = hit
                records[rec.id] = rec
                break
        else:
            break  # trailing bytes we cannot interpret
    return records
