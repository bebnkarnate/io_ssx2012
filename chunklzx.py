# Unpacker for EA's "chunklzx" container, used by several EA Sports Xbox 360
# titles (FIFA, NHL, SSX 2012) to store LZX-compressed assets.
#
# There is no official spec for this container -- the layout below was
# confirmed by hex-dumping a real sample file (an SSX 2012 .xpr texture) and
# matching field values against the known XMemDecompress model (window size /
# compression partition size), corroborated by third-party QuickBMS notes
# for the same family of EA titles. Decompression itself is done by lzxd.py,
# a port of libmspack's LZX decoder (LGPL-2.1).
#
# Container layout (all fields big-endian, Xbox 360 is PowerPC):
#   0x00  8 bytes  magic "chunklzx"
#   0x08  u32      version/const (observed: 2)
#   0x0C  u32      total uncompressed size
#   0x10  u32      chunk size: max uncompressed bytes per chunk (compression
#                  partition size, e.g. 0x40000)
#   0x14  u32      number of chunks
#   0x18  u32      unknown/reserved (observed: 16 -- not the LZX window size;
#                  see WINDOW_BITS below)
#   0x1C  12 bytes reserved/unknown, observed as zero
#   0x28  chunk table, one entry per chunk:
#           u32    compressed size of this chunk
#           u32    chunk type: 3 = LZX compressed, 4 = stored/raw
#           <compressed size> bytes of chunk data (a sequence of LZX frames,
#           see lzxd.py, or raw bytes for stored chunks)
#           padding so the *next* chunk's data (not its 8-byte header)
#           starts on a 16-byte boundary, i.e.
#           next_data_start = align16(this_data_start + compressed_size + 8)
#
# Each chunk is an independent LZX bitstream (state resets per chunk), and
# decompresses to min(chunk_size, bytes remaining) bytes of output. The
# decoder's own internal per-frame consumption (see lzxd.py) reliably lands
# a few bytes short of the chunk table's stated compressed_size (observed:
# a constant 5-byte trailer, not otherwise decoded) -- compressed_size is
# authoritative for locating the next chunk; do not use the decoder's
# consumed-byte count for that.
#
# The LZX window size is fixed at 2^17 (128KB) -- this is the Xbox 360 XDK's
# XMemDecompress default window size (confirmed empirically: computing the
# Kraft sum of the decoded MAINTREE code lengths only comes out to exactly
# 1.0, i.e. a valid complete Huffman code, when num_offsets is derived from
# window_bits=17; any other window size in LZX's valid 15-21 range produces
# an invalid/incomplete code).

import struct

from .lzxd import decompress_chunk, LzxError

MAGIC = b"chunklzx"

CHUNK_TYPE_LZX = 3
CHUNK_TYPE_STORED = 4

WINDOW_BITS = 17

_HEADER_STRUCT = ">8sIIII"  # magic, version, full_size, chunk_size, num_chunks
_HEADER_SIZE = 0x28
_ENTRY_HEADER_STRUCT = ">II"  # compressed_size, type


class ChunkLzxError(Exception):
    pass


def is_chunklzx(data: bytes) -> bool:
    return data[:8] == MAGIC


def unpack_chunklzx(data: bytes) -> bytes:
    if not is_chunklzx(data):
        raise ChunkLzxError("not a chunklzx stream (bad magic)")

    magic, version, full_size, chunk_size, num_chunks = struct.unpack_from(_HEADER_STRUCT, data, 0)

    if chunk_size == 0:
        raise ChunkLzxError("invalid chunklzx header: chunk_size is 0")

    out = bytearray(full_size)
    out_pos = 0
    pos = _HEADER_SIZE

    for chunk_index in range(num_chunks):
        if pos + 8 > len(data):
            raise ChunkLzxError(f"truncated chunklzx chunk table at chunk {chunk_index}")

        compressed_size, chunk_type = struct.unpack_from(_ENTRY_HEADER_STRUCT, data, pos)
        data_start = pos + 8

        this_chunk_out = min(chunk_size, full_size - out_pos)

        chunk_data = data[data_start:data_start + compressed_size]
        if len(chunk_data) != compressed_size:
            raise ChunkLzxError(f"truncated chunklzx chunk {chunk_index} data")

        if chunk_type == CHUNK_TYPE_LZX:
            try:
                decoded, _consumed = decompress_chunk(chunk_data, this_chunk_out, WINDOW_BITS)
            except LzxError as e:
                raise ChunkLzxError(f"LZX decode failed on chunk {chunk_index}: {e}") from e
        elif chunk_type == CHUNK_TYPE_STORED:
            decoded = chunk_data[:this_chunk_out]
        else:
            raise ChunkLzxError(f"unknown chunklzx chunk type {chunk_type} at chunk {chunk_index}")

        out[out_pos:out_pos + this_chunk_out] = decoded
        out_pos += this_chunk_out

        next_data_start = (data_start + compressed_size + 8 + 15) & ~15
        pos = next_data_start - 8

    return bytes(out)


def read_maybe_chunklzx(filepath: str) -> bytes:
    """Read a file from disk, transparently decompressing it if it starts
    with a chunklzx header. Returns the raw (already-decompressed-if-needed)
    bytes, ready to be wrapped in a BinReader."""
    with open(filepath, "rb") as f:
        data = f.read()
    if is_chunklzx(data):
        return unpack_chunklzx(data)
    return data
