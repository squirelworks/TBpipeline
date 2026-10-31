"""The local heap, ported from Wine dlls/krnl386.exe16/local.c (commit 2528aff2).

The heap lives in the guest's DGROUP, laid out by LocalInit16. Every
read and write goes to guest memory through word() and write(). Only the
paths a stop has named are here. A full heap is compacted, then grown to 64K, as
LOCAL_GetBlock does. A heap with a LocalNotify procedure stops where Wine would call it.
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
INFO_NOTIFY, INFO_MINSIZE = 0x1E, 0x26
LMEM_NOCOMPACT = 0x0010
LMEM_NODISCARD = 0x0020
LMEM_DISCARDABLE = 0x0F00
LMEM_MOVEABLE = 0x0002
LMEM_ZEROINIT = 0x0040
LMEM_DISCARDED = 0x4000
MOVEABLE_PREFIX = 2


class Stop(Exception):
    pass


def lalign(w):
    return (w + 3) & ~3


class LocalHeap:
    def __init__(self, ds, word, write, grow=None):
        self.ds = ds
        self._word = word
        self._write = write
        # grow(ds): GlobalReAlloc of the segment to 64K, (oldsize, newsize) or None.
        self._grow = grow

    def read(self, off, size):
        return b"".join(struct.pack("<H", self.w(off + i)) for i in range(0, size + 1, 2))[:size]

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
        size = lalign(max(size + ARENA_HEADER_SIZE, ARENA_SIZE)) & 0xFFFF
        arena = self.find_free_block(size)
        if arena == 0:
            # No space: try to make some.
            self.compact(size, flags)
            arena = self.find_free_block(size)
        if arena == 0:
            # Still no space: try to grow the segment. Wine's ERR, then 0.
            if not self.grow_heap():
                return 0
            arena = self.find_free_block(size)
        if arena == 0:
            return 0
        self.remove_free_block(arena)
        self.shrink_arena(arena, size)
        if flags & LMEM_ZEROINIT:
            self._write(self.ds, arena + ARENA_HEADER_SIZE, b"\x00" * (size - ARENA_HEADER_SIZE))
        return arena + ARENA_HEADER_SIZE

    def free_space(self):
        """LOCAL_GetFreeSpace: the largest free block, less its header."""
        info = self.info()
        if info is None:
            return 0
        arena = self.w(info + INFO_FIRST)
        space = 0
        while arena != self.w(arena + FREE_NEXT):
            arena = self.w(arena + FREE_NEXT)
            if self.w(arena + SIZE) >= space:
                space = self.w(arena + SIZE)
        return 0 if space < ARENA_HEADER_SIZE else space - ARENA_HEADER_SIZE

    def _notify(self, info, what):
        """call_notify_func: nothing when no procedure is set."""
        if self.w(info + INFO_NOTIFY) or self.w(info + INFO_NOTIFY + 2):
            raise Stop(f"LOCAL_Compact would call the heap's LocalNotify procedure with {what}, "
                       "a guest call neww does not make from inside LocalAlloc")

    def _entries(self, info):
        table = self.w(info + INFO_HTABLE)
        while table:
            entry = table + 2
            for _ in range(self.w(table)):
                yield entry
                entry += 4
            table = self.w(entry)

    def grow_arena_downward(self, arena, newsize):
        """LOCAL_GrowArenaDownward: slide the block into the free arena before it."""
        info = self.info()
        if info is None:
            return
        prev = self.w(arena + PREV) & ~3
        offset = self.w(prev + SIZE)
        size = (self.w(arena + NEXT) - arena - ARENA_HEADER_SIZE) & 0xFFFF
        self.remove_free_block(prev)
        self.remove_block(arena)
        self.put(info + INFO_ITEMS, self.w(info + INFO_ITEMS) - 1)
        p = prev + ARENA_HEADER_SIZE
        while offset < size:
            self._write(self.ds, p, self.read(p + offset, offset))
            p += offset
            size -= offset
        if size:
            self._write(self.ds, p, self.read(p + offset, size))
        self.shrink_arena(prev, newsize)

    def compact(self, minfree, flags):
        """LOCAL_Compact: move unlocked moveable blocks down, then discard discardable ones."""
        info = self.info()
        if info is None:
            return 0
        space = self.free_space()
        if space >= minfree or flags & LMEM_NOCOMPACT:
            return space
        for entry in list(self._entries(info)):
            if self.w(entry + 2) >> 8 != 0 or (self.w(entry + 2) & 0xFF) == LMEM_DISCARDED >> 8:
                continue
            addr = self.w(entry)
            move = addr - MOVEABLE_PREFIX - ARENA_HEADER_SIZE
            movesize = (self.w(move + NEXT) - move) & 0xFFFF
            arena = self.w(info + INFO_FIRST)
            best, final = 0xFFFF, 0
            # The smallest free arena below the block that holds it.
            while True:
                arena = self.w(arena + FREE_NEXT)
                if arena >= move or arena == self.w(arena + FREE_NEXT):
                    break
                if movesize <= self.w(arena + SIZE) < best:
                    best, final = self.w(arena + SIZE), arena
            if final:
                self.remove_free_block(final)
                self.shrink_arena(final, movesize)
                self._write(self.ds, final + ARENA_HEADER_SIZE,
                            self.read(move + ARENA_HEADER_SIZE, movesize - ARENA_HEADER_SIZE))
                self.free_arena(move)
                self._notify(info, f"LN_MOVE for handle {entry:#x}")
                self.put(entry, final + ARENA_HEADER_SIZE + MOVEABLE_PREFIX)
            elif (self.w((self.w(move + PREV) & ~3) + PREV) & 3) == FREE:
                final = self.w(move + PREV) & ~3
                self.grow_arena_downward(move, movesize)
                self.put(entry, final + ARENA_HEADER_SIZE + MOVEABLE_PREFIX)
        space = self.free_space()
        if space >= minfree or flags & LMEM_NODISCARD:
            return space
        for entry in list(self._entries(info)):
            addr, fl = self.w(entry), self.w(entry + 2)
            if addr and fl >> 8 == 0 and fl & (LMEM_DISCARDABLE >> 8):
                self.free_arena(addr - MOVEABLE_PREFIX - ARENA_HEADER_SIZE)
                self._notify(info, f"LN_DISCARD for handle {entry:#x}")
                self.put(entry, 0)
                self._write(self.ds, entry + 2, bytes([LMEM_DISCARDED >> 8]))
        return self.compact(0xFFFF, LMEM_NODISCARD)

    def grow_heap(self):
        """LOCAL_GrowHeap: the segment goes to 64K and the new room joins the last free block."""
        if self._grow is None:
            return False
        got = self._grow(self.ds)
        if got is None:
            return False
        oldsize, end = got
        info = self.info()
        if info is None:
            return False
        last = (end - ARENA_SIZE) & ~3
        self.put(info + INFO_ITEMS, self.w(info + INFO_ITEMS) + 1)
        free = self.w(info + INFO_LAST)
        self.put(info + INFO_LAST, last)
        self.put(info + INFO_MINSIZE, self.w(info + INFO_MINSIZE) + end - oldsize)
        # The old last block grows.
        self.put(free + SIZE, last - free)
        self.put(free + NEXT, last)
        self.put(free + FREE_NEXT, last)
        # The new last block.
        self.put(last + PREV, free | FREE)
        self.put(last + NEXT, last)
        self.put(last + SIZE, lalign(ARENA_SIZE))
        self.put(last + FREE_PREV, free)
        self.put(last + FREE_NEXT, last)
        # Merge with the block before when that one is free too.
        if (self.w((self.w(free + PREV) & ~3) + PREV) & 3) == FREE:
            self.remove_block(free)
            self.put(info + INFO_ITEMS, self.w(info + INFO_ITEMS) - 1)
        return True

    def new_htable(self):
        info = self.info()
        hdelta = self.w(info + INFO_HDELTA)
        handle = self.get_block(hdelta * 4 + 4, 0)
        if not handle:
            return False
        info = self.info()
        hdelta = self.w(info + INFO_HDELTA)
        self.put(handle, hdelta)
        entry = handle + 2
        for _ in range(hdelta):
            self.put(entry, 0)
            self._write(self.ds, entry + 2, b"\xFF\xFF")
            entry += 4
        self.put(entry, self.w(info + INFO_HTABLE))
        self.put(info + INFO_HTABLE, handle)
        return True

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
            if not self.new_htable():
                return 0
            entry = self.w(info + INFO_HTABLE) + 2
        self._write(self.ds, entry + 2, b"\x00\x00")
        return entry

    def free_handle_entry(self, handle):
        """LOCAL_FreeHandleEntry: free the entry, and its table when every entry is free."""
        info = self.info()
        if info is None:
            return
        # The word that points at the table: the heap info's htable, or the previous table's link.
        link = info + INFO_HTABLE
        while self.w(link):
            table = self.w(link)
            size = self.w(table) * 4
            if table + 2 <= handle < table + 2 + size:
                break
            link = table + 2 + size
        if not self.w(link):
            raise Stop(f"LOCAL_FreeHandleEntry: {handle:#x} is in no handle table, Wine's ERR \"Invalid entry\"")
        self.put(handle, 0)
        self._write(self.ds, handle + 2, b"\xFF\xFF")
        table = self.w(link)
        count = self.w(table)
        entry = table + 2
        for _ in range(count):
            if self.w(entry + 2) >> 8 != 0xFF:
                return
            entry += 4
        self.put(link, self.w(entry))
        self.free_arena(table - ARENA_HEADER_SIZE)

    def free(self, handle):
        """LocalFree16: 0 when freed, the handle when it could not be."""
        if not handle:
            return 0
        if handle & 3 == 0:
            return 0 if not self.free_arena(handle - ARENA_HEADER_SIZE) else handle
        addr, flags = self.w(handle), self.w(handle + 2) & 0xFF
        if flags != LMEM_DISCARDED >> 8:
            if self.free_arena(addr - MOVEABLE_PREFIX - ARENA_HEADER_SIZE):
                return handle
        self.free_handle_entry(handle)
        return 0

    def alloc(self, flags, size):
        """LocalAlloc16."""
        if 0 < size <= 4:
            size = 5
        if flags & LMEM_MOVEABLE:
            hmem = 0
            if size:
                hmem = self.get_block(size + MOVEABLE_PREFIX, flags)
                if not hmem:
                    return 0
            try:
                handle = self.get_new_handle_entry()
            except Stop:
                # Wine frees the block when it gets no handle. The stop then writes nothing.
                if hmem:
                    self.free_arena(hmem - ARENA_HEADER_SIZE)
                raise
            if not handle:
                if hmem:
                    self.free_arena(hmem - ARENA_HEADER_SIZE)
                return 0
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
