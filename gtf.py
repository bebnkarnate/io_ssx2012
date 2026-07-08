# SPDX-License-Identifier: LGPL-2.1-only
import bpy
import struct
import os
import tempfile
import io
from . binreader import *
from .chunklzx import read_maybe_chunklzx

def read_gtf_header(br: BinReader):

    id_bytes = br.u8(4)
    if len(id_bytes) != 4 or not (id_bytes[0] == 1 and id_bytes[1] == 5):
        raise ValueError("Invalid GTF header")

    size      = br.u32()
    one       = br.i32()
    nul       = br.i32()
    dataOffset= br.u32()
    size2     = br.u32()
    _86       = br.u8()
    mipCount  = br.u8()

    if _86 == 134:
        fourcc = b"DXT1"
    elif _86 == 136:
        fourcc = b"DXT5"
    else:
        raise ValueError(f"Unknown textype value: {_86}")

    unkB      = br.u16()
    someInt   = br.u32()
    width     = br.u16()
    height    = br.u16()
    unk       = br.u32()

    return {
        "dataOffset": dataOffset,
        "mipCount": mipCount,
        "fourcc": fourcc,
        "width": width,
        "height": height,
    }

def build_dds_header(width, height, mipCount, fourcc, data_size):
    # DDS header is 128 bytes total
    # Reference: https://docs.microsoft.com/en-us/windows/win32/direct3ddds/dds-header
    dwSize = 124
    dwFlags = 0x0002100F  # CAPS | HEIGHT | WIDTH | PIXELFORMAT | LINEARSIZE
    dwHeight = height
    dwWidth = width
    dwPitchOrLinearSize = data_size
    dwDepth = 0
    dwMipMapCount = mipCount if mipCount > 1 else 0
    dwReserved1 = (0,) * 11

    # Pixel format
    pf_dwSize = 32
    pf_dwFlags = 0x00000004  # DDPF_FOURCC
    pf_dwFourCC = struct.unpack("<I", fourcc)[0]
    pf_dwRGBBitCount = 0
    pf_dwRBitMask = 0
    pf_dwGBitMask = 0
    pf_dwBBitMask = 0
    pf_dwABitMask = 0

    # Caps
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

def load_gtf(filepath):
    filepath = os.path.abspath(filepath)

    data = read_maybe_chunklzx(filepath)
    f = io.BytesIO(data)
    br = BinReader(f, ">")
    header = read_gtf_header(br)
    f.seek(header["dataOffset"])
    tex_data = f.read()  # all mip levels

    dds_header = build_dds_header(
        width=header["width"],
        height=header["height"],
        mipCount=header["mipCount"],
        fourcc=header["fourcc"],
        data_size=len(tex_data),
    )

    # Create temporary DDS file
    tmp_dir = tempfile.gettempdir()
    base_name = os.path.splitext(os.path.basename(filepath))[0]
    dds_path = os.path.join(tmp_dir, base_name + ".dds")

    with open(dds_path, "wb") as df:
        df.write(dds_header)
        df.write(tex_data)

    # Load DDS into Blender
    img = bpy.data.images.load(dds_path)
    img.name = base_name
    img.pack()  # pack into .blend

    try:
        os.remove(dds_path)
    except OSError:
        pass

    print(f"Imported and packed '{base_name}' as DDS, original deleted.")
    return img
