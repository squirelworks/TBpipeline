#!/usr/bin/env python3
"""OpenScript bytecode decompressor.

Implements FUN_1040_0970 from TB80CMP.DLL (COMPILEREXPANDTEXT).

Usage:
    python3 openscript_decompress.py <book.tbk|book.sbk> [output.json]

The keyword table is loaded from res_77.bin (resource 0x77, id 119).
"""

import json
import struct
import sys
from pathlib import Path

# Default keyword resource (TB80CMP resource 0x77)
DEFAULT_KEYWORDS = Path(__file__).resolve().parent / "compat" / "res_77.bin"


def load_keywords(res_path: Path) -> list[str]:
    """Load the keyword table from resource 0x77.

    Layout: word count, then count*4 bytes of offset table start,
    then word offsets into the resource, then null-terminated strings.
    """
    data = res_path.read_bytes()
    count = struct.unpack_from("<H", data, 0)[0]
    fa_start = 2 + count * 4
    keywords = []
    for i in range(count):
        off = struct.unpack_from("<H", data, fa_start + i * 2)[0]
        if off >= len(data):
            break
        end = data.find(b"\x00", off)
        if end < 0:
            break
        keywords.append(data[off:end].decode("latin-1", errors="replace"))
    return keywords


def decompress(bytecode, keywords, max_out=100_000, origin=0, span=None, misses=None):
    """Decompress one OpenScript bytecode stream.

    bytecode is the book. Decoding starts at origin. A back-reference is an
    index into that same book, and it often lands before origin, in an earlier
    handler. Slicing the book first turns those copies into "?".

    Follows FUN_1040_0970:
      00-7F   literal
      80-BF   keyword (bit 4 = two-byte index, bit 5 clear = trailing space)
      C0-DF   back-reference into the input stream
      E0-EF   CRLF + 0-15 spaces
      F0-FE   2-16 spaces
      FF      repeat next byte (count+1) times
    Stops on a 0x00 literal or when the output limit is reached.

    A copy that lands outside the book is written as "?". When misses is a
    list, the book offset of each such byte is appended to it, so a caller
    can tell an unreadable handler from a real "?".
    """
    blob = bytecode
    out = bytearray()
    pos = origin
    end = len(blob) if span is None else min(len(blob), origin + span)
    if pos < end and blob[pos] == 0xF8:
        pos += 1

    while pos < end and len(out) < max_out:
        b = blob[pos]
        pos += 1

        if b < 0x80:
            if b == 0:
                break
            out.append(b)
            continue

        if (b & 0xF0) == 0xF0:
            if b == 0xFF:
                if pos + 1 >= end:
                    break
                ch = blob[pos]
                count = blob[pos + 1] + 1
                pos += 2
                out.extend([ch] * count)
            else:
                out.extend([0x20] * ((b & 0xF) + 2))
            continue

        if (b & 0xF0) == 0xE0:
            out.extend([0x0D, 0x0A])
            out.extend([0x20] * (b & 0xF))
            continue

        if (b & 0x40) == 0:
            index = b & 0xF
            if b & 0x10:
                if pos >= end:
                    break
                index = (index << 8) | blob[pos]
                pos += 1
            if index < len(keywords):
                out.extend(keywords[index].encode("latin-1"))
            if (b & 0x20) == 0:
                out.append(0x20)
            continue

        if (b & 0x10) == 0:
            if pos >= end:
                break
            length = (b & 0xF) + 3
            src = pos + (-4 - blob[pos])
            pos += 1
        else:
            if pos + 1 >= end:
                break
            length = (b & 0xF) + 4
            off = struct.unpack_from("<H", blob, pos)[0]
            src = pos + (-1 - off)
            pos += 2

        for i in range(length):
            at = src + i
            if 0 <= at < len(blob):
                out.append(blob[at])
            else:
                out.append(ord("?"))
                if misses is not None:
                    misses.append(at)

    return out.decode("latin-1", errors="replace")


