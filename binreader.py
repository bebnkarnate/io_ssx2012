# SPDX-License-Identifier: LGPL-2.1-only
import struct

class BinReader:
    def __init__(self, f, endian="<"):
        self.f = f
        self.endian = endian  # "<" little, ">" big

    def tell(self):
        return self.f.tell()

    def seek(self, offset, whence=0):
        self.f.seek(offset, whence)

    def skip(self, count):
        self.f.seek(count, 1)

    def read(self, arg, /, *, fmt=None):
        if isinstance(arg, str):
            fmt = arg
            size = struct.calcsize(fmt)
        else:
            size = arg

        if fmt is not None and isinstance(arg, int):
            size = struct.calcsize(fmt)

        data = self.f.read(size)
        if len(data) != size:
            raise EOFError("Unexpected end of file")

        if fmt is None:
            return data

        return struct.unpack(fmt, data)

    def filesize(self):
        cur = self.tell()
        self.seek(0, 2)
        size = self.tell()
        self.seek(cur, 0)
        return size

    def peek_u32(self):
        pos = self.tell()
        if pos + 4 > self.filesize():
            return None
        data = self.f.read(4)
        self.f.seek(pos, 0)
        if len(data) < 4:
            return None
        return struct.unpack(self.endian + "I", data)[0]

    def u32(self):
        return struct.unpack(self.endian + "I", self.read(4))[0]

    def i32(self):
        return struct.unpack(self.endian + "i", self.read(4))[0]

    def u16(self):
        return struct.unpack(self.endian + "H", self.read(2))[0]

    def i16(self,count=1):
        if count == 1:
            return struct.unpack(self.endian + "H", self.read(2))[0]
        return struct.unpack(self.endian + "H" * count, self.read(2 * count))

    def u64(self):
        return struct.unpack(self.endian + "Q", self.read(8))[0]

    def f16(self, count=1):
        if count == 1:
            return struct.unpack(self.endian + "e", self.read(2))[0]
        return struct.unpack(self.endian + "e" * count, self.read(2 * count))

    def f32(self, count=1):
        if count == 1:
            return struct.unpack(self.endian + "f", self.read(4))[0]
        return struct.unpack(self.endian + "f" * count, self.read(4 * count))

    def u8(self, count=1):
        if count == 1:
            return struct.unpack(self.endian + "B", self.read(1))[0]
        return struct.unpack(self.endian + "B" * count, self.read(count))

    def magic(self):
        return self.read(4) if self.endian == '>' else self.read(4)[::-1]

    def ssx_string(self):
        length = self.u32()
        raw = self.read(length + 1)
        if raw.endswith(b"\x00"):
            raw = raw[:-1]
        return raw.decode("utf-8", errors="replace")
    
    def cstring(self):
        chars = []
        while True:
            b = self.read(1)
            if not b:
                raise EOFError("Unexpected EOF while reading C‑string")
            if b == b'\x00':
                break
            chars.append(b)
        return b''.join(chars).decode('utf-8', errors='replace')


    def align16(self):
        pos = self.tell()
        aligned = (pos + 15) & ~15
        if aligned != pos:
            self.seek(aligned)