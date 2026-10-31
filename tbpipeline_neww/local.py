"""The local heap, ported from Wine dlls/krnl386.exe16/local.c (commit 2528aff2).

The heap lives in the guest's DGROUP, laid out by LocalInit16. Every
read and write goes to guest memory through word() and write(). Only the
paths a stop has named are here. Where Wine would compact or grow the
heap, this raises Stop instead of guessing what that would have done.
"""

import struct

# LOCALARENA: prev, next, size, free_prev, free_next.
PREV, NEXT, SIZE, FREE_PREV, FREE_NEXT = 0, 2, 4, 6, 8
ARENA_SIZE = 10
ARENA_HEADER_SIZE = 4
FREE, FIXED = 0, 1
LOCAL_HEAP_MAGIC = 0x484C
# LOCALHEAPINFO fields.
INFO_ITEMS, INFO_FIRST, INFO_LAST, INFO_HTABLE, INFO_HDELTA, INFO_MAGIC = 0x04, 0x06, 0x0A, 0x14, 0x18, 0x28
LMEM_MOVEABLE = 0x0002
LMEM_ZEROINIT = 0x0040
LMEM_DISCARDED = 0x4000
MOVEABLE_PREFIX = 2


class Stop(Exception):
    pass


def lalign(w):
    return (w + 3) & ~3


class LocalHeap:
    def __init__(self, ds, word, write):
        self.ds = ds
        self._word = word
        self._write = write

    def w(self, off):
        return self._word(self.ds, off & 0xFFFF)

    def put(self, off, value):
        self._write(self.ds, off & 0xFFFF, struct.pack("<H", value & 0xFFFF))

    def byte_put(self, off, value):
        self._write(self.ds, off & 0xFFFF, bytes([value & 0xFF]))

    def info(self):
        """LOCAL_GetHeap: the LOCALHEAPINFO offset, or None."""
        heap = self.w(0x06)
        if not heap or self.w(heap + INFO_MAGIC) != LOCAL_HEAP_MAGIC:
            return None
        return heap

    def make_block_free(self, block):
        self.put(block + PREV, (self.w(block + PREV) & ~3) | FREE)
        self.put(block + SIZE, self.w(block + NEXT) - block)
        nxt = self.w(block + NEXT)
        while (self.w(nxt + PREV) & 3) != FREE:
            nxt = self.w(nxt + NEXT)
        fp = self.w(nxt + FREE_PREV)
        self.put(block + FREE_PREV, fp)
        self.put(block + FREE_NEXT, nxt)
        self.put(fp + FREE_NEXT, block)
        self.put(nxt + FREE_PREV, block)

    def remove_free_block(self, block):
        self.put(block + PREV, (self.w(block + PREV) & ~3) | FIXED)
        fp, fn = self.w(block + FREE_PREV), self.w(block + FREE_NEXT)
        self.put(fp + FREE_NEXT, fn)
        self.put(fn + FREE_PREV, fp)

    def add_block(self, prev, new):
        self.put(new + PREV, (prev & ~3) | FIXED)
        nxt = self.w(prev + NEXT)
        self.put(new + NEXT, nxt)
        self.put(nxt + PREV, (self.w(nxt + PREV) & 3) | new)
        self.put(prev + NEXT, new)

    def remove_block(self, block):
        if (self.w(block + PREV) & 3) == FREE:
            self.remove_free_block(block)
        tmp = self.w(block + PREV) & ~3
        if (self.w(tmp + PREV) & 3) == FREE:
            self.put(tmp + SIZE, self.w(tmp + SIZE) + self.w(block + NEXT) - block)
        nxt = self.w(block + NEXT)
        self.put(tmp + NEXT, nxt)
        self.put(nxt + PREV, (self.w(nxt + PREV) & 3) | (self.w(block + PREV) & ~3))

    def free_arena(self, arena):
        info = self.info()
        if info is None:
            return arena
        if (self.w(arena + PREV) & 3) == FREE:
            return arena
        prev = self.w(arena + PREV) & ~3
        if (self.w(prev + PREV) & 3) == FREE:
            self.remove_block(self.w(prev + NEXT))
            self.put(info + INFO_ITEMS, self.w(info + INFO_ITEMS) - 1)
            arena = prev
        else:
            self.make_block_free(arena)
        nxt = self.w(arena + NEXT)
        if nxt == self.w(arena + FREE_NEXT) and nxt != self.w(info + INFO_LAST):
            self.remove_block(nxt)
            self.put(info + INFO_ITEMS, self.w(info + INFO_ITEMS) - 1)
        return 0

    def shrink_arena(self, arena, size):
        if arena + size + lalign(ARENA_SIZE) < self.w(arena + NEXT):
            info = self.info()
            if info is None:
                return
            self.add_block(arena, arena + size)
            self.put(info + INFO_ITEMS, self.w(info + INFO_ITEMS) + 1)
            self.free_arena(arena + size)

    def find_free_block(self, size):
        info = self.info()
        arena = self.w(info + INFO_FIRST)
        while True:
            arena = self.w(arena + FREE_NEXT)
            if arena == self.w(arena + FREE_NEXT):
                return 0
            if self.w(arena + SIZE) >= size:
                return arena

    def get_block(self, size, flags):
        if self.info() is None:
            raise Stop(f"no local heap in DS={self.ds:#x}: LOCAL_GetHeap finds no LOCALHEAPINFO")
        size = lalign(max(size + ARENA_HEADER_SIZE, ARENA_SIZE))
        arena = self.find_free_block(size)
        if arena == 0:
            raise Stop(
                f"no free block of {size:#x} bytes in DS={self.ds:#x}: Wine would LOCAL_Compact "
                "and LOCAL_GrowHeap here, and neww has neither"
            )
        self.remove_free_block(arena)
        self.shrink_arena(arena, size)
        if flags & LMEM_ZEROINIT:
            self._write(self.ds, arena + ARENA_HEADER_SIZE, b"\x00" * (size - ARENA_HEADER_SIZE))
        return arena + ARENA_HEADER_SIZE

    def new_htable(self):
        info = self.info()
        hdelta = self.w(info + INFO_HDELTA)
        handle = self.get_block(hdelta * 4 + 4, 0)
        self.put(handle, hdelta)
        entry = handle + 2
        for _ in range(hdelta):
            self.put(entry, 0)
            self._write(self.ds, entry + 2, b"\xFF\xFF")
            entry += 4
        self.put(entry, self.w(info + INFO_HTABLE))
        self.put(info + INFO_HTABLE, handle)

    def get_new_handle_entry(self):
        info = self.info()
        table = self.w(info + INFO_HTABLE)
        entry = None
        while table:
            count = self.w(table)
            entry = table + 2
            while count > 0:
                if self.w(entry + 2) >> 8 == 0xFF:
                    break
                count -= 1
                entry += 4
            if count:
                break
            table = self.w(entry)
        if not table:
            self.new_htable()
            entry = self.w(info + INFO_HTABLE) + 2
        self._write(self.ds, entry + 2, b"\x00\x00")
        return entry

    def alloc(self, flags, size):
        """LocalAlloc16."""
        if 0 < size <= 4:
            size = 5
        if flags & LMEM_MOVEABLE:
            hmem = self.get_block(size + MOVEABLE_PREFIX, flags) if size else 0
            try:
                handle = self.get_new_handle_entry()
            except Stop:
                # Wine frees the block when it gets no handle. The stop then writes nothing.
                if hmem:
                    self.free_arena(hmem - ARENA_HEADER_SIZE)
                raise
            if hmem:
                self.put(handle, hmem + MOVEABLE_PREFIX)
                # flags byte, lock byte 0.
                self._write(self.ds, handle + 2, bytes([(flags & 0x0F00) >> 8, 0]))
                self.put(hmem, handle)
            else:
                self.put(handle, 0)
                self._write(self.ds, handle + 2, bytes([LMEM_DISCARDED >> 8, 0]))
            return handle
        return self.get_block(size, flags) if size else 0
