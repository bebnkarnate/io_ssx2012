# SPDX-License-Identifier: LGPL-2.1-only
import os
import bpy
import struct
import io
from mathutils import Matrix, Vector
from . binreader import *
from .chunklzx import read_maybe_chunklzx

def build_hierarchy_from_childcount(joints):
    """
    Returns a list of parent indices for each joint,
    using childCount to reconstruct a depth-first tree.
    """
    parents = [-1] * len(joints)
    stack = []  # each entry: (joint_index, remaining_children)

    for i, j in enumerate(joints):
        # Assign parent from top of stack
        if stack:
            parent_index, remaining = stack[-1]
            parents[i] = parent_index

            # Decrement the remaining children counter
            stack[-1] = (parent_index, remaining - 1)

            # Use <= 0 to prevent off-by-one errors from permanently trapping nodes
            # if the child_count data is slightly malformed.
            while stack and stack[-1][1] <= 0:
                stack.pop()

        # Push this joint if it has children
        if j["child_count"] > 0:
            stack.append((i, j["child_count"]))

    return parents


# The section magics are FourCCs that get byte-swapped when the asset is
# saved little-endian (this file is an Xbox 360/PowerPC format ported to a
# little-endian platform), so they must be read with BinReader.magic()
# (which un-swaps based on br.endian), never as raw bytes.
def read_header(br: BinReader):
    magic = br.magic()
    if magic != b"\x00FSR":
        raise ValueError("Not a RSF/CRSF file")
    big_endian_flag = br.u32()
    _48 = br.u64()

    # adjust endianness
    if big_endian_flag == 1:
        br.endian = ">"
    elif big_endian_flag == 0:
        br.endian = "<"
    else:
        raise ValueError("Invalid endian flag")

    return big_endian_flag


def skip_view_section(br: BinReader):
    section_magic = br.magic()
    if section_magic != b"WEIT":
        raise ValueError("Expected WEIT section")
    version = br.u32()
    unk = br.u32()
    section_size = br.u32()
    unknown3_0 = br.u32()
    unknown3_1 = br.u32()
    weight_count = br.u32()
    element_count = br.u32()

    if element_count > 0:
        # vertexWeights[section.elementCount] (4 floats each)
        br.read(element_count * 4 * 4)
        # boneIDs[section.elementCount] (4 bytes each)
        br.read(element_count * 4)

    br.align16()


def read_sktn_section(br: BinReader):
    # "SKTN" skeleton header
    magic = br.magic()
    if magic != b"SKTN":
        # Not fatal for our purposes; seek back so caller can handle
        br.seek(-4, 1)
        return None

    version = br.u32()
    section_size = br.u32()
    unknown_header = br.u32()
    bone_count = br.u32()

    names = []
    matrices = []

    if bone_count > 0:
        # BoneNames
        for _ in range(bone_count):
            names.append(br.ssx_string())

        # BoneTransforms (Matrix4x4 each)
        for _ in range(bone_count):
            vals = br.f32(16)
            matrices.append(vals)

    br.align16()
    return {"bone_count": bone_count, "names": names, "matrices": matrices}


def read_sgnode_group(br: BinReader):
    some_count = br.u32()
    size = br.u32()
    type_bytes = br.u8(size + 1)
    unkA = br.u32()
    name = br.ssx_string()
    br.align16()
    unkB = br.u32()
    unkC = br.u32()
    return {
        "some_count": some_count,
        "type": bytes(type_bytes).decode("ascii", errors="replace"),
        "name": name,
    }


def read_transform_data(br: BinReader):
    t_type = br.u32()
    unkA = br.u32()
    name = br.ssx_string()
    x = br.f32()
    y = br.f32()
    z = br.f32()
    return {
        "type": t_type,
        "unkA": unkA,
        "name": name,
        "vec": (x, y, z),
    }


def read_sgnode_transform(br: BinReader):
    unkA = br.u32()
    type_str = br.ssx_string()
    unkB = br.u32()
    name = br.ssx_string()
    br.read(1)  # pad
    unkC = br.u32()
    unkD = br.u32()
    transform_count = br.u32()
    transforms = [read_transform_data(br) for _ in range(transform_count)]
    br.read(1)  # pad
    unkE = br.u32()
    unkF = br.u32()
    matrix_bytes = br.read(64)  # 16 floats, but template says uchar[64]; we ignore
    return {
        "type": type_str,
        "name": name,
        "transforms": transforms,
    }


def read_sgnode_joint(br: BinReader):
    type_str = br.ssx_string()
    unkB = br.u32()
    name = br.ssx_string()
    br.read(1)  # pad

    # These two u16 fields looked like parent indices at first glance, but
    # every joint in a real file carries the same constant values (0x1000 /
    # 0x0100) -- they are flags/padding, not hierarchy data. The real parent
    # linkage comes from child_count below (see build_hierarchy_from_childcount).
    unused_flag1 = br.u16()
    unused_flag2 = br.u16()
    unkD = br.u32()
    transform_count = br.u32()
    transforms = [read_transform_data(br) for _ in range(transform_count)]
    br.read(1)  # pad
    unkF = br.u32()
    unkG = br.u32()

    # Parent-relative (local) bind matrix. File convention is row-vectors
    # with translation in the last row (v' = v @ M). Only equal to
    # extra_mats[1] for the root joint (where local == world) -- do not use
    # this for placing bones, it collapses every limb near the origin.
    local_vals = br.f32(16)

    unkH = br.u32()

    # extra_mats[0] is always identity in practice (unused scale slot).
    # extra_mats[1] is the WORLD/armature-space bind matrix -- this is what
    # bone head/tail placement must use.
    # extra_mats[2] is exactly the inverse of extra_mats[1] (likely the
    # engine's precomputed inverse-bind matrix for skinning). We still have
    # to read all three to stay aligned with the byte stream.
    extra_mats = [br.f32(16) for _ in range(3)]

    unkI = br.u32()
    child_count = br.u32()

    return {
        "type": type_str,
        "name": name,
        "local_matrix": local_vals,
        "matrix": extra_mats[1],
        "extra_mats": extra_mats,
        "child_count": child_count,
    }


def read_sgrf_section(br: BinReader):
    magic = br.magic()
    if magic != b"SGRF":
        raise ValueError("Expected SGRF section")
    nul = br.u32()
    size = br.u32()

    nodegroup = read_sgnode_group(br)
    nodetransforms = [read_sgnode_transform(br) for _ in range(2)]
    random_four = br.u32()

    joints = []
    # while ((FTell()+4 < FileSize()) && (ReadUInt(FTell()) == 0x0B))
    while br.tell() + 4 < br.filesize():
        val = br.peek_u32()
        if val is None or val != 0x0B:
            break
        joint = read_sgnode_joint(br)
        joints.append(joint)

    return {
        "nodegroup": nodegroup,
        "nodetransforms": nodetransforms,
        "joints": joints,
    }


# Game axes -> Blender axes: (x, y, z) -> (-x, z, y). Same convention used
# for mesh verts/normals elsewhere in this addon. This 3x3 map is orthogonal
# and involutory (AXIS_FLIP @ AXIS_FLIP == identity), so it is its own inverse
# and can be used directly to conjugate rotation matrices.
AXIS_FLIP = Matrix((
    (-1.0, 0.0, 0.0, 0.0),
    (0.0, 0.0, 1.0, 0.0),
    (0.0, 1.0, 0.0, 0.0),
    (0.0, 0.0, 0.0, 1.0),
))


def joint_matrix_to_blender(vals):
    """Convert a joint's raw 16-float bind matrix (file convention: row
    vectors, translation in the last row) into a mathutils.Matrix in Blender
    space (column vectors, translation in the last column).

    Transposing the whole 4x4 turns a row-vector matrix into the equivalent
    column-vector one; conjugating by AXIS_FLIP then remaps both the
    rotation and the translation into Blender's axis convention in one step.
    """
    file_m = Matrix((
        (vals[0], vals[1], vals[2], vals[3]),
        (vals[4], vals[5], vals[6], vals[7]),
        (vals[8], vals[9], vals[10], vals[11]),
        (vals[12], vals[13], vals[14], vals[15]),
    ))
    m = file_m.transposed()
    return AXIS_FLIP @ m @ AXIS_FLIP


# ------------------------------------------------------------------------
# Armature creation
# ------------------------------------------------------------------------

MIN_BONE_LENGTH = 0.01


def create_armature_from_joints(joints, armature_name="ImportedSkeleton"):
    parents = build_hierarchy_from_childcount(joints)

    children = [[] for _ in joints]
    for i, p in enumerate(parents):
        if p != -1:
            children[p].append(i)

    # Precompute every joint's Blender-space bind matrix up front (order-
    # independent), so tail placement can freely look at child/parent heads
    # regardless of array order.
    blender_mats = [joint_matrix_to_blender(j["matrix"]) for j in joints]
    heads = [m.translation.copy() for m in blender_mats]

    # Total descendant count per joint. A branch point (e.g. a spine bone)
    # often also carries cosmetic/prop attachments (board wings, packs,
    # jiggle helpers) as direct children -- those are leaves, while the real
    # skeletal continuation (neck, shoulder->arm->hand...) always has further
    # descendants. This tells the two apart without relying on bone names.
    subtree_size = [0] * len(joints)
    for i in reversed(range(len(joints))):
        for c in children[i]:
            subtree_size[i] += 1 + subtree_size[c]

    # A single trailing helper (e.g. a twist bone with one jiggle bone under
    # it) still has subtree_size 1 -- that's not a "real" continuation, just
    # a short accessory. Require at least 2 descendants to count as a
    # substantial branch, otherwise the twist helper can out-rank the actual
    # limb continuation once direction alignment is factored in below.
    SUBSTANTIAL_SUBTREE = 2

    def pick_tail(i):
        candidates = [c for c in children[i] if subtree_size[c] >= SUBSTANTIAL_SUBTREE] or children[i]
        candidates = [c for c in candidates if (heads[c] - heads[i]).length > MIN_BONE_LENGTH] or \
            [c for c in children[i] if (heads[c] - heads[i]).length > MIN_BONE_LENGTH]

        if candidates:
            incoming = None
            p = parents[i]
            if p != -1:
                d = heads[i] - heads[p]
                if d.length > MIN_BONE_LENGTH:
                    incoming = d.normalized()

            if incoming is not None:
                # Prefer whichever candidate continues the incoming bone's
                # direction (the natural next segment) over one that merely
                # happens to be far away (a prop hanging off to the side).
                best = max(candidates, key=lambda c: incoming.dot((heads[c] - heads[i]).normalized()))
            else:
                # No parent (root) to derive a direction from -- farthest
                # child is the best available guess.
                best = max(candidates, key=lambda c: (heads[c] - heads[i]).length)
            return heads[best]

        p = parents[i]
        if p != -1:
            direction = heads[i] - heads[p]
            if direction.length > MIN_BONE_LENGTH:
                return heads[i] + direction.normalized() * 0.1

        return heads[i] + Vector((0.0, 0.1, 0.0))

    bpy.ops.object.add(type='ARMATURE', enter_editmode=True)
    arm_obj = bpy.context.object
    arm_obj.name = armature_name
    arm = arm_obj.data
    arm.name = armature_name + "_Data"

    bones = arm.edit_bones
    bone_map = [None] * len(joints)

    for i, j in enumerate(joints):
        b = bones.new(j["name"] if j["name"] else f"Bone_{i}")
        b.head = heads[i]
        b.tail = pick_tail(i)

        p = parents[i]
        if p != -1:
            b.parent = bone_map[p]
            b.use_connect = False

        # Align roll to the joint's own bind-pose Z axis (converted to
        # Blender space) so the rest pose's twist matches the source rig,
        # instead of Blender's arbitrary auto-roll -- this is what removes
        # the need for a corrective constraint on rotation.
        up_hint = blender_mats[i].to_3x3() @ Vector((0.0, 0.0, 1.0))
        b.align_roll(up_hint)

        bone_map[i] = b

    bpy.ops.object.mode_set(mode='OBJECT')
    return arm_obj


# ------------------------------------------------------------------------
# Main import function
# ------------------------------------------------------------------------

def import_crsf_skeleton(filepath):
    obj = bpy.context.active_object
    data = read_maybe_chunklzx(filepath)
    with io.BytesIO(data) as f:
        br = BinReader(f, "<")

        read_header(br)
        skip_view_section(br)
        sktn = read_sktn_section(br)  # we don't strictly need it, but nice to have

        # Now SGRF section with joints
        sgrf = read_sgrf_section(br)
        joints = sgrf["joints"]

    if not joints:
        raise ValueError("No joints found in SGRF section")

    name = os.path.splitext(os.path.basename(filepath))[0]
    arm_obj = create_armature_from_joints(joints, armature_name=name)

    # Ensure we have an active object
    if obj is None:
        print("No active object selected")
        return

    # Ensure it's a mesh
    if obj.type != 'MESH':
        print(f"Selected object '{obj.name}' is not a mesh")
        return

    # Parent mesh to armature
    obj.parent = arm_obj
    obj.parent_type = 'ARMATURE'

    # Add Armature modifier (or reuse existing one)
    mod = obj.modifiers.get("Armature")
    if mod is None:
        mod = obj.modifiers.new(name="Armature", type='ARMATURE')

    mod.object = arm_obj

    print(f"Mesh '{obj.name}' parented to armature '{arm_obj.name}' and modifier assigned.")
    print(f"Imported {len(joints)} joints into armature '{arm_obj.name}'")
