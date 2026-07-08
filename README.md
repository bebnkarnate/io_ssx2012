# SSX 2012 Importer

A Blender addon for importing assets from **SSX** (2012, EA Sports, Android/PS3/Xbox 360). It reads the game's proprietary `.geom`, `.crsf`, `.gtf`, `.xpr`, and `.pvr` formats directly and reconstructs meshes, skin weights, skeletons, and textures inside Blender.

## What it imports

- **Geometry + weights (`.geom` / `.crsf`)** — `File > Import > SSX (2012) > Geometry + Weights`. Reads a `.geom` mesh (positions, normals, UVs, triangle indices) and its matching `_meshpoly.crsf` file (per-vertex bone weights and bone names), builds the mesh, and assigns vertex groups.
- **Rig / Skeleton (`.crsf`)** — `File > Import > SSX (2012) > Rig / Skeleton`. Parses the skeleton's scene graph (`SGRF`) section, reconstructs the joint hierarchy and bind-pose transforms, and builds a Blender armature with correct bone positions, parenting, and roll — then parents the active mesh to it with an Armature modifier.
- **Textures (`.gtf` / `.xpr` / `.pvr`)** — `File > Import > SSX (2012) > Texture`. Three different platform-specific containers handled side by side, not one shared format: `.gtf` is PS3's texture format (`gtf.py`), `.xpr` is the Xbox family's "packed resource" texture format (`xpr.py`) — both converted into a DDS Blender can load directly — and `.pvr` is Android/mobile's PowerVR Texture container (`pvr.py`), wrapping ETC1-compressed pixel data that Blender can't decode natively (see below).

## Format notes

SSX 2012 assets are wrapped in an Xbox 360-era container (`RSF`/FourCC-tagged sections) and are frequently compressed with EA's `chunklzx` scheme — a chunked LZX container (`chunklzx.py`, decoder ported from libmspack's LZX implementation, see `reference/libmspack` submodule). `read_maybe_chunklzx()` transparently decompresses a file if needed before parsing.

Key reverse-engineered details baked into the importer:
- Section FourCCs are byte-swapped in this little-endian build of the format (it's originally a big-endian/PowerPC format), so magics are read with an endian-aware `BinReader.magic()`, not raw bytes.
- Each skeleton joint carries **two** 4x4 matrices: a parent-relative local transform and a world/armature-space bind transform (plus its precomputed inverse). Bone placement uses the world matrix — using the local one collapses every non-root bone near the skeleton root.
- The joint hierarchy is reconstructed from a per-joint `child_count` (depth-first child counter), not from an index field that turns out to be constant filler across every joint in real files.
- Bone tail/roll placement prefers the child with a substantial descendant subtree, aligned with the incoming bone direction — this avoids picking a nearby prop/twist/jiggle helper bone over the actual anatomical continuation (e.g. a spine bone reaching for a cosmetic "wing" attachment instead of the neck).
- `.pvr` decoding relies on **PVRTexToolCLI** from Imagination Technologies' free [PVRTexTool](https://developer.imaginationtech.com/solutions/pvrtextool/). `pvr.py` searches PATH, common install locations, and an `SSX_PVRTEXTOOLCLI` environment variable override for it; if it isn't installed, `.pvr` is simply left out of the texture-import file picker.

## Usage

1. Install as a Blender addon (Edit > Preferences > Add-ons > Install..., point at this folder or a zip of it).
2. `File > Import > SSX (2012)` submenu:
   - **Geometry + Weights (.geom/.crsf)** — pick the `_geo.geom` file; you'll then be prompted for the matching `_meshpoly.crsf` (or equivalent) weights file in the same folder.
   - **Rig / Skeleton (.crsf)** — with a mesh selected as the active object, pick the skeleton's `.crsf` file to build and parent an armature to it.
   - **Texture (.gtf/.xpr/.pvr)** — pick a texture file to load it into Blender.

## Requirements

- Blender 3.3+.
- For `.pvr` textures only: [PVRTexTool](https://developer.imaginationtech.com/solutions/pvrtextool/) installed (its `PVRTexToolCLI` needs to be on PATH, in a default install location, or pointed to via the `SSX_PVRTEXTOOLCLI` environment variable).

## Repository layout

- `__init__.py` — addon registration, operators/menu, `.geom` mesh reader, texture-container glue.
- `crsf_rig.py` — skeleton/rig importer (scene graph parsing, hierarchy + bind-pose reconstruction, armature building).
- `binreader.py` — small endian-aware binary reader used by all format parsers.
- `chunklzx.py` / `lzxd.py` — EA `chunklzx` container unpacking and LZX decompression.
- `gtf.py` / `xpr.py` — GTF/XPR texture container readers.
- `pvr.py` — PVR3 header parser and PVRTexToolCLI-backed ETC1 texture decoder.
- `reference/libmspack` — upstream [libmspack](https://github.com/kyz/libmspack) submodule, kept for reference during LZX reverse-engineering (not used at runtime).

## License

This project is licensed under the **GNU Lesser General Public License v2.1** (LGPL-2.1-only) — see [LICENSE](LICENSE) for the full text.

`lzxd.py` is a Python port of libmspack's LZX decoder (`mspack/lzxd.c` and related headers), © 2003-2023 Stuart Caie, also LGPL-2.1; see the file's header for details. `reference/libmspack` is the original upstream project, included as a submodule for reference only (not compiled/linked into the addon).
