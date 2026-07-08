# Pure-Python port of the LZX decompression algorithm implemented in
# libmspack's mspack/lzxd.c, mspack/lzx.h, mspack/readbits.h and
# mspack/readhuff.h -- (C) 2003-2023 Stuart Caie, licensed under the GNU
# Lesser General Public License (LGPL) version 2.1. See
# reference/libmspack/libmspack/COPYING.LIB for the full license text.
#
# The LZX method was created by Jonathan Forbes and Tomi Poutanen, adapted
# by Microsoft Corporation. This port only implements standard (non-DELTA)
# LZX decoding of a single, self-contained bitstream at a time -- the mode
# used by Xbox 360 XMemDecompress, which is what EA's "chunklzx" container
# (see chunklzx.py) wraps one chunk at a time.

LZX_MIN_MATCH = 2
LZX_MAX_MATCH = 257
LZX_NUM_CHARS = 256
LZX_BLOCKTYPE_INVALID = 0
LZX_BLOCKTYPE_VERBATIM = 1
LZX_BLOCKTYPE_ALIGNED = 2
LZX_BLOCKTYPE_UNCOMPRESSED = 3
LZX_NUM_PRIMARY_LENGTHS = 7
LZX_NUM_SECONDARY_LENGTHS = 249

LZX_PRETREE_MAXSYMBOLS = 20
LZX_PRETREE_TABLEBITS = 6
LZX_MAINTREE_MAXSYMBOLS = LZX_NUM_CHARS + 290 * 8
LZX_MAINTREE_TABLEBITS = 12
LZX_LENGTH_MAXSYMBOLS = LZX_NUM_SECONDARY_LENGTHS + 1
LZX_LENGTH_TABLEBITS = 12
LZX_ALIGNED_MAXSYMBOLS = 8
LZX_ALIGNED_TABLEBITS = 7
LZX_LENTABLE_SAFETY = 64

LZX_FRAME_SIZE = 32768
HUFF_MAXBITS = 16
BITBUF_WIDTH = 32
BITBUF_MASK = 0xFFFFFFFF

_POSITION_SLOTS = (30, 32, 34, 36, 38, 42, 50, 66, 98, 162, 290)

_EXTRA_BITS = (
    0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8,
    9, 9, 10, 10, 11, 11, 12, 12, 13, 13, 14, 14, 15, 15, 16, 16,
)

_POSITION_BASE = (
    0, 1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64, 96, 128, 192, 256, 384, 512,
    768, 1024, 1536, 2048, 3072, 4096, 6144, 8192, 12288, 16384, 24576, 32768,
    49152, 65536, 98304, 131072, 196608, 262144, 393216, 524288, 655360,
    786432, 917504, 1048576, 1179648, 1310720, 1441792, 1572864, 1703936,
    1835008, 1966080, 2097152, 2228224, 2359296, 2490368, 2621440, 2752512,
    2883584, 3014656, 3145728, 3276800, 3407872, 3538944, 3670016, 3801088,
    3932160, 4063232, 4194304, 4325376, 4456448, 4587520, 4718592, 4849664,
    4980736, 5111808, 5242880, 5373952, 5505024, 5636096, 5767168, 5898240,
    6029312, 6160384, 6291456, 6422528, 6553600, 6684672, 6815744, 6946816,
    7077888, 7208960, 7340032, 7471104, 7602176, 7733248, 7864320, 7995392,
    8126464, 8257536, 8388608, 8519680, 8650752, 8781824, 8912896, 9043968,
    9175040, 9306112, 9437184, 9568256, 9699328, 9830400, 9961472, 10092544,
    10223616, 10354688, 10485760, 10616832, 10747904, 10878976, 11010048,
    11141120, 11272192, 11403264, 11534336, 11665408, 11796480, 11927552,
    12058624, 12189696, 12320768, 12451840, 12582912, 12713984, 12845056,
    12976128, 13107200, 13238272, 13369344, 13500416, 13631488, 13762560,
    13893632, 14024704, 14155776, 14286848, 14417920, 14548992, 14680064,
    14811136, 14942208, 15073280, 15204352, 15335424, 15466496, 15597568,
    15728640, 15859712, 15990784, 16121856, 16252928, 16384000, 16515072,
    16646144, 16777216, 16908288, 17039360, 17170432, 17301504, 17432576,
    17563648, 17694720, 17825792, 17956864, 18087936, 18219008, 18350080,
    18481152, 18612224, 18743296, 18874368, 19005440, 19136512, 19267584,
    19398656, 19529728, 19660800, 19791872, 19922944, 20054016, 20185088,
    20316160, 20447232, 20578304, 20709376, 20840448, 20971520, 21102592,
    21233664, 21364736, 21495808, 21626880, 21757952, 21889024, 22020096,
    22151168, 22282240, 22413312, 22544384, 22675456, 22806528, 22937600,
    23068672, 23199744, 23330816, 23461888, 23592960, 23724032, 23855104,
    23986176, 24117248, 24248320, 24379392, 24510464, 24641536, 24772608,
    24903680, 25034752, 25165824, 25296896, 25427968, 25559040, 25690112,
    25821184, 25952256, 26083328, 26214400, 26345472, 26476544, 26607616,
    26738688, 26869760, 27000832, 27131904, 27262976, 27394048, 27525120,
    27656192, 27787264, 27918336, 28049408, 28180480, 28311552, 28442624,
    28573696, 28704768, 28835840, 28966912, 29097984, 29229056, 29360128,
    29491200, 29622272, 29753344, 29884416, 30015488, 30146560, 30277632,
    30408704, 30539776, 30670848, 30801920, 30932992, 31064064, 31195136,
    31326208, 31457280, 31588352, 31719424, 31850496, 31981568, 32112640,
    32243712, 32374784, 32505856, 32636928, 32768000, 32899072, 33030144,
    33161216, 33292288, 33423360,
)


class LzxError(Exception):
    pass


def _make_decode_table(nsyms, nbits, length):
    """Port of make_decode_table() from readhuff.h (MSB bit-order variant).
    Returns None on table overrun (mirrors the C function returning 1)."""
    table = [0] * ((1 << nbits) + nsyms * 2)
    pos = 0
    table_mask = 1 << nbits
    bit_mask = table_mask >> 1

    for bit_num in range(1, nbits + 1):
        for sym in range(nsyms):
            if length[sym] != bit_num:
                continue
            leaf = pos
            pos += bit_mask
            if pos > table_mask:
                return None
            for fill in range(bit_mask):
                table[leaf + fill] = sym
        bit_mask >>= 1

    if pos == table_mask:
        return table

    for sym in range(pos, table_mask):
        table[sym] = 0xFFFF

    next_symbol = nsyms if (table_mask >> 1) < nsyms else (table_mask >> 1)

    pos <<= 16
    table_mask <<= 16
    bit_mask = 1 << 15

    for bit_num in range(nbits + 1, HUFF_MAXBITS + 1):
        for sym in range(nsyms):
            if length[sym] != bit_num:
                continue
            if pos >= table_mask:
                return None
            leaf = pos >> 16
            for fill in range(bit_num - nbits):
                if table[leaf] == 0xFFFF:
                    table[next_symbol << 1] = 0xFFFF
                    table[(next_symbol << 1) + 1] = 0xFFFF
                    table[leaf] = next_symbol
                    next_symbol += 1
                leaf = table[leaf] << 1
                if (pos >> (15 - fill)) & 1:
                    leaf += 1
            table[leaf] = sym
            pos += bit_mask
        bit_mask >>= 1

    return table if pos == table_mask else None


class _BitReader:
    """MSB-first bit reader matching readbits.h's BITS_ORDER_MSB variant.

    LZX reads bytes in pairs, little-endian within the pair, then reads bits
    from the buffer MSB-first -- this quirk comes straight from lzxd.c's
    READ_BYTES macro.
    """

    __slots__ = ("data", "pos", "end", "bit_buffer", "bits_left", "input_end")

    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0
        self.end = len(data)
        self.bit_buffer = 0
        self.bits_left = 0
        self.input_end = False

    def _read_bytes(self):
        if self.pos + 1 < self.end:
            b0 = self.data[self.pos]
            b1 = self.data[self.pos + 1]
            self.pos += 2
        elif self.pos < self.end:
            b0 = self.data[self.pos]
            b1 = 0
            self.pos += 1
        else:
            # matches read_input()'s fake 2-zero-byte EOF padding
            if self.input_end:
                raise LzxError("out of input bytes")
            b0 = b1 = 0
            self.input_end = True
        word = (b1 << 8) | b0
        self.bit_buffer = (self.bit_buffer | (word << (BITBUF_WIDTH - 16 - self.bits_left))) & BITBUF_MASK
        self.bits_left += 16

    def ensure(self, n):
        while self.bits_left < n:
            self._read_bytes()

    def peek(self, n):
        return self.bit_buffer >> (BITBUF_WIDTH - n)

    def remove(self, n):
        self.bit_buffer = (self.bit_buffer << n) & BITBUF_MASK
        self.bits_left -= n

    def read(self, n):
        self.ensure(n)
        v = self.peek(n)
        self.remove(n)
        return v

    def discard_buffered_bits(self):
        """Mirrors the uncompressed-block byte-realign dance in lzxd.c:
        ensure a 16-bit fill happened (so i_ptr sits on an even boundary),
        then drop whatever's left in the bit buffer without touching pos."""
        if self.bits_left == 0:
            self.ensure(16)
        self.bit_buffer = 0
        self.bits_left = 0

    def read_raw_bytes(self, n):
        out = self.data[self.pos:self.pos + n]
        self.pos += n
        if len(out) < n:
            out += b"\x00" * (n - len(out))
        return out


def _read_huffsym(br, table, lengths, maxsymbols, tablebits):
    br.ensure(HUFF_MAXBITS)
    sym = table[br.peek(tablebits)]
    if sym >= maxsymbols:
        mask = 1 << (BITBUF_WIDTH - tablebits)
        while True:
            mask >>= 1
            if mask == 0:
                raise LzxError("huffman decode error (bad table)")
            bit = 1 if (br.bit_buffer & mask) else 0
            sym = table[(sym << 1) | bit]
            if sym < maxsymbols:
                break
    br.remove(lengths[sym])
    return sym


class _LzxdState:
    def __init__(self, window_bits):
        if not (15 <= window_bits <= 21):
            raise LzxError(f"unsupported LZX window_bits: {window_bits}")
        self.window_bits = window_bits
        self.window_size = 1 << window_bits
        self.window = bytearray(self.window_size)
        self.window_posn = 0
        self.frame_posn = 0
        self.frame = 0
        self.num_offsets = _POSITION_SLOTS[window_bits - 15] << 3
        self.intel_filesize = 0
        self.intel_started = False

        self.PRETREE_len = [0] * (LZX_PRETREE_MAXSYMBOLS + LZX_LENTABLE_SAFETY)
        self.MAINTREE_len = [0] * (LZX_MAINTREE_MAXSYMBOLS + LZX_LENTABLE_SAFETY)
        self.LENGTH_len = [0] * (LZX_LENGTH_MAXSYMBOLS + LZX_LENTABLE_SAFETY)
        self.ALIGNED_len = [0] * (LZX_ALIGNED_MAXSYMBOLS + LZX_LENTABLE_SAFETY)
        self.MAINTREE_table = None
        self.LENGTH_table = None
        self.ALIGNED_table = None
        self.LENGTH_empty = False

        self._reset_state()

    def _reset_state(self):
        self.R0 = self.R1 = self.R2 = 1
        self.header_read = False
        self.block_remaining = 0
        self.block_length = 0
        self.block_type = LZX_BLOCKTYPE_INVALID
        for i in range(LZX_MAINTREE_MAXSYMBOLS):
            self.MAINTREE_len[i] = 0
        for i in range(LZX_LENGTH_MAXSYMBOLS):
            self.LENGTH_len[i] = 0

    def _read_lens(self, br, lens, first, last):
        for x in range(20):
            self.PRETREE_len[x] = br.read(4)
        pretree_table = _make_decode_table(LZX_PRETREE_MAXSYMBOLS, LZX_PRETREE_TABLEBITS, self.PRETREE_len)
        if pretree_table is None:
            raise LzxError("failed to build PRETREE table")

        x = first
        while x < last:
            z = _read_huffsym(br, pretree_table, self.PRETREE_len, LZX_PRETREE_MAXSYMBOLS, LZX_PRETREE_TABLEBITS)
            if z == 17:
                y = br.read(4) + 4
                for _ in range(y):
                    lens[x] = 0
                    x += 1
            elif z == 18:
                y = br.read(5) + 20
                for _ in range(y):
                    lens[x] = 0
                    x += 1
            elif z == 19:
                y = br.read(1) + 4
                z2 = _read_huffsym(br, pretree_table, self.PRETREE_len, LZX_PRETREE_MAXSYMBOLS, LZX_PRETREE_TABLEBITS)
                delta = lens[x] - z2
                if delta < 0:
                    delta += 17
                for _ in range(y):
                    lens[x] = delta
                    x += 1
            else:
                delta = lens[x] - z
                if delta < 0:
                    delta += 17
                lens[x] = delta
                x += 1


def _copy_match(window, window_size, dest, src_offset_back, length, window_posn):
    """Copy `length` bytes within the circular window, `src_offset_back` bytes
    behind `dest` (dest = window_posn before the copy). Handles the LRU-style
    overlapping copies (src_offset_back < length) and window wraparound,
    mirroring the pointer-chasing loop in lzxd_decompress()."""
    if src_offset_back > window_posn:
        # match reaches back across the window wrap point
        j = src_offset_back - window_posn
        if j > window_size:
            raise LzxError("match offset beyond window boundaries")
        src = window_size - j
        if j < length:
            # two-part copy: tail of window, then front
            remaining = length - j
            _copy_overlapping(window, dest, src, j)
            _copy_overlapping(window, dest + j, 0, remaining)
        else:
            _copy_overlapping(window, dest, src, length)
    else:
        src = dest - src_offset_back
        _copy_overlapping(window, dest, src, length)


def _copy_overlapping(window, dest, src, length):
    gap = dest - src
    if gap <= 0:
        # shouldn't happen for src >= 0 given how this is invoked, but guard anyway
        window[dest:dest + length] = window[src:src + length]
        return
    if gap >= length:
        window[dest:dest + length] = window[src:src + length]
    else:
        pattern = bytes(window[src:src + gap])
        reps = (length + gap - 1) // gap
        window[dest:dest + length] = (pattern * reps)[:length]


def decompress_chunk(data: bytes, out_size: int, window_bits: int):
    """Decompress a self-contained LZX bitstream (as produced by one Xbox 360
    XMemCompress/XMemDecompress chunk) to exactly out_size bytes.

    Unlike CAB LZX, each 32KB LZX frame here is prefixed with a small header
    (mirrors the CFDATA-style framing seen in Unreal Engine's Xbox 360
    mspack_read() glue): normally 2 bytes (big-endian compressed size of this
    frame's bitstream); when the first byte reads as 0xFF, that's an escape
    to a 5-byte form instead (0xFF, 2-byte BE uncompressed size -- always
    equal to frame_size, unused otherwise -- then the real 2-byte BE
    compressed size). Both forms feed a genuine LZX bitstream; there is no
    raw/stored frame variant at this level. This function strips those
    per-frame headers as it walks the frames.

    Returns (decompressed_bytes, consumed_byte_count) -- the caller should
    trust consumed_byte_count (not an outer container's stated compressed
    size) to locate whatever follows this chunk's data, since some chunklzx
    files pad chunk data to alignment boundaries that aren't reflected in the
    container's own size field.
    """
    if out_size == 0:
        return b"", 0

    lzx = _LzxdState(window_bits)
    window = lzx.window
    window_size = lzx.window_size

    output = bytearray(out_size)
    offset = 0  # bytes produced so far, overall
    pos = 0  # cursor into `data`

    end_frame = (offset + out_size) // LZX_FRAME_SIZE + 1

    while lzx.frame < end_frame:
        frame_size = LZX_FRAME_SIZE
        if (out_size - offset) < frame_size:
            frame_size = out_size - offset

        if frame_size == 0:
            # libmspack's end_frame formula always allows one trailing
            # "phantom" iteration once out_size is an exact multiple of
            # LZX_FRAME_SIZE; in the original it's a true no-op, but here
            # it must not touch `data` at all, since there is no frame
            # left to have a size-prefix -- what follows is the next
            # container chunk (or end of input).
            break

        # Normally a 2-byte BE compressed size. When the encoder needs to
        # escape (its high byte would otherwise read as the 0xFF marker
        # itself, or similar), it instead emits 0xFF, a 2-byte BE
        # uncompressed size (== frame_size, unused otherwise) and a 2-byte
        # BE compressed size. Either way the frame's payload is still a
        # genuine LZX bitstream -- there is no raw/stored frame variant.
        if data[pos] == 0xFF:
            pos += 3
        frame_compressed_size = (data[pos] << 8) | data[pos + 1]
        pos += 2

        frame_data = data[pos:pos + frame_compressed_size]
        pos += frame_compressed_size

        br = _BitReader(frame_data)

        if not lzx.header_read:
            i = br.read(1)
            j = 0
            if i:
                i = br.read(16)
                j = br.read(16)
            else:
                i = 0
            lzx.intel_filesize = (i << 16) | j
            lzx.header_read = True

        bytes_todo = lzx.frame_posn + frame_size - lzx.window_posn
        while bytes_todo > 0:
            if lzx.block_remaining == 0:
                if lzx.block_type == LZX_BLOCKTYPE_UNCOMPRESSED and (lzx.block_length & 1):
                    br.read_raw_bytes(1)

                lzx.block_type = br.read(3)
                i = br.read(16)
                j = br.read(8)
                lzx.block_remaining = lzx.block_length = (i << 8) | j

                if lzx.block_type == LZX_BLOCKTYPE_ALIGNED:
                    for i in range(8):
                        lzx.ALIGNED_len[i] = br.read(3)
                    lzx.ALIGNED_table = _make_decode_table(LZX_ALIGNED_MAXSYMBOLS, LZX_ALIGNED_TABLEBITS, lzx.ALIGNED_len)
                    if lzx.ALIGNED_table is None:
                        raise LzxError("failed to build ALIGNED table")
                    lzx._read_lens(br, lzx.MAINTREE_len, 0, 256)
                    lzx._read_lens(br, lzx.MAINTREE_len, 256, LZX_NUM_CHARS + lzx.num_offsets)
                    lzx.MAINTREE_table = _make_decode_table(LZX_MAINTREE_MAXSYMBOLS, LZX_MAINTREE_TABLEBITS, lzx.MAINTREE_len)
                    if lzx.MAINTREE_table is None:
                        raise LzxError("failed to build MAINTREE table")
                    if lzx.MAINTREE_len[0xE8] != 0:
                        lzx.intel_started = True
                    lzx._read_lens(br, lzx.LENGTH_len, 0, LZX_NUM_SECONDARY_LENGTHS)
                    lzx.LENGTH_table = _make_decode_table(LZX_LENGTH_MAXSYMBOLS, LZX_LENGTH_TABLEBITS, lzx.LENGTH_len)
                    lzx.LENGTH_empty = lzx.LENGTH_table is None
                    if lzx.LENGTH_table is None and any(lzx.LENGTH_len[i] for i in range(LZX_LENGTH_MAXSYMBOLS)):
                        raise LzxError("failed to build LENGTH table")

                elif lzx.block_type == LZX_BLOCKTYPE_VERBATIM:
                    lzx._read_lens(br, lzx.MAINTREE_len, 0, 256)
                    lzx._read_lens(br, lzx.MAINTREE_len, 256, LZX_NUM_CHARS + lzx.num_offsets)
                    lzx.MAINTREE_table = _make_decode_table(LZX_MAINTREE_MAXSYMBOLS, LZX_MAINTREE_TABLEBITS, lzx.MAINTREE_len)
                    if lzx.MAINTREE_table is None:
                        raise LzxError("failed to build MAINTREE table")
                    if lzx.MAINTREE_len[0xE8] != 0:
                        lzx.intel_started = True
                    lzx._read_lens(br, lzx.LENGTH_len, 0, LZX_NUM_SECONDARY_LENGTHS)
                    lzx.LENGTH_table = _make_decode_table(LZX_LENGTH_MAXSYMBOLS, LZX_LENGTH_TABLEBITS, lzx.LENGTH_len)
                    lzx.LENGTH_empty = lzx.LENGTH_table is None
                    if lzx.LENGTH_table is None and any(lzx.LENGTH_len[i] for i in range(LZX_LENGTH_MAXSYMBOLS)):
                        raise LzxError("failed to build LENGTH table")

                elif lzx.block_type == LZX_BLOCKTYPE_UNCOMPRESSED:
                    lzx.intel_started = True
                    br.discard_buffered_bits()
                    buf = br.read_raw_bytes(12)
                    lzx.R0 = int.from_bytes(buf[0:4], "little")
                    lzx.R1 = int.from_bytes(buf[4:8], "little")
                    lzx.R2 = int.from_bytes(buf[8:12], "little")

                else:
                    raise LzxError(f"bad LZX block type: {lzx.block_type}")

            this_run = lzx.block_remaining
            if this_run > bytes_todo:
                this_run = bytes_todo
            bytes_todo -= this_run
            lzx.block_remaining -= this_run

            if lzx.block_type in (LZX_BLOCKTYPE_ALIGNED, LZX_BLOCKTYPE_VERBATIM):
                aligned = lzx.block_type == LZX_BLOCKTYPE_ALIGNED
                while this_run > 0:
                    main_element = _read_huffsym(br, lzx.MAINTREE_table, lzx.MAINTREE_len, LZX_MAINTREE_MAXSYMBOLS, LZX_MAINTREE_TABLEBITS)
                    if main_element < LZX_NUM_CHARS:
                        window[lzx.window_posn] = main_element
                        lzx.window_posn += 1
                        this_run -= 1
                    else:
                        main_element -= LZX_NUM_CHARS
                        match_length = main_element & LZX_NUM_PRIMARY_LENGTHS
                        if match_length == LZX_NUM_PRIMARY_LENGTHS:
                            if lzx.LENGTH_empty:
                                raise LzxError("LENGTH symbol needed but tree is empty")
                            length_footer = _read_huffsym(br, lzx.LENGTH_table, lzx.LENGTH_len, LZX_LENGTH_MAXSYMBOLS, LZX_LENGTH_TABLEBITS)
                            match_length += length_footer
                        match_length += LZX_MIN_MATCH

                        slot = main_element >> 3
                        if slot == 0:
                            match_offset = lzx.R0
                        elif slot == 1:
                            match_offset = lzx.R1
                            lzx.R1 = lzx.R0
                            lzx.R0 = match_offset
                        elif slot == 2:
                            match_offset = lzx.R2
                            lzx.R2 = lzx.R0
                            lzx.R0 = match_offset
                        else:
                            extra = 17 if slot >= 36 else _EXTRA_BITS[slot]
                            match_offset = _POSITION_BASE[slot] - 2
                            if extra >= 3 and aligned:
                                if extra > 3:
                                    verbatim_bits = br.read(extra - 3)
                                    match_offset += verbatim_bits << 3
                                aligned_bits = _read_huffsym(br, lzx.ALIGNED_table, lzx.ALIGNED_len, LZX_ALIGNED_MAXSYMBOLS, LZX_ALIGNED_TABLEBITS)
                                match_offset += aligned_bits
                            elif extra:
                                verbatim_bits = br.read(extra)
                                match_offset += verbatim_bits
                            lzx.R2 = lzx.R1
                            lzx.R1 = lzx.R0
                            lzx.R0 = match_offset

                        if (lzx.window_posn + match_length) > window_size:
                            raise LzxError("match ran over window wrap")

                        _copy_match(window, window_size, lzx.window_posn, match_offset, match_length, lzx.window_posn)

                        this_run -= match_length
                        lzx.window_posn += match_length
            elif lzx.block_type == LZX_BLOCKTYPE_UNCOMPRESSED:
                chunk = br.read_raw_bytes(this_run)
                window[lzx.window_posn:lzx.window_posn + this_run] = chunk
                lzx.window_posn += this_run
            else:
                raise LzxError("bad LZX block type")

        if (lzx.window_posn - lzx.frame_posn) != frame_size:
            raise LzxError("decode beyond output frame limits")

        _finish_frame(lzx, window, window_size, output, offset, frame_size)
        offset += frame_size

        lzx.frame_posn += frame_size
        lzx.frame += 1

        if lzx.window_posn == window_size:
            lzx.window_posn = 0
        if lzx.frame_posn == window_size:
            lzx.frame_posn = 0

    return bytes(output), pos


def _finish_frame(lzx, window, window_size, output, offset, frame_size):
    """Applies the Intel E8 call-translation filter (only matters for x86
    executable data; texture/geometry assets should never trigger
    intel_started) and writes the decoded frame to the output buffer."""
    if lzx.intel_started and lzx.intel_filesize and lzx.frame < 32768 and frame_size > 10:
        frame_bytes = bytearray(window[lzx.frame_posn:lzx.frame_posn + frame_size])
        dataend = frame_size - 10
        curpos = offset
        filesize = lzx.intel_filesize
        i = 0
        while i < dataend:
            if frame_bytes[i] != 0xE8:
                i += 1
                curpos += 1
                continue
            abs_off = int.from_bytes(frame_bytes[i + 1:i + 5], "little", signed=True)
            if -curpos <= abs_off < filesize:
                rel_off = (abs_off - curpos) if abs_off >= 0 else (abs_off + filesize)
                frame_bytes[i + 1:i + 5] = (rel_off & 0xFFFFFFFF).to_bytes(4, "little")
            i += 5
            curpos += 5
        out_frame = bytes(frame_bytes)
    else:
        out_frame = bytes(window[lzx.frame_posn:lzx.frame_posn + frame_size])

    output[offset:offset + frame_size] = out_frame
