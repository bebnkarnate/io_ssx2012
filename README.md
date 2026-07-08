# SSX 2012 Importer

A Blender addon for importing assets from **SSX** (2012, EA Sports, Android/PS3/Xbox 360). It reads the game's proprietary `.geom`, `.crsf`, `.gtf`, and `.xpr` formats directly and reconstructs meshes, skin weights, skeletons, and textures inside Blender.

## What it imports

- **Geometry + weights (`.geom` / `.crsf`)** — `File > Import > SSX (2012) > Geometry + Weights`. Reads a `.geom` mesh (positions, normals, UVs, triangle indices) and its matching `_meshpoly.crsf` file (per-vertex bone weights and bone names), builds the mesh, and assigns vertex groups.
- **Rig / Skeleton (`.crsf`)** — `File > Import > SSX (2012) > Rig / Skeleton`. Parses the skeleton's scene graph (`SGRF`) section, reconstructs the joint hierarchy and bind-pose transforms, and builds a Blender armature with correct bone positions, parenting, and roll — then parents the active mesh to it with an Armature modifier.
- **Textures (`.gtf` / `.xpr`)** — `File > Import > SSX (2012) > Texture`. Converts platform-native DXT1/DXT5 texture containers into a DDS Blender can load directly: `.gtf` is PS3's texture format (`gtf.py`), `.xpr` is the Xbox family's "packed resource" texture format (`xpr.py`) — two different platform-specific containers handled side by side, not one shared format.

## Format notes

SSX 2012 assets are wrapped in an Xbox 360-era container (`RSF`/FourCC-tagged sections) and are frequently compressed with EA's `chunklzx` scheme — a chunked LZX container (`chunklzx.py`, decoder ported from libmspack's LZX implementation, see `reference/libmspack` submodule). `read_maybe_chunklzx()` transparently decompresses a file if needed before parsing.

Key reverse-engineered details baked into the importer:
- Section FourCCs are byte-swapped in this little-endian build of the format (it's originally a big-endian/PowerPC format), so magics are read with an endian-aware `BinReader.magic()`, not raw bytes.
- Each skeleton joint carries **two** 4x4 matrices: a parent-relative local transform and a world/armature-space bind transform (plus its precomputed inverse). Bone placement uses the world matrix — using the local one collapses every non-root bone near the skeleton root.
- The joint hierarchy is reconstructed from a per-joint `child_count` (depth-first child counter), not from an index field that turns out to be constant filler across every joint in real files.
- Bone tail/roll placement prefers the child with a substantial descendant subtree, aligned with the incoming bone direction — this avoids picking a nearby prop/twist/jiggle helper bone over the actual anatomical continuation (e.g. a spine bone reaching for a cosmetic "wing" attachment instead of the neck).

## Usage

1. Install as a Blender addon (Edit > Preferences > Add-ons > Install..., point at this folder or a zip of it).
2. `File > Import > SSX (2012)` submenu:
   - **Geometry + Weights (.geom/.crsf)** — pick the `_geo.geom` file; you'll then be prompted for the matching `_meshpoly.crsf` (or equivalent) weights file in the same folder.
   - **Rig / Skeleton (.crsf)** — with a mesh selected as the active object, pick the skeleton's `.crsf` file to build and parent an armature to it.
   - **Texture (.gtf/.xpr)** — pick a texture file to load it into Blender.

## Requirements

- Blender 3.3+.

## Repository layout

- `__init__.py` — addon registration, operators/menu, `.geom` mesh reader, texture-container glue.
- `crsf_rig.py` — skeleton/rig importer (scene graph parsing, hierarchy + bind-pose reconstruction, armature building).
- `binreader.py` — small endian-aware binary reader used by all format parsers.
- `chunklzx.py` / `lzxd.py` — EA `chunklzx` container unpacking and LZX decompression.
- `gtf.py` / `xpr.py` — GTF/XPR texture container readers.
- `reference/libmspack` — upstream [libmspack](https://github.com/kyz/libmspack) submodule, kept for reference during LZX reverse-engineering (not used at runtime).
