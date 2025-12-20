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
    # GLTFインポート後、カメラ・ライト・Emptyオブジェクトを削除
    before_objects = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)

    # インポートされたオブジェクトのうち、メッシュ以外を削除
    imported_objects = set(bpy.data.objects) - before_objects
    for obj in imported_objects:
        if obj.type not in ('MESH', 'ARMATURE'):
            obj_name = obj.name
            obj_type = obj.type
            bpy.data.objects.remove(obj, do_unlink=True)
            print(f"Removed non-mesh object: {obj_name} (type: {obj_type})")

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

def rigid_skin_to_bone(head_obj, armature_obj, bone_name: str):
    """
    GLB(glTF)での「ボーン親子付け」が環境によって崩れることがあるため、
    頭メッシュをヘッドボーンに 100% ウェイトでスキニングして追従させる。
    """
    if bone_name not in armature_obj.data.bones:
        raise RuntimeError(
            f"Head bone '{bone_name}' not found. Bones: {[b.name for b in armature_obj.data.bones][:10]}..."
        )

    # 念のためRESTポーズにしてからバインドする
    armature_obj.data.pose_position = 'REST'

    # HeadメッシュにArmatureモディファイアを追加（既存があれば再利用）
    arm_mod = None
    for mod in head_obj.modifiers:
        if mod.type == 'ARMATURE':
            arm_mod = mod
            break
    if arm_mod is None:
        arm_mod = head_obj.modifiers.new(name="Armature", type='ARMATURE')
    arm_mod.object = armature_obj

    # Headボーンに 100% ウェイト
    vg = head_obj.vertex_groups.get(bone_name)
    if vg is None:
        vg = head_obj.vertex_groups.new(name=bone_name)
    all_verts = list(range(len(head_obj.data.vertices)))
    if all_verts:
        vg.add(all_verts, 1.0, 'REPLACE')

    # オブジェクト親はArmatureに（keep_transformで見た目維持）
    bpy.ops.object.select_all(action='DESELECT')
    head_obj.select_set(True)
    armature_obj.select_set(True)
    bpy.context.view_layer.objects.active = armature_obj
    bpy.ops.object.parent_set(type='OBJECT', keep_transform=True)

def resolve_bone_name(armature_obj, requested: str) -> str:
    requested = (requested or "").strip()
    if not requested:
        raise RuntimeError("head_bone is empty")

    bones = [b.name for b in armature_obj.data.bones]
    if requested in armature_obj.data.bones:
        return requested

    base = requested.split(":", 1)[1] if ":" in requested else requested
    base_lower = base.lower()

    exact_segment_matches = [n for n in bones if n.split(":", 1)[-1].lower() == base_lower]
    if len(exact_segment_matches) == 1:
        chosen = exact_segment_matches[0]
        print(f"NOTE: head bone '{requested}' not found; using '{chosen}'")
        return chosen
    if len(exact_segment_matches) > 1:
        chosen = sorted(exact_segment_matches, key=len)[0]
        print(f"NOTE: head bone '{requested}' not found; using '{chosen}' from {exact_segment_matches}")
        return chosen

    exact_name_matches = [n for n in bones if n.lower() == base_lower]
    if len(exact_name_matches) == 1:
        chosen = exact_name_matches[0]
        print(f"NOTE: head bone '{requested}' not found; using '{chosen}'")
        return chosen

    head_like = [n for n in bones if "head" in n.lower()]
    raise RuntimeError(
        f"Head bone '{requested}' not found. "
        f"Try one of: {head_like[:20]} (total {len(head_like)})."
    )

def delete_template_head_mesh(armature_obj, head_bone_name: str):
    """
    テンプレの頭を「雑に消す」版:
    - 頭ボーンに近いメッシュだけ消したいが、完全自動は難しい。
    - ここでは名前ヒント（Head）で見つけたメッシュを削除するか、
      もしくは 'head' を含むメッシュ名を削除。
    - Icosphere(デバッグ用の球)も削除
    """
    print("DEBUG: delete_template_head_mesh - All MESH objects in scene:")
    for obj in bpy.data.objects:
        if obj.type == "MESH":
            print(f"  - {obj.name} (lower: {obj.name.lower()})")

    candidates = []
    for obj in bpy.data.objects:
        if obj.type == "MESH":
            n = obj.name.lower()
            # "body" まで消すとテンプレ全体が消えることがあるので除外する
            if "head" in n or "face" in n or "hair" in n or "eye" in n or "skull" in n or "beard" in n or "ico" in n or "sphere" in n or "body" in n:
                candidates.append(obj)
                print(f"DEBUG: Matched deletion candidate: {obj.name}")

    print(f"DEBUG: Total deletion candidates: {len(candidates)}")
    # 候補がなければ何もしない（Unity側で頭を隠してもいい）
    for obj in candidates:
        print(f"Deleting template mesh: {obj.name}")
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


def export_gltf(path: str, selected_only: bool = False):
    # GLBエクスポート時はメッシュとアーマチュアのみエクスポート
    # カメラ、ライト、Emptyオブジェクトなどを除外
    kwargs = dict(
        filepath=path,
        export_format='GLB',
        use_selection=selected_only,
        export_cameras=False,
        export_lights=False,
        export_extras=False,
        export_yup=True,  # Y-up座標系に変換
        export_apply=False,  # スケール正規化済みの想定（必要な場合だけTrueにする）
        export_skins=True,
        # Blender再インポート時の不要な補助オブジェクト（例: Icosphere）を抑制しやすい
        export_armature_object_remove=True,
        export_all_influences=True,
        export_morph=True,
    )

    # Blenderのバージョン差で未対応の引数があるので、対応分だけ渡す
    try:
        props = bpy.ops.export_scene.gltf.get_rna_type().properties
        supported = {p.identifier for p in props}
        filtered = {k: v for k, v in kwargs.items() if k in supported}
        dropped = sorted(set(kwargs.keys()) - set(filtered.keys()))
        if dropped:
            print(f"NOTE: Dropped unsupported glTF export args: {dropped}")
        bpy.ops.export_scene.gltf(**filtered)
    except Exception:
        # get_rna_type() が取れない環境向けフォールバック
        bpy.ops.export_scene.gltf(**kwargs)


def export_gltf_normalized(path: str, armature_obj, mesh_objs: list, export_selected_only: bool = True):
    """
    FBX由来のArmature scale=0.01 を含んだままglTFに出すと、ビューア側でスキンが崩れることがある。
    ここでは一時複製を作り、スケールだけ焼き込んで (scale=1) から選択エクスポートする。
    """
    tmp_col = bpy.data.collections.new("TMP_GLB_EXPORT")
    bpy.context.scene.collection.children.link(tmp_col)

    def deep_copy_object(obj):
        obj_copy = obj.copy()
        if obj.data is not None:
            obj_copy.data = obj.data.copy()
        obj_copy.animation_data_clear()
        obj_copy.parent = None
        obj_copy.matrix_world = obj.matrix_world.copy()
        tmp_col.objects.link(obj_copy)
        return obj_copy

    arm_copy = deep_copy_object(armature_obj)
    if arm_copy.type == "ARMATURE":
        arm_copy.data.pose_position = 'REST'
        # リグの操作用カスタムシェイプ（例: Icosphere）がglTFに混入しがちなので無効化
        try:
            print("DEBUG: Removing custom shapes from pose bones:")
            for pb in arm_copy.pose.bones:
                if pb.custom_shape:
                    print(f"  - Bone '{pb.name}' had custom_shape: {pb.custom_shape.name}")
                    pb.custom_shape = None
        except Exception as e:
            print(f"DEBUG: Error removing custom shapes: {e}")

    mesh_copies = []
    for m in mesh_objs:
        mc = deep_copy_object(m)
        # Armature modifier の参照先を差し替え
        has_arm_mod = False
        for mod in mc.modifiers:
            if mod.type == 'ARMATURE':
                mod.object = arm_copy
                has_arm_mod = True
        if not has_arm_mod:
            mod = mc.modifiers.new(name="Armature", type='ARMATURE')
            mod.object = arm_copy
        mesh_copies.append(mc)

    # スケールだけ焼き込む（location/rotationは維持）
    def apply_scale(obj):
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

    apply_scale(arm_copy)
    for mc in mesh_copies:
        apply_scale(mc)

    # glTFエクスポータは「Armatureがスキンメッシュの親」であることを期待する
    for mc in mesh_copies:
        world = mc.matrix_world.copy()
        mc.parent = arm_copy
        mc.parent_type = 'OBJECT'
        mc.matrix_parent_inverse = arm_copy.matrix_world.inverted()
        mc.matrix_world = world

    # 複製を選択してエクスポート
    bpy.ops.object.select_all(action='DESELECT')
    arm_copy.select_set(True)
    for mc in mesh_copies:
        mc.select_set(True)
    bpy.context.view_layer.objects.active = arm_copy

    # デバッグ: エクスポート対象を確認
    print("DEBUG: Objects selected for GLB export:")
    for obj in bpy.context.selected_objects:
        print(f"  - {obj.name} (type: {obj.type})")

    # デバッグ: TMP_GLB_EXPORTコレクション内の全オブジェクトを確認
    print("DEBUG: All objects in TMP_GLB_EXPORT collection:")
    for obj in tmp_col.objects:
        print(f"  - {obj.name} (type: {obj.type})")

    export_gltf(path, selected_only=export_selected_only)

    # 後片付け
    for obj in mesh_copies:
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.objects.remove(arm_copy, do_unlink=True)
    bpy.data.collections.remove(tmp_col)



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
    ap.add_argument("--head_bone", default="mixamorig7:Head")
    ap.add_argument("--calib", default=None)
    ap.add_argument("--delete_template_head", default="false")
    ap.add_argument("--decimate_ratio", type=float, default=1.0)

    args = parse_after_double_dash(ap)

    reset_scene()

    # 1) template import
    import_fbx(args.template)
    arm = find_armature()

    # FBXインポート時のアーマチュアスケールをそのまま使用
    print(f"Armature scale: {arm.scale}")

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

    # デバッグ: インポートされたメッシュの情報を出力
    print(f"DEBUG: Imported {len(after_meshes)} mesh(es) from head file:")
    for m in after_meshes:
        poly_count = len(m.data.polygons)
        vert_count = len(m.data.vertices)
        print(f"  - {m.name}: {poly_count} polygons, {vert_count} vertices")

    # headメッシュが複数入ることがあるので、最大ポリゴンのものを採用し、他は削除
    def poly_count(obj):
        return len(obj.data.polygons)
    head_obj = sorted(after_meshes, key=poly_count, reverse=True)[0]

    # 他のメッシュを削除
    for m in after_meshes:
        if m != head_obj:
            print(f"Removing extra mesh: {m.name}")
            bpy.data.objects.remove(m, do_unlink=True)

    # 3) optional decimate
    apply_decimate(head_obj, args.decimate_ratio)

    # 4) apply calib transform
    calib = load_calib(args.calib)
    apply_transform(head_obj, calib)

    # 4.6) apply all transforms before parenting to prevent scale issues
    bpy.context.view_layer.objects.active = head_obj
    bpy.ops.object.select_all(action='DESELECT')
    head_obj.select_set(True)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    print(f"Applied transforms to head mesh: scale={head_obj.scale}, location={head_obj.location}")

    # 5) parent to head bone
    # GLBではボーン親子付けより、スキニングの方が崩れにくい
    head_bone = resolve_bone_name(arm, args.head_bone)
    rigid_skin_to_bone(head_obj, arm, head_bone)
    print(f"After bind: scale={head_obj.scale}, location={head_obj.location}")

    # 6) delete template head (optional)
    if str(args.delete_template_head).lower() in ("1","true","yes","y"):
        delete_template_head_mesh(arm, head_bone)

    # 7) export
    # エクスポート前のシーン状態をデバッグ
    print("DEBUG: All objects before export:")
    for o in bpy.data.objects:
        print(f"  - {o.name} (type: {o.type}, parent: {o.parent.name if o.parent else None})")

    out_lower = args.out.lower()
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    if out_lower.endswith(".fbx"):
        export_fbx(args.out)
    elif out_lower.endswith(".glb") or out_lower.endswith(".gltf"):
        # GLBはArmature scale(例:0.01)が残るとビューア側でスキンが崩れやすいので、
        # 一時複製を作ってスケールを焼き込んでからエクスポートする。
        mesh_objs = []
        for o in bpy.data.objects:
            if o.type != "MESH":
                continue
            if o.parent == arm:
                mesh_objs.append(o)
                continue
            for mod in o.modifiers:
                if mod.type == "ARMATURE" and mod.object == arm:
                    mesh_objs.append(o)
                    break

        export_gltf_normalized(args.out, armature_obj=arm, mesh_objs=mesh_objs, export_selected_only=True)
    else:
        raise RuntimeError("Unsupported output format. Use .fbx or .glb")

if __name__ == "__main__":
    main()
