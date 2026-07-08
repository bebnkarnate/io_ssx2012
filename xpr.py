import bpy
import struct
import os
import tempfile
import io
from .binreader import *
from .chunklzx import read_maybe_chunklzx

# ------------------------------------------------------------
# Core helpers
# ------------------------------------------------------------

 
def AlignValue(num, alignTo):
    return ((num + alignTo - 1) & ~(alignTo - 1))
 
 
def appLog2(n):
    r = -1
    while n:
        n >>= 1
        r += 1
    return r
 
 
def GetXbox360TiledOffset(x, y, width, logBpb):
    alignedWidth = AlignValue(width, 32)
    macro = ((x >> 5) + (y >> 5) * (alignedWidth >> 5)) << (logBpb + 7)
    micro = ((x & 7) + ((y & 0xE) << 2)) << logBpb
    offset = macro + ((micro & ~0xF) << 1) + (micro & 0xF) + ((y & 1) << 4)
    return (((offset & ~0x1FF) << 3) +
            ((y & 16) << 7) +
            ((offset & 0x1C0) << 2) +
            (((((y & 8) >> 2) + (x >> 3)) & 3) << 6) +
            (offset & 0x3F)) >> logBpb
 
 
def PerformX360Untile(src, dst, tiledWidth, originalWidth, tiledHeight, originalHeight,
                       blockSizeX, blockSizeY, bytesPerBlock):
    tiledBlockWidth = tiledWidth // blockSizeX
    originalBlockWidth = originalWidth // blockSizeX
    tiledBlockHeight = tiledHeight // blockSizeY
    originalBlockHeight = originalHeight // blockSizeY
    logBpp = appLog2(bytesPerBlock)
 
    sxOffset = 0
    if (tiledBlockWidth >= originalBlockWidth * 2) and (originalWidth == 16):
        sxOffset = originalBlockWidth
 
    for dy in range(originalBlockHeight):
        for dx in range(originalBlockWidth):
            swzAddr = GetXbox360TiledOffset(dx + sxOffset, dy, tiledBlockWidth, logBpp)
            sy = swzAddr // tiledBlockWidth
            sx = swzAddr % tiledBlockWidth
            dst_add = (dy * originalBlockWidth + dx) * bytesPerBlock
            src_add = (sy * tiledBlockWidth + sx) * bytesPerBlock
            for c in range(bytesPerBlock):
                dst[dst_add + c] = src[src_add + c]
 
 
# ------------------------------------------------------------
# Untile + mip handling
# ------------------------------------------------------------
def _swap_u16(data: bytes) -> bytes:
    count = len(data) // 2
    if count == 0:
        return data
    usable = count * 2
    swapped = struct.pack("<" + str(count) + "H",
                           *struct.unpack(">" + str(count) + "H", data[:usable]))
    # keep a trailing odd byte instead of dropping it
    return swapped + data[usable:]
 
 
def _block_dims(w, h, blockSizeX, blockSizeY, alignX=1, alignY=1):
    """Block-aligned width/height, floored at 1 block."""
    aw = AlignValue(max(w, 1), alignX)
    ah = AlignValue(max(h, 1), alignY)
    bw = max(1, (aw + blockSizeX - 1) // blockSizeX)
    bh = max(1, (ah + blockSizeY - 1) // blockSizeY)
    return bw, bh
 
 
def _resolve_format_options(imgFormat, options=None):
    if options:
        return (options["blockSizeX"], options["blockSizeY"],
                options["bytesPerBlock"], options["alignX"], options["alignY"])
 
    match imgFormat:
        case b"DXT1":
            return 4, 4, 8, 128, 128
        case b"DXT3" | b"DXT5":
            return 4, 4, 16, 128, 128
        case b"ATI2":
            return 4, 4, 16, 128, 128
        case b"\0\0\0\0":  # raw RGBA
            return 1, 1, 4, 32, 32
        case _:
            return None
 
 
def UntileX360Image(imgData, width, height, imgFormat, mipCount=1, options=None):
    imgData = _swap_u16(imgData)
 
    resolved = _resolve_format_options(imgFormat, options)
    if resolved is None:
        print("UNKNOWN IMAGE FORMAT:", imgFormat)
        return []
    blockSizeX, blockSizeY, bytesPerBlock, alignX, alignY = resolved
 
    mipmaps = []
    offset = 0
    curW = width
    curH = height
 
    for mipLevel in range(mipCount):
        # on-disk (tiled) dims, aligned to the tile granularity
        tiledW = AlignValue(curW, alignX)
        tiledH = AlignValue(curH, alignY)

        # logical dims, floored to one block (matches console storage)
        logicalW = max(curW, blockSizeX)
        logicalH = max(curH, blockSizeY)
 
        tiledBlockWidth, tiledBlockHeight = _block_dims(tiledW, tiledH, blockSizeX, blockSizeY)
        originalBlockWidth, originalBlockHeight = _block_dims(logicalW, logicalH, blockSizeX, blockSizeY)
 
        mipSize = tiledBlockWidth * tiledBlockHeight * bytesPerBlock
        if offset + mipSize > len(imgData):
            # not enough data left for this mip -- stop rather than fabricate
            break

        mipSrc = imgData[offset:offset + mipSize]
        offset += mipSize

        logBpp = appLog2(bytesPerBlock)

        # PerformX360Untile expects pixel dimensions, not block counts
        untiled = bytearray(originalBlockWidth * originalBlockHeight * bytesPerBlock)
 
        PerformX360Untile(
            mipSrc, untiled,
            tiledBlockWidth * blockSizeX, logicalW,
            tiledBlockHeight * blockSizeY, logicalH,
            blockSizeX, blockSizeY,
            bytesPerBlock
        )
 
        mipmaps.append({
            "width": curW,
            "height": curH,
            "data": untiled,
            "blockWidth": originalBlockWidth,
            "blockHeight": originalBlockHeight,
        })
 
        curW = max(1, curW // 2)
        curH = max(1, curH // 2)
 
    return mipmaps


# ------------------------------------------------------------
# XPR parsing + mipCount detection
# ------------------------------------------------------------

def read_xpr_header(bs: BinReader):
    textures = []
    Header = bs.read(">iiii")

    if Header[0] != 1481658930:
        raise ValueError("Invalid XPR header")

    headerSize = Header[1]
    Tex = []
    TexNames = []
    TexData = []
    TexSize = []

    for i in range(Header[3]):
        Data = bs.read(">iiii")
        Tex.append([Data[1], Data[2], Data[3]])

    for i in range(Header[3]):
        bs.seek(Tex[i][2] + 12, 0)
        TexNames.append(bs.cstring())

    for i in range(Header[3]):
        bs.seek(Tex[i][0] + 12, 0)
        bs.seek(33, 1)
        Data = bs.read(">HBHHiii")
        TexData.append([Data[0], Data[1], Data[2], Data[3]])

    for i in range(Header[3] - 1):
        TexSize.append(TexData[i + 1][0] - TexData[i][0])
    TexSize.append(Header[2] / 0x100 - TexData[Header[3] - 1][0])

    for i in range(Header[3]):
        bs.seek(TexData[i][0] * 0x100 + headerSize + 12, 0)
        data = bs.read(int(TexSize[i] * 0x100))

        height = (TexData[i][2] + 1) * 8
        width  = (TexData[i][3] + 1) & 0x1FFF

        fmt = TexData[i][1]
        blockSize = None
        fourcc = None

        if fmt == 0x52:      # DXT1
            blockSize = 8
            fourcc = b"DXT1"
        elif fmt == 0x53:    # DXT3
            blockSize = 16
            fourcc = b"DXT3"
        elif fmt == 0x54:    # DXT5
            blockSize = 16
            fourcc = b"DXT5"
        elif fmt == 0x71:    # ATI2
            blockSize = 16
            fourcc = b"ATI2"
        elif fmt == 0x86:    # raw RGBA
            blockSize = 4
            fourcc = b"\0\0\0\0"
        else:
            raise ValueError(f"Unhandled image format {hex(fmt)} - {width}x{height} - {len(data)}")

        _w, _h = width, height
        start = 0
        mipCount = 0

        while True:
            if fourcc == b"\0\0\0\0":
                mipSize = _w * _h * blockSize
            else:
                bw = max(1, (_w + 3) // 4)
                bh = max(1, (_h + 3) // 4)
                mipSize = bw * bh * blockSize

            if start + mipSize > len(data):
                break

            start += mipSize
            mipCount += 1
            if _w == 1 and _h == 1:
                # still count the 1x1 mip
                break

            _w = max(1, _w // 2)
            _h = max(1, _h // 2)


        textures.append({
            "name": TexNames[i],
            "data": data,
            "mipCount": mipCount,
            "fourcc": fourcc,
            "width": width,
            "height": height,
            "size": len(data),
            "blockSize": blockSize,
        })

    return textures

# ------------------------------------------------------------
# DDS header
# ------------------------------------------------------------

def compute_top_mip_size(width, height, fourcc, blockSize):
    if fourcc == b"\0\0\0\0":
        return width * height * blockSize
    bw = max(1, (width + 3) // 4)
    bh = max(1, (height + 3) // 4)
    return bw * bh * blockSize

def build_dds_header(width, height, mipCount, fourcc, blockSize):
    dwSize = 124
    dwFlags = 0x0002100F  # CAPS | HEIGHT | WIDTH | PIXELFORMAT | LINEARSIZE
    dwHeight = height
    dwWidth = width
    dwPitchOrLinearSize = compute_top_mip_size(width, height, fourcc, blockSize)
    dwDepth = 0
    dwMipMapCount = mipCount if mipCount > 1 else 0
    dwReserved1 = (0,) * 11

    pf_dwSize = 32
    pf_dwFlags = 0x00000004  # DDPF_FOURCC
    pf_dwFourCC = struct.unpack("<I", fourcc)[0]
    pf_dwRGBBitCount = 0
    pf_dwRBitMask = 0
    pf_dwGBitMask = 0
    pf_dwBBitMask = 0
    pf_dwABitMask = 0

    dwCaps = 0x00001000  # DDSCAPS_TEXTURE
    if dwMipMapCount > 1:
        dwCaps |= 0x00400008  # COMPLEX | MIPMAP
    dwCaps2 = 0
    dwCaps3 = 0
    dwCaps4 = 0
    dwReserved2 = 0

    values = [
        dwSize,
        dwFlags,
        dwHeight,
        dwWidth,
        dwPitchOrLinearSize,
        dwDepth,
        dwMipMapCount,
        *dwReserved1,
        pf_dwSize,
        pf_dwFlags,
        pf_dwFourCC,
        pf_dwRGBBitCount,
        pf_dwRBitMask,
        pf_dwGBitMask,
        pf_dwBBitMask,
        pf_dwABitMask,
        dwCaps,
        dwCaps2,
        dwCaps3,
        dwCaps4,
        dwReserved2,
    ]
    header = b"DDS " + struct.pack("<" + "I" * len(values), *values)
    return header

# ------------------------------------------------------------
# XPR → DDS → Blender
# ------------------------------------------------------------

def load_xpr(filepath):
    filepath = os.path.abspath(filepath)

    data = read_maybe_chunklzx(filepath)
    br = BinReader(io.BytesIO(data), ">")
    textures = read_xpr_header(br)

    for tex in textures:
        # Untile first: mipCount from the header is an estimate, and the
        # DDS header must reflect however many mips we actually got.
        mips = UntileX360Image(
            tex["data"],
            tex["width"],
            tex["height"],
            tex["fourcc"],
            mipCount=tex["mipCount"],
        )

        if not mips:
            print(f"Skipping {tex['name']}: no mip levels could be untiled "
                  f"(format {tex['fourcc']!r}).")
            continue

        dds_header = build_dds_header(
            width=tex["width"],
            height=tex["height"],
            mipCount=len(mips),
            fourcc=tex["fourcc"],
            blockSize=tex["blockSize"],
        )

        tmp_dir = tempfile.gettempdir()
        dds_path = os.path.join(tmp_dir, tex["name"] + ".dds")

        with open(dds_path, "wb") as df:
            df.write(dds_header)
            for mip in mips:
                df.write(bytes(mip["data"]))

        img = bpy.data.images.load(dds_path)
        img.name = tex["name"]
        img.pack()

        requested = tex["mipCount"]
        note = "" if len(mips) == requested else f", reduced from {requested} requested"
        print(f"Imported and packed {tex['name']} as DDS "
              f"({len(mips)} mip level(s){note}).")
    return None