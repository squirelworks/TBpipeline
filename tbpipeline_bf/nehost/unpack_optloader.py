#!/usr/bin/env python3
"""Unpack SLR OPTLOADER (1993) Win16 NE images.

The bitstream and relocation layout follow moralrecordings' optloader.py
in win16-debug: https://github.com/moralrecordings/win16-debug
This file is a standalone port. It does not import mrcrowbar. The 16-bit
wrap on the match copy is the local fix for the segments that port rejected.

ToolBook 8.0 ships its 16-bit runtime as self-loading NE files. Segment 1
is the loader (stamp "OPTLOADER - Copyright (C) 1993 SLR Systems"). The
other segments are a bitstream plus a custom relocation table. This script
expands both and writes a normal NE with the self-loading flag cleared.

Bitstream, matching the loader at the labels used by mrcrowbar's port:

  * A 16-bit control word is shifted left. The carry is the next code bit.
    After 16 bits a new word is fetched.
  * A 1 bit is a literal byte.
  * A 0 bit starts a match. The length and the distance are both Elias-style
    bit fields, with the distance stored as a one's-complement byte pair.
  * A length byte >= 0x82 ends the stream. 0x81 is an empty match and is
    skipped.
  * Matches are copied inside a 64K window. The back-reference and the
    write cursor are masked to 16 bits; without that wrap the RLE copy
    walks off the buffer (TB80BAS, TB80BMP, TB80W16, and the others that
    the unmasked port rejected).

Segment 1 unpacks itself: a tail of `precopy_size` bytes is moved to the
end of the allocation, then the same bitstream is run from there. Its
original NE relocation table is kept. Later segments carry their own
OPTLOADER relocation records, which are rewritten as ordinary 8-byte NE
fixups. The iterated flag (segment flags bit 3) is cleared.
"""

import argparse
import os
import struct
import sys

STAMP = b'OPTLOADER - Copyright (C) 1993 SLR Systems\nAll Rights Reserved\x00'
STAMP_AT = 0x17F

# NE relocation address-type nibble, indexed by OPTLOADER target type & 3.
NE_ADDR = (0x00, 0x02, 0x03, 0x05)


class _Flags:
    def __init__(self):
        self.carry = False
        self.zero = False


def _add16(value, flags):
    total = value + value
    flags.carry = total > 0xFFFF
    return total & 0xFFFF


def _cmp(op1, op2):
    flags = _Flags()
    flags.carry = op1 < op2
    flags.zero = op1 == op2
    return flags


def _precopy(data, start_offset, precopy_offset, precopy_size):
    """Move the compressed tail up to the end of the allocation, reversed copy."""
    si = start_offset + precopy_size - 1
    di = precopy_offset + precopy_size - 1
    for _ in range(precopy_size):
        data[di] = data[si]
        di -= 1
        si -= 1


def _get_bit(src, state):
    state['bp'] = _add16(state['bp'], state['flags'])
    state['dx'] -= 1
    if state['dx'] == 0:
        state['bp'] = struct.unpack_from('<H', src, state['si'])[0]
        state['dx'] = 0x10
        state['si'] += 2
    return 1 if state['flags'].carry else 0


def optloader_expand(src, read_offset, dest, write_offset):
    """Expand one OPTLOADER stream. Returns the source cursor after the stream."""
    flags = _Flags()
    state = {
        'bp': struct.unpack_from('<H', src, read_offset)[0],
        'dx': 0x10,
        'si': read_offset + 2,
        'flags': flags,
    }
    di = write_offset
    cx = 0

    while True:
        if _get_bit(src, state):
            dest[di & 0xFFFF] = src[state['si']]
            di = (di + 1) & 0xFFFF
            state['si'] += 1
            continue

        branch1 = 1
        branch2 = 0
        bh = 0
        bl = 0

        if _get_bit(src, state):
            cx += 1
            if _get_bit(src, state):
                cx += 1
                if _get_bit(src, state):
                    bh, bl = 0x08, 0x02
                    if _get_bit(src, state):
                        bh, bl = 0x0C, 0x03
                        if _get_bit(src, state):
                            cx = src[state['si']]
                            state['si'] += 1
                            cmpf = _cmp(cx, 0x81)
                            if cmpf.carry:
                                pass
                            elif not cmpf.zero:
                                return state['si']
                            else:
                                cx = 0
                                continue
                        else:
                            cx = 0
                            while bl:
                                cx = (cx + cx + _get_bit(src, state)) & 0xFFFF
                                bl -= 1
                            cx += bh
                    else:
                        cx = 0
                        while bl:
                            cx = (cx + cx + _get_bit(src, state)) & 0xFFFF
                            bl -= 1
                        cx += bh
                else:
                    branch2 = 1
            else:
                branch2 = 1
        else:
            bh = 0
            branch2 = 1

        if branch2:
            cx += 1
            cx = (cx + cx + _get_bit(src, state)) & 0xFFFF
            if cx == 2:
                branch1 = 0

        if branch1:
            bh = 0
            skip_inc = False
            if _get_bit(src, state):
                if _get_bit(src, state):
                    ch, cl = 0x10, 0x04
                    if _get_bit(src, state):
                        ch, cl = 0x20, 0x04
                        if _get_bit(src, state):
                            ch, cl = 0x30, 0x04
                            if _get_bit(src, state):
                                ch, cl = 0x40, 0x06
                else:
                    ch, cl = 0x04, 0x02
                    if _get_bit(src, state):
                        ch, cl = 0x08, 0x03
            else:
                if _get_bit(src, state):
                    bh += 1
                    if _get_bit(src, state):
                        ch, cl = 0x02, 0x01
                    else:
                        skip_inc = True
                else:
                    skip_inc = True

            if not skip_inc:
                bh = 0
                while cl:
                    bh = (bh + bh + _get_bit(src, state)) & 0xFF
                    cl -= 1
                bh = (bh + ch) & 0xFF

        bl = src[state['si']]
        state['si'] += 1
        bl ^= 0xFF
        bh ^= 0xFF
        si_copy = (di + (bh << 8) + bl) & 0xFFFF
        for _ in range(cx):
            dest[di & 0xFFFF] = dest[si_copy & 0xFFFF]
            di = (di + 1) & 0xFFFF
            si_copy = (si_copy + 1) & 0xFFFF
        cx = 0


def _u16(buf, off):
    return struct.unpack_from('<H', buf, off)[0]


def _parse_relocs(raw, offset, count):
    """OPTLOADER relocation block -> list of 8-byte NE relocation records."""
    si = offset
    records = []
    while count > 0:
        al = raw[si]
        ah = raw[si + 1]
        si += 2
        num_items = ah
        count -= num_items
        if al == 0xF0:
            for _ in range(num_items):
                seg = raw[si]
                di = _u16(raw, si + 1)
                si += 3
                records.append(_ne_reloc(0x02, 0x00, di, seg, 0))
            continue

        tgt_type = al & 0x7
        src_type = (al >> 3) & 0x3
        addr = NE_ADDR[tgt_type & 3]
        flags = 0x04 if (tgt_type & 4) else 0x00

        if src_type == 0x00:
            seg = raw[si]
            si += 1
            loops = 1 if seg != 0xFF else num_items
            for _ in range(loops):
                di = _u16(raw, si)
                dx = _u16(raw, si + 2)
                si += 4
                records.append(_ne_reloc(addr, flags, di, seg, dx))
        elif src_type == 0x01:
            mod = _u16(raw, si)
            si += 2
            for _ in range(num_items):
                di = _u16(raw, si)
                ordinal = _u16(raw, si + 2)
                si += 4
                records.append(_ne_reloc(addr, flags | 0x01, di, mod, ordinal))
        elif src_type == 0x02:
            mod = _u16(raw, si)
            si += 2
            for _ in range(num_items):
                di = _u16(raw, si)
                name_off = _u16(raw, si + 2)
                si += 4
                records.append(_ne_reloc(addr, flags | 0x02, di, mod, name_off))
        elif src_type == 0x03:
            fixup = _u16(raw, si)
            si += 2
            for _ in range(num_items):
                di = _u16(raw, si)
                si += 2
                records.append(_ne_reloc(addr, flags | 0x03, di, fixup, 0))
        else:
            raise ValueError('unknown OPTLOADER reloc source {:02x}'.format(src_type))
    return records


def _ne_reloc(addr, flags, offset, target1, target2):
    return struct.pack('<BBHHH', addr, flags, offset & 0xFFFF, target1 & 0xFFFF, target2 & 0xFFFF)


def _alloc(value):
    return 0x10000 if value == 0 else value


def _existing_reloc_blob(data, file_off, size, flags):
    if not (flags & 0x0100):
        return b''
    count = _u16(data, file_off + size)
    return data[file_off + size:file_off + size + 2 + count * 8]


def is_optloader(data):
    if data[:2] != b'MZ':
        return False
    ne = _u16(data, 0x3C)
    if ne + 2 > len(data) or data[ne:ne + 2] != b'NE':
        return False
    nseg = _u16(data, ne + 0x1C)
    segoff = _u16(data, ne + 0x22)
    shift = _u16(data, ne + 0x32)
    if nseg < 1:
        return False
    off, size = struct.unpack_from('<HH', data, ne + segoff)
    file_off = off << shift
    blob = data[file_off:file_off + size]
    return len(blob) > STAMP_AT + len(STAMP) and blob[STAMP_AT:STAMP_AT + len(STAMP)] == STAMP


def unpack(data):
    """Return a decompressed NE image."""
    if not is_optloader(data):
        raise ValueError('not an OPTLOADER Win16 image')

    ne = _u16(data, 0x3C)
    nseg = _u16(data, ne + 0x1C)
    segoff = _u16(data, ne + 0x22)
    shift = _u16(data, ne + 0x32)
    table = ne + segoff

    segments = []
    for i in range(nseg):
        off, size, flags, alloc = struct.unpack_from('<HHHH', data, table + i * 8)
        segments.append({
            'off': off,
            'size': size,
            'flags': flags,
            'alloc': alloc,
            'file_off': off << shift,
        })

    unpacked = []
    # Segment 1 unpacks over itself.
    seg1 = segments[0]
    raw = bytearray(0x10000)
    raw[:seg1['size']] = data[seg1['file_off']:seg1['file_off'] + seg1['size']]
    start = _u16(raw, 0x08)
    precopy = _u16(raw, 0x2E)
    alloc = _alloc(seg1['alloc'])
    _precopy(raw, start, alloc - precopy, precopy)
    optloader_expand(raw, alloc - precopy, raw, start)
    unpacked.append((bytes(raw[:alloc]), _existing_reloc_blob(data, seg1['file_off'], seg1['size'], seg1['flags'])))

    for seg in segments[1:]:
        # A zero sector offset is an empty segment, not a stream. Optlink
        # leaves these as a hole with only an allocation size.
        if seg['off'] == 0 or seg['size'] == 0:
            unpacked.append((b'\x00' * _alloc(seg['alloc']), b''))
            continue
        predelta = seg['file_off'] & 0x1FF
        sector = seg['file_off'] & ~0x1FF
        span = seg['size'] + predelta
        postdelta = (512 - (span % 512)) % 512
        raw = data[sector:sector + span + postdelta]
        # The loader reads the slack between the sector and the segment.
        out = bytearray(0x10000)
        relocs_count = _u16(raw, predelta)
        end = optloader_expand(raw, predelta + 2, out, 0)
        try:
            relocs = _parse_relocs(raw, end, relocs_count)
        except Exception as exc:
            print('  reloc parse skipped: {}'.format(exc), file=sys.stderr)
            relocs = []
        blob = b''
        if relocs:
            blob = struct.pack('<H', len(relocs)) + b''.join(relocs)
        unpacked.append((bytes(out[:_alloc(seg['alloc'])]), blob))

    return _rebuild(data, ne, segments, unpacked, shift)


def _rebuild(data, ne, segments, unpacked, shift):
    real = [seg['file_off'] for seg in segments if seg['off'] and seg['size']]
    first = min(real) if real else len(data)
    prefix = bytearray(data[:first])
    # Self-loading flag. OPTLOADER sets this so Windows calls segment 1.
    flags = _u16(prefix, ne + 0x0C) & ~0x0800
    struct.pack_into('<H', prefix, ne + 0x0C, flags)

    nonres = struct.unpack_from('<I', data, ne + 0x2C)[0]
    nonres_size = _u16(data, ne + 0x1E)
    tail = b''
    if nonres >= first:
        tail = data[nonres:nonres + nonres_size]

    align = 1 << shift
    cursor = (len(prefix) + align - 1) & ~(align - 1)
    if cursor != len(prefix):
        prefix.extend(b'\x00' * (cursor - len(prefix)))
    body = bytearray()
    table = ne + _u16(prefix, ne + 0x22)

    for i, (payload, relocs) in enumerate(unpacked):
        while (len(prefix) + len(body)) % align:
            body.append(0)
        file_off = len(prefix) + len(body)
        if file_off % align:
            raise RuntimeError('alignment drifted')
        sector = file_off >> shift
        if sector > 0xFFFF:
            raise RuntimeError('segment offset does not fit the NE sector shift')
        flags = segments[i]['flags'] & ~0x0008
        if relocs:
            flags |= 0x0100
        size_field = 0 if len(payload) == 0x10000 else len(payload)
        struct.pack_into('<HHHH', prefix, table + i * 8, sector, size_field, flags, segments[i]['alloc'])
        body.extend(payload)
        body.extend(relocs)

    image = bytearray(prefix + body)
    image = _append_resources(data, image, ne)
    if tail:
        struct.pack_into('<I', image, ne + 0x2C, len(image))
        image.extend(tail)
    return image


def _append_resources(data, image, ne):
    """Keep the resource payload. ENU1 keeps its dialogs and string tables after the segments; dropping that region is what collapsed it to 7 KB."""
    rsoff = _u16(data, ne + 0x24)
    resname = _u16(data, ne + 0x26)
    if rsoff == 0 or rsoff >= resname:
        return image
    rs = ne + rsoff
    align_shift = _u16(data, rs)
    align = 1 << align_shift
    p = rs + 2
    entries = []
    while p + 8 <= len(data):
        tid, count, reserved = struct.unpack_from('<HHI', data, p)
        p += 8
        if tid == 0:
            break
        for _ in range(count):
            off, length, flags, ident = struct.unpack_from('<HHHH', data, p)
            entries.append((p, off, length))
            p += 12
    if not entries:
        return image
    start = min(off << align_shift for _, off, _ in entries)
    end = max((off << align_shift) + (length << align_shift) for _, off, length in entries)
    if end <= start or start >= len(data):
        return image
    end = min(end, len(data))
    blob = data[start:end]
    while len(image) % align:
        image.append(0)
    new_start = len(image)
    image.extend(blob)
    for pos, off, length in entries:
        file_off = off << align_shift
        new_off = (new_start + (file_off - start)) >> align_shift
        struct.pack_into('<H', image, pos, new_off)
    return image


def main():
    parser = argparse.ArgumentParser(description='Unpack SLR OPTLOADER Win16 NE images.')
    parser.add_argument('sources', nargs='+', help='EXE/DLL files, or a directory of them')
    parser.add_argument('-o', '--out', help='output file (one source) or output directory')
    args = parser.parse_args()

    files = []
    for src in args.sources:
        if os.path.isdir(src):
            for name in sorted(os.listdir(src)):
                path = os.path.join(src, name)
                if os.path.isfile(path):
                    files.append(path)
        else:
            files.append(src)

    out_dir = args.out if args.out and (len(files) > 1 or os.path.isdir(args.out or '')) else None
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    failures = 0
    for path in files:
        try:
            data = open(path, 'rb').read()
        except OSError as exc:
            print('skip  {} ({})'.format(path, exc))
            continue
        if not is_optloader(data):
            print('skip  {}'.format(path))
            continue
        try:
            image = unpack(data)
        except Exception as exc:
            failures += 1
            print('FAIL  {} ({})'.format(path, exc))
            continue
        if out_dir:
            target = os.path.join(out_dir, os.path.basename(path))
        elif args.out:
            target = args.out
        else:
            root, ext = os.path.splitext(path)
            target = root + '_unpacked' + ext
        open(target, 'wb').write(image)
        print('wrote {} ({} -> {} bytes)'.format(target, len(data), len(image)))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
