# SPDX-License-Identifier: LGPL-2.1-only
#
# Importer for SSX 2012's Android/mobile ".pvr" textures (PowerVR Texture
# container, PVR3 format). Unlike .gtf (PS3) and .xpr (Xbox), whose
# compressed pixel data (DXT1/DXT5) Blender's own DDS loader already
# understands, the .pvr files here wrap ETC1 -- a mobile-GPU compression
# format Blender cannot decode itself.
#
# Decoding ETC1 requires either a from-scratch block decompressor or
# Imagination Technologies' own PVRTexTool. This module shells out to
# PVRTexToolCLI (bundled with a PVRTexTool install) rather than the
# officially documented PVRTexLibPy Python API, because PVRTexLibPy ships as
# a compiled extension module built for one specific CPython ABI (observed:
# cp312-win_amd64) that generally will not match whatever Python version
# Blender itself bundles (Blender 4.5 ships 3.11) -- they are separate
# interpreters and the extension cannot be imported across that mismatch.
# The CLI tool is a standalone executable and has no such constraint.

import bpy
import os
import shutil
import struct
import subprocess
import tempfile

from .chunklzx import is_chunklzx, unpack_chunklzx


# --- PVR3 header (52 bytes, little-endian) ------------------------------
# magic(4) flags(4) pixelFormat(8) colourSpace(4) channelType(4) height(4)
# width(4) depth(4) numSurfaces(4) numFaces(4) numMipmaps(4) metaDataSize(4)
# Verified against a real SSX 2012 asset (elise's board diffuse: 64x128
# ETC1, 8 mips, header + mip chain size matched the file size exactly).

PVR3_MAGIC = 0x03525650  # "PVR\x03" read as a little-endian u32

# PixelFormat id (low 32 bits of the 64-bit field, high 32 bits zero) --
# only the value actually seen on SSX 2012 mobile assets is named here.
PVR_PIXEL_FORMAT_ETC1 = 6

PVR_COLOUR_SPACE_LINEAR = 0
PVR_COLOUR_SPACE_SRGB = 1


def read_pvr_header(data: bytes):
    if len(data) < 52:
        raise ValueError("File too small to contain a PVR3 header")

    (magic, flags, pixel_format, colour_space, channel_type,
     height, width, depth, num_surfaces, num_faces, num_mipmaps,
     meta_data_size) = struct.unpack("<IIQIIIIIIIII", data[:52])

    if magic != PVR3_MAGIC:
        raise ValueError(
            f"Not a PVR3 file (magic={magic:#x}). Legacy PVR2 files and "
            "other container versions aren't parsed here, but PVRTexToolCLI "
            "may still be able to decode them directly."
        )

    return {
        "flags": flags,
        "pixel_format": pixel_format,
        "colour_space": colour_space,
        "channel_type": channel_type,
        "width": width,
        "height": height,
        "depth": depth,
        "num_surfaces": num_surfaces,
        "num_faces": num_faces,
        "num_mipmaps": num_mipmaps,
        "meta_data_size": meta_data_size,
    }


# --- Locating PVRTexToolCLI ----------------------------------------------

def _candidate_cli_paths():
    env_override = os.environ.get("SSX_PVRTEXTOOLCLI")
    if env_override:
        yield env_override

    on_path = shutil.which("PVRTexToolCLI")
    if on_path:
        yield on_path

    # Confirmed layout on Windows: <root>\Imgtec\PowerVR_Tools\PVRTexTool\CLI\<arch>\PVRTexToolCLI.exe
    program_files_roots = [
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramFiles(x86)"),
    ]
    vendor_dirs = ("Imgtec", "Imagination Technologies")
    arch_dirs = ("Windows_x86_64", "Windows_x86_32")
    for root in program_files_roots:
        if not root:
            continue
        for vendor in vendor_dirs:
            for arch in arch_dirs:
                yield os.path.join(
                    root, vendor, "PowerVR_Tools", "PVRTexTool", "CLI", arch,
                    "PVRTexToolCLI.exe",
                )

    # Best-effort locations for other platforms -- unverified, PVRTexTool
    # has only actually been confirmed installed on Windows for this project.
    yield "/opt/Imagination Technologies/PowerVR_Tools/PVRTexTool/CLI/Linux_x86_64/PVRTexToolCLI"
    yield "/Applications/Imagination/PowerVR_Tools/PVRTexTool/CLI/OSX_x86/PVRTexToolCLI"


def find_pvrtextool_cli():
    """Return the path to PVRTexToolCLI if installed, else None."""
    for path in _candidate_cli_paths():
        if path and os.path.isfile(path):
            return path
    return None


# --- Decoding --------------------------------------------------------------

def decode_pvr_to_png(filepath, cli_path, out_path):
    # -d saves a decompressed copy alongside the (suppressed, -noout) .pvr
    # output; -shh keeps the CLI quiet so its stdout doesn't spam Blender's
    # console on every texture import.
    result = subprocess.run(
        [cli_path, "-i", filepath, "-d", out_path, "-noout", "-shh"],
        capture_output=True, text=True,
    )
    if result.returncode != 0 or not os.path.exists(out_path):
        message = result.stderr.strip() or result.stdout.strip() or "no output"
        raise RuntimeError(
            f"PVRTexToolCLI failed to decode '{filepath}' "
            f"(exit code {result.returncode}): {message}"
        )


def load_pvr(filepath):
    filepath = os.path.abspath(filepath)

    with open(filepath, "rb") as f:
        original = f.read()

    raw = unpack_chunklzx(original) if is_chunklzx(original) else original

    try:
        header = read_pvr_header(raw)
    except ValueError:
        header = None  # not fatal -- PVRTexToolCLI may still read it directly

    cli_path = find_pvrtextool_cli()
    if cli_path is None:
        raise RuntimeError(
            "PVRTexTool is required to decode .pvr textures (this format "
            "uses ETC1 compression, which Blender cannot decode natively). "
            "Install PVRTexTool from "
            "https://developer.imaginationtech.com/solutions/pvrtextool/ "
            "and make sure PVRTexToolCLI is on PATH, in its default install "
            "location, or pointed to via the SSX_PVRTEXTOOLCLI environment "
            "variable."
        )

    base_name = os.path.splitext(os.path.basename(filepath))[0]
    tmp_dir = tempfile.gettempdir()
    png_path = os.path.join(tmp_dir, base_name + ".png")

    # PVRTexToolCLI reads directly from disk, so if the source was
    # chunklzx-wrapped it needs a decompressed temp copy to point the CLI at.
    temp_src_path = None
    if raw is not original:
        temp_src_path = os.path.join(tmp_dir, base_name + "_decompressed.pvr")
        with open(temp_src_path, "wb") as f:
            f.write(raw)
    src_path = temp_src_path or filepath

    try:
        decode_pvr_to_png(src_path, cli_path, png_path)

        img = bpy.data.images.load(png_path)
        img.name = base_name
        if header is not None and header["colour_space"] == PVR_COLOUR_SPACE_LINEAR:
            img.colorspace_settings.name = "Non-Color"
        img.pack()
    finally:
        for p in (png_path, temp_src_path):
            if p:
                try:
                    os.remove(p)
                except OSError:
                    pass

    fmt = "ETC1" if header and header["pixel_format"] == PVR_PIXEL_FORMAT_ETC1 else "unknown format"
    print(f"Imported and packed '{base_name}' from PVR ({fmt}) via PVRTexToolCLI.")
    return img
