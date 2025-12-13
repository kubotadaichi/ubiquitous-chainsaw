# attach_head.py
import argparse
import json
import os
import bpy
from mathutils import Vector, Euler

import sys
print("RAW ARGV:", sys.argv)

def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)

def import_fbx(path: str):
    bpy.ops.import_scene.fbx(filepath=path)

def import_obj(path: str):
    # OBJは相対パスでテクスチャを参照しがちなので、作業ディレクトリを合わせるのが無難
    cwd = os.getcwd()
    os.chdir(os.path.dirname(path) or ".")
    try:
        bpy.ops.import_scene.obj(filepath=path)
    finally:
        os.chdir(cwd)

def import_gltf(path: str):
    bpy.ops.import_scene.gltf(filepath=path)

def find_armature():
    for obj in bpy.data.objects:
        if obj.type == "ARMATURE":
            return obj
    raise RuntimeError("Armature not found in template")

def find_mesh_objects(exclude_names=()):
    meshes = []
    for obj in bpy.data.objects:
        if obj.type == "MESH" and obj.name not in exclude_names:
            meshes.append(obj)
    return meshes

def find_by_hint(meshes, hint: str):
    hint = hint.lower()
    for m in meshes:
        if hint in m.name.lower():
            return m
    return None

def apply_decimate(obj, ratio: float):
    if ratio >= 1.0:
        return
    mod = obj.modifiers.new(name="Decimate", type='DECIMATE')
    mod.ratio = ratio
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=mod.name)

def load_calib(path: str | None):
    if not path:
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def apply_transform(obj, calib: dict | None):
    if not calib:
        return
    # 想定: {"scale":[s,s,s], "rotation_euler":[rx,ry,rz], "translation":[tx,ty,tz]}
    if "scale" in calib:
        sx, sy, sz = calib["scale"]
        obj.scale = Vector((sx, sy, sz))
    if "rotation_euler" in calib:
        rx, ry, rz = calib["rotation_euler"]
        obj.rotation_euler = Euler((rx, ry, rz), 'XYZ')
    if "translation" in calib:
        tx, ty, tz = calib["translation"]
        obj.location = Vector((tx, ty, tz))

def parent_to_head_bone(head_obj, armature_obj, head_bone_name: str):
    if head_bone_name not in armature_obj.data.bones:
        raise RuntimeError(f"Head bone '{head_bone_name}' not found. Bones: {[b.name for b in armature_obj.data.bones][:10]}...")

    # Keep Transformでボーンに親子付け
    bpy.ops.object.select_all(action='DESELECT')
    head_obj.select_set(True)
    armature_obj.select_set(True)
    bpy.context.view_layer.objects.active = armature_obj

    bpy.ops.object.mode_set(mode='POSE')
    armature_obj.data.bones.active = armature_obj.data.bones[head_bone_name]
    # pose boneを選択
    for pb in armature_obj.pose.bones:
        pb.bone.select = (pb.name == head_bone_name)

    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.parent_set(type='BONE', keep_transform=True)

def delete_template_head_mesh(armature_obj, head_bone_name: str):
    """
    テンプレの頭を「雑に消す」版:
    - 頭ボーンに近いメッシュだけ消したいが、完全自動は難しい。
    - ここでは名前ヒント（Head）で見つけたメッシュを削除するか、
      もしくは 'head' を含むメッシュ名を削除。
    """
    candidates = []
    for obj in bpy.data.objects:
        if obj.type == "MESH":
            n = obj.name.lower()
            if "head" in n or "face" in n:
                candidates.append(obj)

    # 候補がなければ何もしない（Unity側で頭を隠してもいい）
    for obj in candidates:
        bpy.data.objects.remove(obj, do_unlink=True)

def export_fbx(path: str):
    bpy.ops.export_scene.fbx(
        filepath=path,
        use_selection=False,                # シーン全体を書き出す
        object_types={'ARMATURE', 'MESH'},  # ★ これが超重要
        add_leaf_bones=False,
        bake_anim=False,
        apply_unit_scale=True,
        apply_scale_options='FBX_SCALE_ALL',
        use_space_transform=True,
        axis_forward='-Z',
        axis_up='Y',
        path_mode='COPY',                   # テクスチャ同梱
        embed_textures=True,
    )


def export_gltf(path: str):
    bpy.ops.export_scene.gltf(filepath=path, export_format='GLB')



def parse_after_double_dash(parser: argparse.ArgumentParser):
    # BlenderのargvにはBlender側の引数が混ざるので、`--`より後だけを使う
    if "--" in sys.argv:
        idx = sys.argv.index("--")
        script_argv = sys.argv[idx + 1:]
    else:
        script_argv = sys.argv[1:]
    return parser.parse_args(script_argv)

def main():
    ap = argparse.ArgumentParser(prog="attach_head.py")

    ap.add_argument("--template", required=True)
    ap.add_argument("--head", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--head_bone", default="mixamorig:Head")
    ap.add_argument("--calib", default=None)
    ap.add_argument("--delete_template_head", default="false")
    ap.add_argument("--decimate_ratio", type=float, default=1.0)

    args = parse_after_double_dash(ap)

    reset_scene()

    # 1) template import
    import_fbx(args.template)
    arm = find_armature()

    # 2) head import
    head_path = args.head.lower()
    before_meshes = set([o.name for o in bpy.data.objects if o.type == "MESH"])
    if head_path.endswith(".obj"):
        import_obj(args.head)
    elif head_path.endswith(".glb") or head_path.endswith(".gltf"):
        import_gltf(args.head)
    else:
        raise RuntimeError("Unsupported head format. Use .obj or .glb/.gltf")

    after_meshes = [o for o in bpy.data.objects if o.type == "MESH" and o.name not in before_meshes]
    if not after_meshes:
        raise RuntimeError("No mesh imported for head")

    # headメッシュが複数入ることがあるので、最大ポリゴンのものを採用
    def poly_count(obj):
        return len(obj.data.polygons)
    head_obj = sorted(after_meshes, key=poly_count, reverse=True)[0]

    # 3) optional decimate
    apply_decimate(head_obj, args.decimate_ratio)

    # 4) apply calib transform
    calib = load_calib(args.calib)
    apply_transform(head_obj, calib)

    # 5) parent to head bone
    parent_to_head_bone(head_obj, arm, args.head_bone)

    # 6) delete template head (optional)
    if str(args.delete_template_head).lower() in ("1","true","yes","y"):
        delete_template_head_mesh(arm, args.head_bone)

    # 7) export
    
    out_lower = args.out.lower()
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    if out_lower.endswith(".fbx"):
        export_fbx(args.out)
    elif out_lower.endswith(".glb") or out_lower.endswith(".gltf"):
        export_gltf(args.out)
    else:
        raise RuntimeError("Unsupported output format. Use .fbx or .glb")

if __name__ == "__main__":
    main()

