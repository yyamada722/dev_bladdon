bl_info = {
    "name": "Transform Saver",
    "author": "Your Name",
    "version": (1, 5, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > Transform Saver",
    "description": "Manage object transforms with groups - save and restore with clean transforms",
    "category": "Object",
}

import bpy
from mathutils import Vector, Euler
from bpy.props import (
    CollectionProperty,
    StringProperty,
    FloatVectorProperty,
    IntProperty,
    BoolProperty,
)


class TransformData(bpy.types.PropertyGroup):
    """保存されたトランスフォームデータ"""
    object_name: StringProperty(name="Object Name")
    location: FloatVectorProperty(name="Location", size=3)
    rotation: FloatVectorProperty(name="Rotation", size=3)
    scale: FloatVectorProperty(name="Scale", size=3, default=(1, 1, 1))
    has_saved: BoolProperty(name="Has Saved Data", default=False)


class TransformGroup(bpy.types.PropertyGroup):
    """トランスフォームグループ"""
    name: StringProperty(name="Group Name", default="New Group")
    items: CollectionProperty(type=TransformData)
    expanded: BoolProperty(name="Expanded", default=True)
    # Zero/Restore時に適用する項目
    apply_location: BoolProperty(name="Loc", default=True, description="Apply Location on Zero/Restore")
    apply_rotation: BoolProperty(name="Rot", default=True, description="Apply Rotation on Zero/Restore")
    apply_scale: BoolProperty(name="Scale", default=True, description="Apply Scale on Zero/Restore")


# ==================== グループ操作 ====================

class TRANSFORMSAVER_OT_group_add(bpy.types.Operator):
    """新規グループを作成"""
    bl_idname = "object.transform_group_add"
    bl_label = "Add Group"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        group = scene.transform_groups.add()
        group.name = f"Group {len(scene.transform_groups)}"
        self.report({'INFO'}, f"Created '{group.name}'")
        return {'FINISHED'}


class TRANSFORMSAVER_OT_group_remove(bpy.types.Operator):
    """グループを削除"""
    bl_idname = "object.transform_group_remove"
    bl_label = "Remove Group"
    bl_options = {'REGISTER', 'UNDO'}

    group_index: IntProperty()

    def execute(self, context):
        scene = context.scene
        if 0 <= self.group_index < len(scene.transform_groups):
            name = scene.transform_groups[self.group_index].name
            scene.transform_groups.remove(self.group_index)
            self.report({'INFO'}, f"Removed group '{name}'")
        return {'FINISHED'}


class TRANSFORMSAVER_OT_group_toggle(bpy.types.Operator):
    """グループの展開/折りたたみ"""
    bl_idname = "object.transform_group_toggle"
    bl_label = "Toggle Group"

    group_index: IntProperty()

    def execute(self, context):
        scene = context.scene
        if 0 <= self.group_index < len(scene.transform_groups):
            group = scene.transform_groups[self.group_index]
            group.expanded = not group.expanded
        return {'FINISHED'}


# ==================== アイテム操作 ====================

class TRANSFORMSAVER_OT_item_add(bpy.types.Operator):
    """選択オブジェクトをグループに追加（複数選択対応）"""
    bl_idname = "object.transform_item_add"
    bl_label = "Add Selected"
    bl_description = "Add all selected objects to this group"
    bl_options = {'REGISTER', 'UNDO'}

    group_index: IntProperty()

    @classmethod
    def poll(cls, context):
        return len(context.selected_objects) > 0

    def execute(self, context):
        scene = context.scene

        if not (0 <= self.group_index < len(scene.transform_groups)):
            return {'CANCELLED'}

        group = scene.transform_groups[self.group_index]

        # 既存のオブジェクト名をセットで管理
        existing_names = {item.object_name for item in group.items}

        added = 0
        skipped = 0

        for obj in context.selected_objects:
            if obj.name in existing_names:
                skipped += 1
                continue

            item = group.items.add()
            item.object_name = obj.name
            item.has_saved = False
            existing_names.add(obj.name)
            added += 1

        if added > 0 and skipped > 0:
            self.report({'INFO'}, f"Added {added} objects, skipped {skipped} duplicates")
        elif added > 0:
            self.report({'INFO'}, f"Added {added} objects to '{group.name}'")
        else:
            self.report({'WARNING'}, f"All {skipped} objects already in group")

        return {'FINISHED'}


class TRANSFORMSAVER_OT_item_remove(bpy.types.Operator):
    """アイテムをグループから削除"""
    bl_idname = "object.transform_item_remove"
    bl_label = "Remove from Group"
    bl_options = {'REGISTER', 'UNDO'}

    group_index: IntProperty()
    item_index: IntProperty()

    def execute(self, context):
        scene = context.scene

        if not (0 <= self.group_index < len(scene.transform_groups)):
            return {'CANCELLED'}

        group = scene.transform_groups[self.group_index]

        if 0 <= self.item_index < len(group.items):
            name = group.items[self.item_index].object_name
            group.items.remove(self.item_index)
            self.report({'INFO'}, f"Removed '{name}' from '{group.name}'")

        return {'FINISHED'}


class TRANSFORMSAVER_OT_clean_missing(bpy.types.Operator):
    """存在しないオブジェクトをグループから一括削除"""
    bl_idname = "object.transform_clean_missing"
    bl_label = "Clean Missing"
    bl_description = "Remove all missing objects from this group"
    bl_options = {'REGISTER', 'UNDO'}

    group_index: IntProperty()

    def execute(self, context):
        scene = context.scene

        if not (0 <= self.group_index < len(scene.transform_groups)):
            return {'CANCELLED'}

        group = scene.transform_groups[self.group_index]

        # 後ろから削除（インデックスずれ防止）
        removed = 0
        for i in range(len(group.items) - 1, -1, -1):
            if group.items[i].object_name not in bpy.data.objects:
                group.items.remove(i)
                removed += 1

        if removed > 0:
            self.report({'INFO'}, f"Removed {removed} missing objects from '{group.name}'")
        else:
            self.report({'INFO'}, "No missing objects found")

        return {'FINISHED'}


# ==================== ヘルパー関数 ====================

def apply_zero(item, apply_loc=True, apply_rot=True, apply_scale=True):
    """Zeroを適用：トランスフォーム値を0/1にリセット（見た目も変わる）"""
    if not item.has_saved:
        return False, "No saved data"

    obj = bpy.data.objects.get(item.object_name)
    if obj is None:
        return False, "Object not found"

    # トランスフォームをリセット
    if apply_loc:
        obj.location = Vector((0, 0, 0))
    if apply_rot:
        obj.rotation_euler = Euler((0, 0, 0))
    if apply_scale:
        obj.scale = Vector((1, 1, 1))

    return True, None


def apply_restore(item, apply_loc=True, apply_rot=True, apply_scale=True):
    """Restoreを適用するヘルパー関数（トランスフォーム値のみ復元）"""
    if not item.has_saved:
        return False, "No saved data"

    obj = bpy.data.objects.get(item.object_name)
    if obj is None:
        return False, "Object not found"

    if apply_loc:
        obj.location = Vector(item.location)
    if apply_rot:
        obj.rotation_euler = Euler(item.rotation)
    if apply_scale:
        obj.scale = Vector(item.scale)

    return True, None


# ==================== 一括操作 ====================

class TRANSFORMSAVER_OT_save_all(bpy.types.Operator):
    """グループ内全オブジェクトのトランスフォームを保存"""
    bl_idname = "object.transform_save_all"
    bl_label = "Save All"
    bl_description = "Save transforms for all objects in this group"
    bl_options = {'REGISTER', 'UNDO'}

    group_index: IntProperty()

    def execute(self, context):
        scene = context.scene

        if not (0 <= self.group_index < len(scene.transform_groups)):
            return {'CANCELLED'}

        group = scene.transform_groups[self.group_index]
        count = 0

        for item in group.items:
            obj = bpy.data.objects.get(item.object_name)
            if obj is not None:
                item.location = obj.location.copy()
                item.rotation = obj.rotation_euler.copy()
                item.scale = obj.scale.copy()
                item.has_saved = True
                count += 1

        self.report({'INFO'}, f"Saved {count} objects in '{group.name}'")
        return {'FINISHED'}


class TRANSFORMSAVER_OT_zero_all(bpy.types.Operator):
    """グループ内全オブジェクトをZero"""
    bl_idname = "object.transform_zero_all"
    bl_label = "Zero All"
    bl_description = "Reset all objects to Loc=0, Rot=0, Scale=1"
    bl_options = {'REGISTER', 'UNDO'}

    group_index: IntProperty()

    def execute(self, context):
        scene = context.scene

        if not (0 <= self.group_index < len(scene.transform_groups)):
            return {'CANCELLED'}

        group = scene.transform_groups[self.group_index]
        count = 0

        for item in group.items:
            success, _ = apply_zero(
                item,
                group.apply_location,
                group.apply_rotation,
                group.apply_scale
            )
            if success:
                count += 1

        self.report({'INFO'}, f"Zeroed {count} objects in '{group.name}'")
        return {'FINISHED'}


class TRANSFORMSAVER_OT_restore_all(bpy.types.Operator):
    """グループ内全オブジェクトをRestore"""
    bl_idname = "object.transform_restore_all"
    bl_label = "Restore All"
    bl_description = "Restore all objects to saved transforms"
    bl_options = {'REGISTER', 'UNDO'}

    group_index: IntProperty()

    def execute(self, context):
        scene = context.scene

        if not (0 <= self.group_index < len(scene.transform_groups)):
            return {'CANCELLED'}

        group = scene.transform_groups[self.group_index]
        count = 0

        for item in group.items:
            success, _ = apply_restore(
                item,
                group.apply_location,
                group.apply_rotation,
                group.apply_scale
            )
            if success:
                count += 1

        self.report({'INFO'}, f"Restored {count} objects in '{group.name}'")
        return {'FINISHED'}


# ==================== 選択オブジェクトのみ操作 ====================

class TRANSFORMSAVER_OT_save_selected(bpy.types.Operator):
    """選択中のオブジェクトのみ保存"""
    bl_idname = "object.transform_save_selected"
    bl_label = "Save Sel"
    bl_description = "Save transforms for selected objects only"
    bl_options = {'REGISTER', 'UNDO'}

    group_index: IntProperty()

    def execute(self, context):
        scene = context.scene

        if not (0 <= self.group_index < len(scene.transform_groups)):
            return {'CANCELLED'}

        group = scene.transform_groups[self.group_index]
        selected_names = {obj.name for obj in context.selected_objects}
        count = 0

        for item in group.items:
            if item.object_name not in selected_names:
                continue
            obj = bpy.data.objects.get(item.object_name)
            if obj is not None:
                item.location = obj.location.copy()
                item.rotation = obj.rotation_euler.copy()
                item.scale = obj.scale.copy()
                item.has_saved = True
                count += 1

        self.report({'INFO'}, f"Saved {count} selected objects")
        return {'FINISHED'}


class TRANSFORMSAVER_OT_zero_selected(bpy.types.Operator):
    """選択中のオブジェクトのみZero"""
    bl_idname = "object.transform_zero_selected"
    bl_label = "Zero Sel"
    bl_description = "Reset selected objects to Loc=0, Rot=0, Scale=1"
    bl_options = {'REGISTER', 'UNDO'}

    group_index: IntProperty()

    def execute(self, context):
        scene = context.scene

        if not (0 <= self.group_index < len(scene.transform_groups)):
            return {'CANCELLED'}

        group = scene.transform_groups[self.group_index]
        selected_names = {obj.name for obj in context.selected_objects}
        count = 0

        for item in group.items:
            if item.object_name not in selected_names:
                continue
            success, _ = apply_zero(
                item,
                group.apply_location,
                group.apply_rotation,
                group.apply_scale
            )
            if success:
                count += 1

        self.report({'INFO'}, f"Zeroed {count} selected objects")
        return {'FINISHED'}


class TRANSFORMSAVER_OT_restore_selected(bpy.types.Operator):
    """選択中のオブジェクトのみRestore"""
    bl_idname = "object.transform_restore_selected"
    bl_label = "Restore Sel"
    bl_description = "Restore selected objects to saved transforms"
    bl_options = {'REGISTER', 'UNDO'}

    group_index: IntProperty()

    def execute(self, context):
        scene = context.scene

        if not (0 <= self.group_index < len(scene.transform_groups)):
            return {'CANCELLED'}

        group = scene.transform_groups[self.group_index]
        selected_names = {obj.name for obj in context.selected_objects}
        count = 0

        for item in group.items:
            if item.object_name not in selected_names:
                continue
            success, _ = apply_restore(
                item,
                group.apply_location,
                group.apply_rotation,
                group.apply_scale
            )
            if success:
                count += 1

        self.report({'INFO'}, f"Restored {count} selected objects")
        return {'FINISHED'}


# ==================== 選択 ====================

class TRANSFORMSAVER_OT_select(bpy.types.Operator):
    """オブジェクトを選択"""
    bl_idname = "object.transform_select"
    bl_label = "Select"
    bl_description = "Select this object"
    bl_options = {'REGISTER', 'UNDO'}

    group_index: IntProperty()
    item_index: IntProperty()

    def execute(self, context):
        scene = context.scene

        if not (0 <= self.group_index < len(scene.transform_groups)):
            return {'CANCELLED'}

        group = scene.transform_groups[self.group_index]

        if not (0 <= self.item_index < len(group.items)):
            return {'CANCELLED'}

        item = group.items[self.item_index]
        obj = bpy.data.objects.get(item.object_name)

        if obj is None:
            self.report({'WARNING'}, f"Object '{item.object_name}' not found")
            return {'CANCELLED'}

        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        context.view_layer.objects.active = obj

        return {'FINISHED'}


class TRANSFORMSAVER_OT_select_group(bpy.types.Operator):
    """グループ内の全オブジェクトを選択"""
    bl_idname = "object.transform_select_group"
    bl_label = "Select All"
    bl_description = "Select all objects in this group"
    bl_options = {'REGISTER', 'UNDO'}

    group_index: IntProperty()

    def execute(self, context):
        scene = context.scene

        if not (0 <= self.group_index < len(scene.transform_groups)):
            return {'CANCELLED'}

        group = scene.transform_groups[self.group_index]

        bpy.ops.object.select_all(action='DESELECT')
        count = 0

        for item in group.items:
            obj = bpy.data.objects.get(item.object_name)
            if obj is not None:
                obj.select_set(True)
                if count == 0:
                    context.view_layer.objects.active = obj
                count += 1

        self.report({'INFO'}, f"Selected {count} objects")
        return {'FINISHED'}


# ==================== ユーティリティ ====================

def count_missing_objects(group):
    """グループ内の存在しないオブジェクト数をカウント"""
    count = 0
    for item in group.items:
        if item.object_name not in bpy.data.objects:
            count += 1
    return count


def count_selected_in_group(group, context):
    """グループ内の選択中オブジェクト数をカウント"""
    selected_names = {obj.name for obj in context.selected_objects}
    count = 0
    for item in group.items:
        if item.object_name in selected_names:
            count += 1
    return count


# ==================== パネル ====================

class TRANSFORMSAVER_PT_panel(bpy.types.Panel):
    """サイドバーパネル"""
    bl_label = "Transform Saver"
    bl_idname = "TRANSFORMSAVER_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Transform Saver'

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # 新規グループ作成ボタン
        row = layout.row()
        row.scale_y = 1.3
        row.operator("object.transform_group_add", icon='ADD', text="New Group")

        layout.separator()

        # グループがない場合
        if len(scene.transform_groups) == 0:
            box = layout.box()
            box.label(text="No groups created", icon='INFO')
            return

        # 選択中オブジェクト名のセット
        selected_names = {obj.name for obj in context.selected_objects}

        # 各グループを表示
        for gi, group in enumerate(scene.transform_groups):
            box = layout.box()

            # グループヘッダー
            header = box.row(align=True)

            # 展開/折りたたみアイコン
            icon = 'TRIA_DOWN' if group.expanded else 'TRIA_RIGHT'
            op = header.operator("object.transform_group_toggle", text="", icon=icon, emboss=False)
            op.group_index = gi

            # グループ名（編集可能）
            header.prop(group, "name", text="")

            # アイテム数と選択数表示
            missing = count_missing_objects(group)
            selected_count = count_selected_in_group(group, context)

            info_parts = []
            if len(group.items) > 0:
                info_parts.append(str(len(group.items)))
            if selected_count > 0:
                info_parts.append(f"sel:{selected_count}")
            if missing > 0:
                info_parts.append(f"miss:{missing}")

            if info_parts:
                header.label(text=f"({', '.join(info_parts)})")

            # グループ削除
            op = header.operator("object.transform_group_remove", text="", icon='X')
            op.group_index = gi

            # 折りたたまれている場合はスキップ
            if not group.expanded:
                continue

            # 適用項目チェックボックス
            row = box.row(align=True)
            row.label(text="Apply:")
            row.prop(group, "apply_location", toggle=True)
            row.prop(group, "apply_rotation", toggle=True)
            row.prop(group, "apply_scale", toggle=True)

            # オブジェクト追加ボタンと選択ボタン
            row = box.row(align=True)
            sel_count = len(context.selected_objects)
            add_text = f"Add ({sel_count})" if sel_count > 0 else "Add"
            op = row.operator("object.transform_item_add", icon='ADD', text=add_text)
            op.group_index = gi

            # グループ全選択ボタン
            if len(group.items) > 0:
                op = row.operator("object.transform_select_group", icon='RESTRICT_SELECT_OFF', text="Select All")
                op.group_index = gi

            # 存在しないオブジェクトがある場合、クリーンボタンを表示
            if missing > 0:
                op = row.operator("object.transform_clean_missing", icon='BRUSH_DATA', text=f"Clean ({missing})")
                op.group_index = gi

            # 一括操作ボタン（All）
            if len(group.items) > 0:
                row = box.row(align=True)
                row.label(text="All:")
                op = row.operator("object.transform_save_all", text="Save", icon='FILE_TICK')
                op.group_index = gi
                op = row.operator("object.transform_zero_all", text="Zero", icon='LOOP_BACK')
                op.group_index = gi
                op = row.operator("object.transform_restore_all", text="Restore", icon='FILE_REFRESH')
                op.group_index = gi

            # 選択オブジェクトのみ操作ボタン
            if selected_count > 0:
                row = box.row(align=True)
                row.alert = True  # 強調表示
                row.label(text=f"Sel({selected_count}):")
                op = row.operator("object.transform_save_selected", text="Save", icon='FILE_TICK')
                op.group_index = gi
                op = row.operator("object.transform_zero_selected", text="Zero", icon='LOOP_BACK')
                op.group_index = gi
                op = row.operator("object.transform_restore_selected", text="Restore", icon='FILE_REFRESH')
                op.group_index = gi

            # アイテムリスト
            if len(group.items) == 0:
                row = box.row()
                row.separator(factor=2.0)
                row.label(text="Empty group", icon='INFO')
            else:
                # アイテム用のインデント付きカラム
                items_split = box.split(factor=0.03)
                items_split.column()  # 左側スペーサー
                items_col = items_split.column()

                for ii, item in enumerate(group.items):
                    obj_exists = item.object_name in bpy.data.objects
                    is_selected = item.object_name in selected_names

                    # 選択中のアイテムはボックスを強調
                    item_col = items_col.column()
                    item_box = item_col.box()

                    # ヘッダー行
                    row = item_box.row(align=True)

                    # 選択中ならオレンジ系アイコンで強調
                    if is_selected:
                        row.label(text="", icon='COLORSET_02_VEC')
                    else:
                        row.label(text="", icon='LAYER_USED')

                    # オブジェクト名ボタン
                    icon = 'OBJECT_DATA' if obj_exists else 'ERROR'
                    op = row.operator("object.transform_select", text=item.object_name, icon=icon)
                    op.group_index = gi
                    op.item_index = ii

                    if item.has_saved:
                        row.label(text="", icon='CHECKMARK')
                    else:
                        row.label(text="", icon='BLANK1')

                    op = row.operator("object.transform_item_remove", text="", icon='X')
                    op.group_index = gi
                    op.item_index = ii


# ==================== キーマップ ====================

addon_keymaps = []


def register_keymaps():
    wm = bpy.context.window_manager
    if wm.keyconfigs.addon:
        km = wm.keyconfigs.addon.keymaps.new(name='3D View', space_type='VIEW_3D')

        # Shift+Z: 選択オブジェクトをZero（全グループ対象）
        kmi = km.keymap_items.new("object.transform_zero_selected_global", 'Z', 'PRESS', shift=True)
        addon_keymaps.append((km, kmi))

        # Shift+R: 選択オブジェクトをRestore（全グループ対象）
        kmi = km.keymap_items.new("object.transform_restore_selected_global", 'R', 'PRESS', shift=True)
        addon_keymaps.append((km, kmi))


def unregister_keymaps():
    for km, kmi in addon_keymaps:
        km.keymap_items.remove(kmi)
    addon_keymaps.clear()


# ==================== グローバル選択操作 ====================

class TRANSFORMSAVER_OT_zero_selected_global(bpy.types.Operator):
    """選択中のオブジェクトを全グループからZero"""
    bl_idname = "object.transform_zero_selected_global"
    bl_label = "Zero Selected (All Groups)"
    bl_description = "Reset selected objects to Loc=0, Rot=0, Scale=1 (searches all groups)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        selected_names = {obj.name for obj in context.selected_objects}
        count = 0

        for group in scene.transform_groups:
            for item in group.items:
                if item.object_name not in selected_names:
                    continue
                success, _ = apply_zero(
                    item,
                    group.apply_location,
                    group.apply_rotation,
                    group.apply_scale
                )
                if success:
                    count += 1

        if count > 0:
            self.report({'INFO'}, f"Zeroed {count} selected objects")
        else:
            self.report({'WARNING'}, "No selected objects found in any group")

        return {'FINISHED'}


class TRANSFORMSAVER_OT_restore_selected_global(bpy.types.Operator):
    """選択中のオブジェクトを全グループからRestore"""
    bl_idname = "object.transform_restore_selected_global"
    bl_label = "Restore Selected (All Groups)"
    bl_description = "Restore selected objects to saved transforms (searches all groups)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        selected_names = {obj.name for obj in context.selected_objects}
        count = 0

        for group in scene.transform_groups:
            for item in group.items:
                if item.object_name not in selected_names:
                    continue
                success, _ = apply_restore(
                    item,
                    group.apply_location,
                    group.apply_rotation,
                    group.apply_scale
                )
                if success:
                    count += 1

        if count > 0:
            self.report({'INFO'}, f"Restored {count} selected objects")
        else:
            self.report({'WARNING'}, "No selected objects found in any group")

        return {'FINISHED'}


classes = (
    TransformData,
    TransformGroup,
    TRANSFORMSAVER_OT_group_add,
    TRANSFORMSAVER_OT_group_remove,
    TRANSFORMSAVER_OT_group_toggle,
    TRANSFORMSAVER_OT_item_add,
    TRANSFORMSAVER_OT_item_remove,
    TRANSFORMSAVER_OT_clean_missing,
    TRANSFORMSAVER_OT_save_all,
    TRANSFORMSAVER_OT_zero_all,
    TRANSFORMSAVER_OT_restore_all,
    TRANSFORMSAVER_OT_save_selected,
    TRANSFORMSAVER_OT_zero_selected,
    TRANSFORMSAVER_OT_restore_selected,
    TRANSFORMSAVER_OT_zero_selected_global,
    TRANSFORMSAVER_OT_restore_selected_global,
    TRANSFORMSAVER_OT_select,
    TRANSFORMSAVER_OT_select_group,
    TRANSFORMSAVER_PT_panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.transform_groups = CollectionProperty(type=TransformGroup)
    register_keymaps()


def unregister():
    unregister_keymaps()
    del bpy.types.Scene.transform_groups
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
