# SPDX-License-Identifier: LGPL-2.1-only
bl_info = {
    "name": "SSX 2012 Importer",
    "author": "bebnkarnate",
    "version": (0, 1, 0),
    "blender": (3, 3, 0),
    "location": "File > Import > (SSX 2012)",
    "description": "Import SSX 2012 assets",
    "category": "Import-Export",
}

from .binreader import *
from .chunklzx import read_maybe_chunklzx
from bpy.props import StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ImportHelper
from mathutils import Vector, Matrix
import bpy
import io
import os
import struct
import sys
import time

SSX_ICONS = None

def bit_vector(val, start, count):
    return (val >> start) & (1 << count) - 1


def decode_10bit_signed_normal(v):
    v = (v) - (512.0)
    if v < 0.0:
        v += 1023.0
    v /= 1023.0
    return 2 * (v) - 1


def decode_16bit_signed_normal(v):
    v = (v) - (32767.0)
    if v < 0.0:
        v += 65535.0
    v /= 65535.0
    return 2 * (v) - 1


# ---------------------- READ CRSF ---------------------


def read_crsf_weights(br: BinReader):
    # header (always LE)
    magic = br.magic()
    if magic != b"\0FSR":
        raise RuntimeError("Not a crsf file")

    big = br.u32()
    br.endian = ">" if big == 1 else "<"

    _48 = br.u64()

    weit = br.magic()
    if weit != b"WEIT":
        raise RuntimeError("WEIT section missing")

    version = br.u32()
    unk = br.u32()
    sectionSize = br.u32()
    unknown3 = br.u64()
    weightCount = br.u32()
    elementCount = br.u32()

    weights = []
    boneIDs = []

    for _ in range(elementCount):
        a, b, c, d = br.f32(4)
        weights.append((a, b, c, d))

    for _ in range(elementCount):
        a, b, c, d = br.u8(4)
        boneIDs.append((a, b, c, d))
    br.align16()

    return weights, boneIDs


def read_crsf_skeleton(br: BinReader):
    sktn = br.magic()
    if sktn != b"SKTN":
        raise RuntimeError("SKTN section missing")

    version = br.u32()
    sectionSize = br.u32()
    unknownHeader = br.u32()
    boneCount = br.u32()

    boneNames = []
    for _ in range(boneCount):
        strlen = br.u32()
        name = br.read(strlen).decode("ascii")
        br.skip(1)
        boneNames.append(name)

    bindMatrices = []
    for _ in range(boneCount):
        m = br.f32(16)
        bindMatrices.append(m)

    return boneNames, bindMatrices


def apply_weights(obj, weights, boneIDs, boneNames):
    mesh = obj.data

    # Create vertex groups
    vg = {}
    for name in boneNames:
        vg[name] = obj.vertex_groups.new(name=name)

    # Assign weights
    for vidx, (w, ids) in enumerate(zip(weights, boneIDs)):
        w0, w1, w2, w3 = w
        b0, b1, b2, b3 = ids

        if w0 > 0:
            vg[boneNames[b0]].add([vidx], w0, "REPLACE")
        if w1 > 0:
            vg[boneNames[b1]].add([vidx], w1, "REPLACE")
        if w2 > 0:
            vg[boneNames[b2]].add([vidx], w2, "REPLACE")
        if w3 > 0:
            vg[boneNames[b3]].add([vidx], w3, "REPLACE")


# ---------------------- READ GEOM ---------------------


def read_geom(filepath):
    verts = []
    normals = []
    uvs = []
    faces = []

    data = read_maybe_chunklzx(filepath)
    with io.BytesIO(data) as f:
        br = BinReader(f)
        # ---------- RSF_Header (always LE) ----------
        rsf = br.magic()
        if rsf != b"\0FSR":
            raise RuntimeError("Not an RSF/GEOM file (magic RSF not found)")

        bigEndianFlag = br.u32()
        _48 = br.u64()

        if bigEndianFlag == 1:
            br.endian = ">"
        elif bigEndianFlag == 0:
            br.endian = "<"
        else:
            raise RuntimeError("Invalid bigEndian flag in RSF header")

        # ---------- GEOM_Header ----------
        geom = br.magic()
        if geom != b"GEOM":
            raise RuntimeError("GEOM header magic not found")

        version = br.u32()
        blockSize = br.u32()
        dataOffset = br.u32()
        geom_count = br.u32()

        # ---------- VFMT_Header ----------
        vfmt = br.magic()
        if vfmt != b"VFMT":
            raise RuntimeError("VFMT header magic not found")

        vertexFormat = br.ssx_string()
        one = br.i32()

        # tokenize the stride definition

        adjuncts = vertexFormat.split(" ")

        adjunct_dict = {
            parts[0]: (parts[4], int(parts[1], 16))
            for adj in adjuncts
            for parts in [adj.split(":")]
        }

        # ---------- STRM_Header ----------
        strm = br.magic()
        if strm != b"STRM":
            raise RuntimeError("STRM header magic not found")

        br.skip(1)
        version = br.u32()
        vertexCount = br.u32()
        strideSize = br.u32()
        nul = br.u32()

        p0_info = adjunct_dict.get("p0")
        n0_info = adjunct_dict.get("n0")
        t0_info = adjunct_dict.get("t0")

        p0_type, p0_start = p0_info if p0_info else (None, 0)
        n0_type, n0_start = n0_info if n0_info else (None, 0)
        t0_type, t0_start = t0_info if t0_info else (None, 0)

        # Pre-verify UV configurations
        if t0_type is None:
            raise Exception("Unsupported type %s" % t0_type)

        # Localize Reader Functions for Max Performance
        br_tell = br.tell
        br_seek = br.seek
        br_f16 = br.f16
        br_f32 = br.f32
        br_i16 = br.i16
        br_u32 = br.u32

        start_pos = br_tell()

        for i in range(vertexCount):
            v_pos = start_pos + (i * strideSize)

            if p0_type:
                br_seek(v_pos + p0_start)
                match p0_type:
                    case "3f32" | "4f32":
                        x, y, z = br_f32(3)[:3]
                    case "_":
                        raise ValueError(f"Unknown pos format: {p0_type!r}")
                verts.append((-x, z, y))

            if n0_type:
                br_seek(v_pos + n0_start)
                match n0_type:
                    case "4s16n":
                        _nx, _ny, _nz = br_i16(3)
                        _nx = decode_16bit_signed_normal(_nx)
                        _ny = decode_16bit_signed_normal(_ny)
                        _nz = decode_16bit_signed_normal(_nz)
                    case "3s10n":
                        pack = br_u32()
                        _nx = decode_10bit_signed_normal(pack & 0x3FF)
                        _ny = decode_10bit_signed_normal((pack >> 10) & 0x3FF)
                        _nz = decode_10bit_signed_normal((pack >> 20) & 0x3FF)
                    case "3f32":
                        _nx, _ny, _nz = br_f32(3)
                    case _:
                        raise ValueError(f"Unknown normal format: {n0_type!r}")
                normals.append(Vector((-_nx, _nz, _ny)))

            if t0_type:
                br_seek(v_pos + t0_start)
                match t0_type:
                    case "2f16":
                        tx0, ty0 = br_f16(2)
                    case "2f32":
                        tx0, ty0 = br_f32(2)
                    case "2s16n":
                        tx0, ty0 = [t / 32768.0 for t in br_i16(2)]
                    # case "4s16n":
                        # tx0, ty0 = [t / 32767.0 for t in br_i16(2)]
                    case "4f16":
                        tx0, ty0 = br_f16(2)
                    case _:
                        raise ValueError(f"Unknown uv format: {t0_type!r}")
                uvs.append((tx0, 1.0 - ty0))

        br_seek(start_pos + (vertexCount * strideSize))
        br_u32()  # 'one'
        # ---------- XDNI_Header ----------
        indx = br.magic()
        if indx != b"INDX":
            raise RuntimeError("INDX header magic not found")

        br.skip(1)
        nul = br.u32()
        faceCount = br.u32()  # number of indices

        # ---------- ID16_Header ----------
        id16 = br.magic()
        if id16 != b"ID16":
            print("Warning: unexpected face magic:", magic)

        tri_count = faceCount // 3
        for _ in range(tri_count):
            i0 = br.u16()
            i1 = br.u16()
            i2 = br.u16()
            faces.append((i0, i1, i2))

        nul = br.i32()
        one = br.i32()

    return verts, normals, uvs, faces


def create_mesh(name, verts, normals, uvs, faces):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    for face in mesh.polygons:
        face.use_smooth = True

    # Set normals
    if normals:  # and len(normals) == len(mesh.vertices):
        loop_normals = [normals[loop.vertex_index] for loop in mesh.loops]
        mesh.normals_split_custom_set(loop_normals)
        mesh.update()

    # UVs
    if uvs:
        uv_layer = mesh.uv_layers.new(name="UV_0")
        for poly in mesh.polygons:
            for loop_index in poly.loop_indices:
                vidx = mesh.loops[loop_index].vertex_index
                uv_layer.data[loop_index].uv = uvs[vidx]

    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)

    return obj


class IMPORT_OT_select_crsf(Operator, ImportHelper):
    bl_idname = "import_scene.select_crsf"
    bl_label = "Select CRSF File"

    filename_ext = ".crsf"
    filter_glob: StringProperty(default="*.crsf", options={"HIDDEN"})

    geom_obj_name: StringProperty()
    geom_folder: StringProperty()

    def invoke(self, context, event):
        if not self.geom_folder.endswith(os.sep):
            self.filepath = self.geom_folder + os.sep
        return super().invoke(context, event)

    def execute(self, context):
        crsf_path = self.filepath
        obj = bpy.data.objects.get(self.geom_obj_name)

        data = read_maybe_chunklzx(crsf_path)
        with io.BytesIO(data) as f:
            br = BinReader(f)
            weights, boneIDs = read_crsf_weights(br)
            boneNames, bindMatrices = read_crsf_skeleton(br)
            apply_weights(obj, weights, boneIDs, boneNames)

        return {"FINISHED"}


class IMPORT_OT_ssx2012_geom(Operator, ImportHelper):
    bl_idname = "import_scene.ssx2012_geom"
    bl_label = "Geometry + Weights (.geom/.crsf)"
    bl_options = {"UNDO"}

    filename_ext = ".geom"
    filter_glob: StringProperty(default="*.geom", options={"HIDDEN"}, maxlen=255)

    def execute(self, context):
        start = time.perf_counter()
        try:
            verts, normals, uvs, faces = read_geom(self.filepath)
        except Exception as e:
            self.report({"ERROR"}, f"Failed to import: {e}")
            return {"CANCELLED"}

        name = os.path.splitext(os.path.basename(self.filepath))[0]
        geom_obj = create_mesh(name, verts, normals, uvs, faces)
        end = time.perf_counter()

        self.report({"INFO"}, f"Imported geom in {(end - start):.6f}s")

        result = bpy.ops.import_scene.select_crsf(
            "INVOKE_DEFAULT",
            geom_obj_name=geom_obj.name,
            geom_folder=os.path.dirname(self.filepath),
        )

        # self.report({'INFO'}, f"Imported SSX 2012 GEOM: {name}")
        return {"FINISHED"}


class IMPORT_OT_gtf(Operator, ImportHelper):
    bl_idname = "import_scene.ssx2012_gtf"
    bl_label = "Texture (.gtf/.xpr/.pvr)"
    bl_options = {"UNDO"}

    filename_ext = ""
    filter_glob: StringProperty(default="*.gtf;*.xpr;*.pvr", options={"HIDDEN"}, maxlen=255)

    def invoke(self, context, event):
        # .pvr needs PVRTexToolCLI to decode; if it isn't installed, drop
        # *.pvr from the file browser filter instead of offering a file type
        # that would just fail with an error when picked.
        from .pvr import find_pvrtextool_cli

        if find_pvrtextool_cli() is None:
            self.filter_glob = "*.gtf;*.xpr"
        return super().invoke(context, event)

    def execute(self, context):
        name, ext = os.path.splitext(os.path.basename(self.filepath))

        if ext == ".gtf":
            from .gtf import load_gtf

            load_gtf(self.filepath)
        elif ext == ".xpr":
            from .xpr import load_xpr

            load_xpr(self.filepath)
        elif ext == ".pvr":
            from .pvr import load_pvr

            try:
                load_pvr(self.filepath)
            except RuntimeError as e:
                self.report({"ERROR"}, str(e))
                return {"CANCELLED"}
        else:
            self.report({"ERROR"}, f"Unrecognized texture extension: {ext}")
            return {"CANCELLED"}

        self.report({"INFO"}, f"Imported SSX 2012 texture: {name}")
        return {"FINISHED"}


class IMPORT_OT_crsf_rig(Operator, ImportHelper):
    bl_idname = "import_scene.ssx2012_crsf_rig"
    bl_label = "Rig / Skeleton (.crsf)"
    bl_options = {"UNDO"}

    filename_ext = ".crsf"
    filter_glob: StringProperty(default="*.crsf", options={"HIDDEN"}, maxlen=255)

    def execute(self, context):
        from .crsf_rig import import_crsf_skeleton

        import_crsf_skeleton(self.filepath)

        # <-- FIX 4: Extracted name so the report below doesn't crash with a NameError
        name = os.path.splitext(os.path.basename(self.filepath))[0]
        self.report({"INFO"}, f"Imported SSX 2012 CRSF rig: {name}")
        return {"FINISHED"}


class Ssx2012ObjectOperatorsMenu(bpy.types.Menu):
    bl_idname = "IMPORT_MT_ssx2012_menu"  # <-- FIX 3: Defined an explicit bl_idname
    bl_label = "SSX (2012)"

    def draw(self, context):
        layout = self.layout  # <-- FIX 2: declared layout so it doesn't fail
        layout.operator(
            IMPORT_OT_ssx2012_geom.bl_idname, text=IMPORT_OT_ssx2012_geom.bl_label
        )
        layout.operator(IMPORT_OT_crsf_rig.bl_idname, text=IMPORT_OT_crsf_rig.bl_label)

        from .pvr import find_pvrtextool_cli

        texture_label = "Texture (.gtf/.xpr/.pvr)" if find_pvrtextool_cli() else "Texture (.gtf/.xpr)"
        layout.operator(IMPORT_OT_gtf.bl_idname, text=texture_label)


def menu_func_import(self, context):
    # 0 is Blender's "no icon" sentinel -- fall back to it instead of a
    # KeyError if the icon failed to load (missing/corrupt PNG), since this
    # draw callback runs every time the File menu opens, not just once.
    icon_id = SSX_ICONS["SSX2012"].icon_id if SSX_ICONS and "SSX2012" in SSX_ICONS else 0

    self.layout.menu(
        Ssx2012ObjectOperatorsMenu.bl_idname,  # Referenced explicit bl_idname
        text="SSX (2012)",
        icon_value=icon_id,
    )


classes = (
    Ssx2012ObjectOperatorsMenu,
    IMPORT_OT_ssx2012_geom,
    IMPORT_OT_select_crsf,
    IMPORT_OT_crsf_rig,
    IMPORT_OT_gtf,
)


def register():
    # Setup custom icons first. Guard against double-registration (e.g. a
    # stray register() call without a matching unregister()) leaking the
    # previous preview collection, and don't let a broken icon (missing/
    # corrupt PNG) block the actual import operators from registering --
    # menu_func_import() already falls back to icon 0 ("no icon") if this
    # collection ends up without "SSX2012" in it.
    global SSX_ICONS
    if SSX_ICONS is not None:
        bpy.utils.previews.remove(SSX_ICONS)
        SSX_ICONS = None

    try:
        SSX_ICONS = bpy.utils.previews.new()
        script_dir = os.path.dirname(os.path.abspath(__file__))
        icon_path = os.path.join(script_dir, "icons", "ssx2012.png")

        if os.path.exists(icon_path):
            SSX_ICONS.load("SSX2012", icon_path, "IMAGE")
        else:
            print(f"Warning: Icon missing at {icon_path}")
    except Exception as e:
        print(f"Warning: failed to set up SSX2012 icon: {e}")

    # Idempotent class registration: a stray register() call without a
    # matching unregister() first (e.g. during script-reload workflows)
    # would otherwise raise ValueError on the first already-registered
    # class and abort registration partway through.
    for myclass in classes:
        try:
            bpy.utils.unregister_class(myclass)
        except (RuntimeError, ValueError):
            pass
        bpy.utils.register_class(myclass)

    try:
        bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    except ValueError:
        pass
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)

    for myclass in classes:
        bpy.utils.unregister_class(myclass)

    global SSX_ICONS
    if SSX_ICONS is not None:
        bpy.utils.previews.remove(SSX_ICONS)
        SSX_ICONS = None


if __name__ == "__main__":
    register()
