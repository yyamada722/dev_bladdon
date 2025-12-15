bl_info = {
    "name": "Export By Name (Batch)",
    "author": "CGSLAB / ChatGPT",
    "version": (0, 1, 5),
    "blender": (4, 0, 0),
    "location": "3D Viewport > N-Panel > Project > Export By Name",
    "description": "Export each object to individual files named from object names; scope=Selected/Visible/Collection; multi-format + collect used textures",
    "category": "Import-Export",
}

import bpy
import os
import re
import shutil
import datetime
import contextlib
import addon_utils

from bpy.props import (
    StringProperty, EnumProperty, BoolProperty, PointerProperty
)
from bpy.types import Operator, Panel, PropertyGroup

# ------------------------------------------------------------
# Helpers / Constants
# ------------------------------------------------------------

EXT_BY_FMT = {
    "GLB": "glb",
    "GLTF": "gltf",
    "FBX": "fbx",
    "OBJ": "obj",
    "STL": "stl",
    "PLY": "ply",
    "ABC": "abc",
    "USD": "usd",
}

# Add-on module names for auto-enable (legacy系のみ明示)
MODULE_BY_FMT = {
    "GLB":  "io_scene_gltf2",
    "GLTF": "io_scene_gltf2",
    "FBX":  "io_scene_fbx",
    "OBJ":  "io_scene_obj",   # 旧OBJ用（新OBJは wm.obj_export）
    "STL":  "io_mesh_stl",    # 旧STL用（新STLは wm.stl_export）
    "USD":  "io_scene_usd",
    # ABC は標準内蔵（wm.alembic_export）
}

def ensure_object_mode():
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

@contextlib.contextmanager
def preserve_selection(context):
    view_layer = context.view_layer
    prev_active = view_layer.objects.active
    prev_sel = [o for o in context.selected_objects]
    try:
        yield
    finally:
        bpy.ops.object.select_all(action='DESELECT')
        for o in prev_sel:
            if o and o.name in bpy.data.objects:
                o.select_set(True)
        if prev_active and prev_active.name in bpy.data.objects:
            view_layer.objects.active = prev_active

def sanitize(name: str, pattern=r"[^A-Za-z0-9_.\-]+") -> str:
    s = re.sub(pattern, "_", name).strip("._-")
    return s or "untitled"

def iter_collection_objects(coll: bpy.types.Collection, recursive=True):
    for o in coll.objects:
        yield o
    if recursive:
        for c in coll.children:
            yield from iter_collection_objects(c, recursive=True)

def unique_path(path: str) -> str:
    if not os.path.exists(path):
        return path
    root, ext = os.path.splitext(path)
    i = 1
    while True:
        p = f"{root}.{i:03d}{ext}"
        if not os.path.exists(p):
            return p
        i += 1

def first_collection_name(obj: bpy.types.Object) -> str:
    cols = list(obj.users_collection) if hasattr(obj, "users_collection") else []
    return cols[0].name if cols else ""

def resolve_filename(template: str, obj: bpy.types.Object, fmt_key: str, regex: str, col_override=None) -> str:
    now = datetime.datetime.now()
    tokens = {
        "obj": sanitize(obj.name, regex),
        "col": sanitize(col_override if col_override is not None else first_collection_name(obj), regex),
        "scene": sanitize(bpy.context.scene.name, regex),
        "date": now.strftime("%Y%m%d"),
        "time": now.strftime("%H%M%S"),
        "ext": EXT_BY_FMT.get(fmt_key, "dat"),
    }
    fname = template.format(**tokens)
    base = os.path.basename(fname)
    _, ext = os.path.splitext(base)
    if not ext:
        fname = f"{fname}.{tokens['ext']}"
    return fname

def gather_targets(context, scope, collection, recursive, visible_only):
    def mesh_and_visible_filter(objs):
        out = []
        for o in objs:
            if o.type != 'MESH':
                continue
            if visible_only and not o.visible_get():
                continue
            out.append(o)
        return out

    if scope == "SELECTED":
        objs = mesh_and_visible_filter(context.selected_objects)
    elif scope == "VISIBLE":
        objs = [o for o in context.view_layer.objects if o.type == 'MESH' and o.visible_get()]
    else:  # COLLECTION
        if not collection:
            return []
        objs = mesh_and_visible_filter(iter_collection_objects(collection, recursive=recursive))

    uniq = {o.name: o for o in objs}
    return [uniq[k] for k in sorted(uniq.keys())]

def enable_addon_if_present(module_name: str):
    try:
        enabled, _ = addon_utils.check(module_name)
    except Exception:
        enabled = False
    if not enabled:
        try:
            addon_utils.enable(module_name, default_set=False, persistent=False)
        except Exception:
            try:
                bpy.ops.preferences.addon_enable(module=module_name)
            except Exception:
                pass

def ensure_exporter_available(fmt_key: str):
    """4.2+ の新エクスポータを優先。無い場合は legacy を有効化して確認。"""
    if fmt_key == "STL":
        if hasattr(bpy.ops.wm, "stl_export"):
            return
        enable_addon_if_present("io_mesh_stl")
        if hasattr(bpy.ops.export_mesh, "stl"):
            return
        raise RuntimeError("STLエクスポータが見つかりません。新エクスポータ（wm.stl_export）または 'STL format (legacy)' を有効にしてください。")

    if fmt_key == "OBJ":
        if hasattr(bpy.ops.wm, "obj_export") or hasattr(bpy.ops.export_scene, "obj"):
            return
        enable_addon_if_present("io_scene_obj")
        if not (hasattr(bpy.ops.wm, "obj_export") or hasattr(bpy.ops.export_scene, "obj")):
            raise RuntimeError("OBJエクスポータが見つかりません（'Wavefront OBJ' を有効に）。")

    if fmt_key in {"GLB", "GLTF"}:
        enable_addon_if_present("io_scene_gltf2")
        if not hasattr(bpy.ops.export_scene, "gltf"):
            raise RuntimeError("glTFエクスポータが無効です（'glTF 2.0' を有効に）。")

    if fmt_key == "FBX":
        enable_addon_if_present("io_scene_fbx")
        if not hasattr(bpy.ops.export_scene, "fbx"):
            raise RuntimeError("FBXエクスポータが無効です（'FBX format' を有効に）。")

    if fmt_key == "USD":
        if hasattr(bpy.ops.wm, "usd_export") or (hasattr(bpy.ops, "usd") and hasattr(bpy.ops.usd, "export")):
            return
        enable_addon_if_present("io_scene_usd")
        if not (hasattr(bpy.ops.wm, "usd_export") or (hasattr(bpy.ops, "usd") and hasattr(bpy.ops.usd, "export"))):
            raise RuntimeError("USDエクスポータが無効です（'USD format (io_scene_usd)' を有効に）。")

    if fmt_key == "ABC":
        if not hasattr(bpy.ops.wm, "alembic_export"):
            raise RuntimeError("Alembicエクスポータが見つかりません（環境を確認）。")

# ------------------------------------------------------------
# Collect images used by targets
# ------------------------------------------------------------

def _gather_images_from_node_tree(ntree, out_set):
    if not ntree:
        return
    for node in ntree.nodes:
        if node.type == 'TEX_IMAGE' and getattr(node, "image", None):
            out_set.add(node.image)
        elif node.type == 'GROUP' and getattr(node, "node_tree", None):
            _gather_images_from_node_tree(node.node_tree, out_set)

def gather_images_from_objects(objs):
    images = set()
    for obj in objs:
        for slot in obj.material_slots:
            mat = slot.material
            if not mat:
                continue
            if getattr(mat, "use_nodes", False):
                _gather_images_from_node_tree(mat.node_tree, images)
    return images

def _image_best_basename(img: bpy.types.Image) -> str:
    # 優先：外部ファイル名 -> 画像名
    fp = bpy.path.abspath(img.filepath) if img.filepath else ""
    bn = os.path.basename(fp) if fp else ""
    if bn:
        return bn
    # 名前＋推定拡張子
    name = sanitize(img.name)
    # 拡張子の推定（最低限）
    ext = os.path.splitext(bn)[1] if bn else ""
    if not ext or len(ext) > 5:
        ext = ".png"
    return f"{name}{ext}"

def copy_or_save_image(img: bpy.types.Image, dest_dir: str, scene: bpy.types.Scene):
    os.makedirs(dest_dir, exist_ok=True)

    # 外部パスが有効で、かつ未パックならコピー
    src = bpy.path.abspath(img.filepath) if img.filepath else ""
    is_packed = getattr(img, "packed_file", None) is not None
    if src and os.path.exists(src) and not is_packed:
        dest = unique_path(os.path.join(dest_dir, os.path.basename(src)))
        try:
            shutil.copy2(src, dest)
            return dest, "copied"
        except Exception as e:
            return None, f"copy_failed: {e}"

    # パック or ソース不明：ファイルとして書き出す
    basename = _image_best_basename(img)
    dest = unique_path(os.path.join(dest_dir, basename))

    # まず Image.save() を試す（4.x）
    try:
        img.save(filepath=dest)
        return dest, "saved"
    except Exception:
        pass

    # 次に save_render（scene 設定使用）。PNGで安全に落とす。
    try:
        scn = scene or bpy.context.scene
        rs_fmt = scn.render.image_settings.file_format
        rs_mode = scn.render.image_settings.color_mode
        scn.render.image_settings.file_format = 'PNG'
        scn.render.image_settings.color_mode = 'RGBA' if getattr(img, "alpha_mode", "STRAIGHT") != 'NONE' else 'RGB'
        # 拡張子をpngに変える
        png_dest = os.path.splitext(dest)[0] + ".png"
        img.save_render(png_dest, scene=scn)
        # restore
        scn.render.image_settings.file_format = rs_fmt
        scn.render.image_settings.color_mode = rs_mode
        return png_dest, "render_saved"
    except Exception as e:
        return None, f"save_failed: {e}"

# ------------------------------------------------------------
# Export dispatchers
# ------------------------------------------------------------

def do_export(fmt_key: str, filepath: str, apply_modifiers: bool):
    ensure_exporter_available(fmt_key)

    if fmt_key in {"GLB", "GLTF"}:
        kw = dict(
            filepath=filepath,
            use_selection=True,
            export_normals=True,
            export_texcoords=True,
            export_colors=True,
            export_materials='EXPORT',
            export_apply=apply_modifiers,
        )
        kw["export_format"] = 'GLB' if fmt_key == "GLB" else 'GLTF_SEPARATE'
        bpy.ops.export_scene.gltf(**kw)
        return

    if fmt_key == "FBX":
        kw = dict(
            filepath=filepath,
            use_selection=True,
            add_leaf_bones=False,
            apply_scale_options='FBX_SCALE_NONE',
        )
        try:
            kw["use_mesh_modifiers"] = apply_modifiers
        except Exception:
            pass
        bpy.ops.export_scene.fbx(**kw)
        return

    if fmt_key == "OBJ":
        # 新OBJエクスポータ（Blender 4.x）
        if hasattr(bpy.ops.wm, "obj_export"):
            kw = dict(
                filepath=filepath,
                export_selected_objects=True,
                export_uv=True,
                export_normals=True,
                export_materials=True,  # MTLを出力
                path_mode="COPY",       # テクスチャを出力先へコピー（環境差で効かない場合あり）
                apply_modifiers=apply_modifiers,
            )
            try:
                bpy.ops.wm.obj_export(**kw)
            except TypeError:
                # 環境差で未対応の引数がある場合は削って再トライ
                for k in ["path_mode", "apply_modifiers", "export_materials", "export_normals", "export_uv"]:
                    if k in kw:
                        kw.pop(k)
                        try:
                            bpy.ops.wm.obj_export(**kw)
                            break
                        except TypeError:
                            continue
                else:
                    bpy.ops.wm.obj_export(filepath=filepath, export_selected_objects=True)
            return

        # 旧OBJエクスポータ
        if hasattr(bpy.ops.export_scene, "obj"):
            kw = dict(
                filepath=filepath,
                use_selection=True,
                use_materials=True,  # MTLを出力
                path_mode="COPY",    # テクスチャを出力先へコピー
            )
            try:
                kw["use_mesh_modifiers"] = apply_modifiers
            except Exception:
                pass
            bpy.ops.export_scene.obj(**kw)
            return

        raise RuntimeError("OBJ exporter not available.")

    if fmt_key == "STL":
        # 新エクスポータ（Blender 4.2+）
        if hasattr(bpy.ops.wm, "stl_export"):
            try:
                bpy.ops.wm.stl_export(
                    filepath=filepath,
                    export_selected_objects=True,
                    apply_modifiers=apply_modifiers
                )
            except TypeError:
                bpy.ops.wm.stl_export(filepath=filepath)
            return
        # 旧（legacy）
        if hasattr(bpy.ops.export_mesh, "stl"):
            kw = dict(filepath=filepath, use_selection=True, ascii=False)
            try:
                kw["use_mesh_modifiers"] = apply_modifiers
            except Exception:
                pass
            bpy.ops.export_mesh.stl(**kw)
            return
        raise RuntimeError("STL exporter not found.")

    if fmt_key == "PLY":
        kw = dict(filepath=filepath, use_selection=True)
        try:
            kw["use_mesh_modifiers"] = apply_modifiers
        except Exception:
            pass
        bpy.ops.export_mesh.ply(**kw)
        return

    if fmt_key == "ABC":
        kw = dict(filepath=filepath, selected=True)
        bpy.ops.wm.alembic_export(**kw)
        return

    if fmt_key == "USD":
        if hasattr(bpy.ops.wm, "usd_export"):
            kw = dict(filepath=filepath, selected_objects_only=True)
            bpy.ops.wm.usd_export(**kw)
            return
        if hasattr(bpy.ops, "usd") and hasattr(bpy.ops.usd, "export"):
            bpy.ops.usd.export(filepath=filepath)
            return

    raise RuntimeError(f"Unknown format: {fmt_key}")

# ------------------------------------------------------------
# Properties & UI
# ------------------------------------------------------------

class EBN_Props(PropertyGroup):
    export_dir: StringProperty(
        name="Export Dir",
        subtype='DIR_PATH',
        default="//exports"
    )
    scope: EnumProperty(
        name="Scope",
        items=[
            ("SELECTED", "Selected", "選択オブジェクト"),
            ("VISIBLE", "Visible", "可視オブジェクト（現在のビューレイヤー）"),
            ("COLLECTION", "Collection", "指定コレクション内（再帰可）"),
        ],
        default="SELECTED"
    )
    collection: PointerProperty(
        name="Collection",
        type=bpy.types.Collection
    )
    recursive: BoolProperty(
        name="Recursive (child collections)",
        default=True
    )
    visible_only: BoolProperty(
        name="Visible Only",
        description="可視のオブジェクトのみ対象（SELECTED/COLLECTIONで有効）",
        default=False
    )
    put_in_collection_subdir: BoolProperty(
        name='Put into "Collection" subfolder',
        description="COLLECTIONスコープ時、選択コレクション名のサブフォルダへ保存",
        default=False
    )
    export_format: EnumProperty(
        name="Format",
        items=[
            ("GLB", "GLB", "glTF Binary"),
            ("GLTF", "glTF (separate)", "glTF + .bin + textures"),
            ("FBX", "FBX", "Autodesk FBX"),
            ("OBJ", "OBJ", "Wavefront OBJ"),
            ("STL", "STL", "STereoLithography"),
            ("PLY", "PLY", "Polygon File Format"),
            ("ABC", "Alembic (.abc)", "Alembic cache"),
            ("USD", "USD", "Universal Scene Description"),
        ],
        default="FBX"
    )
    filename_template: StringProperty(
        name="Filename Template",
        description="Tokens: {obj}, {col}, {scene}, {date}, {time}, {ext}",
        default="{obj}"
    )
    name_sanitize_regex: StringProperty(
        name="Sanitize Regex",
        description="Replace matches with '_' for file names",
        default=r"[^A-Za-z0-9_.\-]+"
    )
    apply_modifiers: BoolProperty(
        name="Apply Modifiers (when supported)",
        default=True
    )
    log_to_text: BoolProperty(
        name="Write Log to Text",
        default=True
    )

    # --- Images export options ---
    images_subdir: StringProperty(
        name="Images Subfolder",
        description="画像の書き出し先サブフォルダ名（Export Dir 配下）",
        default="textures"
    )
    images_reuse_collection_subdir: BoolProperty(
        name='Use "Collection" subfolder (if set)',
        description="COLLECTIONスコープでサブフォルダを使う設定なら、その配下に images_subdir を作成",
        default=True
    )

class EBN_OT_export(Operator):
    bl_idname = "ebn.export_by_name"
    bl_label = "Export By Object Name"
    bl_description = "スコープ内の各オブジェクトを個別ファイルで書き出し（ファイル名はオブジェクト名ベース）"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        ensure_object_mode()
        props: EBN_Props = context.scene.ebn_props

        base_dir = bpy.path.abspath(props.export_dir)
        if not base_dir:
            self.report({'ERROR'}, "Export Dir を指定してください。")
            return {'CANCELLED'}
        os.makedirs(base_dir, exist_ok=True)

        col_name = None
        out_dir = base_dir

        if props.scope == "COLLECTION":
            if not props.collection:
                self.report({'WARNING'}, "Collection を指定してください。")
                return {'CANCELLED'}
            col_name = props.collection.name
            if props.put_in_collection_subdir:
                out_dir = os.path.join(base_dir, sanitize(col_name, props.name_sanitize_regex))
                os.makedirs(out_dir, exist_ok=True)

        targets = gather_targets(
            context,
            props.scope,
            props.collection,
            props.recursive,
            props.visible_only
        )
        if not targets:
            self.report({'WARNING'}, "対象オブジェクトがありません。")
            return {'CANCELLED'}

        log_lines = []
        ok_count, ng_count = 0, 0

        with preserve_selection(context):
            for obj in targets:
                bpy.ops.object.select_all(action='DESELECT')
                obj.select_set(True)
                context.view_layer.objects.active = obj

                fname = resolve_filename(
                    props.filename_template,
                    obj,
                    props.export_format,
                    props.name_sanitize_regex,
                    col_override=col_name
                )
                out_path = unique_path(os.path.join(out_dir, fname))

                try:
                    do_export(props.export_format, out_path, props.apply_modifiers)
                    log_lines.append(f"OK: {obj.name} -> {out_path}")
                    ok_count += 1
                except Exception as e:
                    log_lines.append(f"NG: {obj.name} -> {type(e).__name__}: {e}")
                    ng_count += 1

        if props.log_to_text:
            txt = bpy.data.texts.get("ExportByName_Log") or bpy.data.texts.new("ExportByName_Log")
            txt.clear()
            txt.write(f"[ExportByName] {datetime.datetime.now().isoformat(timespec='seconds')}\n")
            for ln in log_lines:
                txt.write(ln + "\n")

        self.report({'INFO'}, f"完了: OK={ok_count}, NG={ng_count}. Text: ExportByName_Log を確認。")
        return {'FINISHED'}

class EBN_OT_export_used_images(Operator):
    bl_idname = "ebn.export_used_images"
    bl_label = "Export Used Images"
    bl_description = "対象オブジェクトが参照する画像ファイルを一括で書き出す（パック画像にも対応）"

    def execute(self, context):
        ensure_object_mode()
        props: EBN_Props = context.scene.ebn_props

        # ベースの出力先
        base_dir = bpy.path.abspath(props.export_dir)
        if not base_dir:
            self.report({'ERROR'}, "Export Dir を指定してください。")
            return {'CANCELLED'}
        os.makedirs(base_dir, exist_ok=True)

        # コレクションサブフォルダ考慮
        out_dir = base_dir
        if props.scope == "COLLECTION" and props.collection and props.put_in_collection_subdir and props.images_reuse_collection_subdir:
            col_name = sanitize(props.collection.name, props.name_sanitize_regex)
            out_dir = os.path.join(base_dir, col_name)

        # 画像用サブフォルダ
        img_dir = os.path.join(out_dir, props.images_subdir)
        os.makedirs(img_dir, exist_ok=True)

        # 対象オブジェクト
        targets = gather_targets(
            context,
            props.scope,
            props.collection,
            props.recursive,
            props.visible_only
        )
        if not targets:
            self.report({'WARNING'}, "対象オブジェクトがありません。")
            return {'CANCELLED'}

        # 画像の収集
        imgs = gather_images_from_objects(targets)
        if not imgs:
            self.report({'INFO'}, "参照画像は見つかりませんでした。")
            return {'CANCELLED'}

        # 書き出し
        scene = context.scene
        ok, ng = 0, 0
        log_lines = [f"[ExportImages] {datetime.datetime.now().isoformat(timespec='seconds')}  dir={img_dir}"]
        for img in sorted(imgs, key=lambda x: x.name.lower()):
            dest, status = copy_or_save_image(img, img_dir, scene)
            if dest:
                ok += 1
                log_lines.append(f"OK: {img.name} -> {dest} ({status})")
            else:
                ng += 1
                log_lines.append(f"NG: {img.name} ({status})")

        # ログ
        txt = bpy.data.texts.get("ExportByName_Log") or bpy.data.texts.new("ExportByName_Log")
        txt.write("\n".join(log_lines) + "\n")

        self.report({'INFO'}, f"画像書き出し完了: OK={ok}, NG={ng}. Text: ExportByName_Log を確認。")
        return {'FINISHED'}

class EBN_OT_save_log(Operator):
    bl_idname = "ebn.save_log"
    bl_label = "Save Log (.txt)"
    bl_description = "ExportByName_Log をテキストファイルとして保存"

    filepath: StringProperty(subtype='FILE_PATH', default="//ExportByName_Log.txt")

    def execute(self, context):
        txt = bpy.data.texts.get("ExportByName_Log")
        if not txt:
            self.report({'WARNING'}, "Log not found.")
            return {'CANCELLED'}
        path = bpy.path.abspath(self.filepath)
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(txt.as_string())
        self.report({'INFO'}, f"Saved: {path}")
        return {'FINISHED'}

class EBN_PT_panel(Panel):
    bl_label = "Export By Name"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Project'

    def draw(self, context):
        layout = self.layout
        p: EBN_Props = context.scene.ebn_props

        col = layout.column(align=True)
        col.prop(p, "export_dir")
        col.prop(p, "export_format")
        col.prop(p, "filename_template")
        col.prop(p, "name_sanitize_regex")

        box = layout.box()
        box.label(text="Scope")
        box.prop(p, "scope", text="")
        if p.scope == "COLLECTION":
            box.prop(p, "collection")
            row = box.row(align=True)
            row.prop(p, "recursive")
            row.prop(p, "visible_only")
            box.prop(p, "put_in_collection_subdir")
        elif p.scope == "SELECTED":
            box.prop(p, "visible_only")

        # Images
        img = layout.box()
        img.label(text="Images")
        img.prop(p, "images_subdir")
        img.prop(p, "images_reuse_collection_subdir")
        img.operator("ebn.export_used_images", icon='IMAGE_DATA')

        adv = layout.box()
        adv.label(text="Advanced")
        adv.prop(p, "apply_modifiers")
        adv.prop(p, "log_to_text")
        adv.operator("ebn.save_log", icon='FILE_TICK')

        layout.operator("ebn.export_by_name", icon='EXPORT')

# ------------------------------------------------------------
# Register
# ------------------------------------------------------------

classes = (
    EBN_Props,
    EBN_OT_export,
    EBN_OT_export_used_images,
    EBN_OT_save_log,
    EBN_PT_panel,
)

def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.ebn_props = PointerProperty(type=EBN_Props)

def unregister():
    if hasattr(bpy.types.Scene, "ebn_props"):
        del bpy.types.Scene.ebn_props
    for c in reversed(classes):
        bpy.utils.unregister_class(c)

if __name__ == "__main__":
    register()
