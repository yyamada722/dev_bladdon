bl_info = {
    "name": "Super Renamer",
    "author": "CGSLAB",
    "version": (1, 0, 0),
    "blender": (4, 0, 0),
    "location": "3D Viewport > N-Panel > Super Renamer",
    "description": "Ultimate batch renaming tool for objects, bones, materials, collections, vertex groups, and shape keys",
    "category": "Object",
}

import bpy
import re
from bpy.props import (
    StringProperty,
    EnumProperty,
    BoolProperty,
    IntProperty,
    PointerProperty,
)
from bpy.types import Operator, Panel, PropertyGroup


# ------------------------------------------------------------
# Utility Functions
# ------------------------------------------------------------

def to_snake_case(name: str) -> str:
    """Convert to snake_case"""
    # CamelCase -> snake_case
    s = re.sub(r'(?<!^)(?=[A-Z])', '_', name)
    # Replace spaces and hyphens with underscores
    s = re.sub(r'[\s\-]+', '_', s)
    # Remove consecutive underscores
    s = re.sub(r'_+', '_', s)
    return s.lower().strip('_')


def to_camel_case(name: str) -> str:
    """Convert to CamelCase (PascalCase)"""
    # Split by underscore, space, hyphen
    parts = re.split(r'[_\s\-]+', name)
    return ''.join(word.capitalize() for word in parts if word)


def to_lower_camel_case(name: str) -> str:
    """Convert to lowerCamelCase"""
    camel = to_camel_case(name)
    if camel:
        return camel[0].lower() + camel[1:]
    return camel


def to_kebab_case(name: str) -> str:
    """Convert to kebab-case"""
    snake = to_snake_case(name)
    return snake.replace('_', '-')


def to_title_case(name: str) -> str:
    """Convert to Title Case"""
    parts = re.split(r'[_\s\-]+', name)
    return ' '.join(word.capitalize() for word in parts if word)


def apply_case_conversion(name: str, case_type: str) -> str:
    """Apply case conversion based on type"""
    if case_type == 'UPPER':
        return name.upper()
    elif case_type == 'LOWER':
        return name.lower()
    elif case_type == 'TITLE':
        return to_title_case(name)
    elif case_type == 'SNAKE':
        return to_snake_case(name)
    elif case_type == 'CAMEL':
        return to_camel_case(name)
    elif case_type == 'LOWER_CAMEL':
        return to_lower_camel_case(name)
    elif case_type == 'KEBAB':
        return to_kebab_case(name)
    return name


# ------------------------------------------------------------
# Property Group
# ------------------------------------------------------------

class SuperRenamerProperties(PropertyGroup):
    # Target selection
    target_type: EnumProperty(
        name="Target",
        items=[
            ('OBJECT', "Objects", "Rename objects"),
            ('BONE', "Bones", "Rename bones (armature edit/pose mode)"),
            ('MATERIAL', "Materials", "Rename materials"),
            ('COLLECTION', "Collections", "Rename collections"),
            ('VERTEX_GROUP', "Vertex Groups", "Rename vertex groups"),
            ('SHAPE_KEY', "Shape Keys", "Rename shape keys"),
        ],
        default='OBJECT'
    )

    # Scope
    scope: EnumProperty(
        name="Scope",
        items=[
            ('SELECTED', "Selected", "Apply to selected items only"),
            ('ALL', "All", "Apply to all items"),
        ],
        default='SELECTED'
    )

    # Operation mode
    operation: EnumProperty(
        name="Operation",
        items=[
            ('REPLACE', "Find & Replace", "Search and replace text"),
            ('PREFIX', "Add Prefix", "Add prefix to names"),
            ('SUFFIX', "Add Suffix", "Add suffix to names"),
            ('REMOVE_PREFIX', "Remove Prefix", "Remove prefix from names"),
            ('REMOVE_SUFFIX', "Remove Suffix", "Remove suffix from names"),
            ('NUMBERING', "Numbering", "Add sequential numbers"),
            ('CASE', "Case Convert", "Change letter case"),
            ('REGEX', "Regex Replace", "Replace using regular expressions"),
        ],
        default='REPLACE'
    )

    # Find/Replace
    find_string: StringProperty(
        name="Find",
        description="Text to find",
        default=""
    )
    replace_string: StringProperty(
        name="Replace",
        description="Text to replace with",
        default=""
    )
    case_sensitive: BoolProperty(
        name="Case Sensitive",
        description="Match case when searching",
        default=True
    )

    # Prefix/Suffix
    prefix_string: StringProperty(
        name="Prefix",
        description="Prefix to add/remove",
        default=""
    )
    suffix_string: StringProperty(
        name="Suffix",
        description="Suffix to add/remove",
        default=""
    )

    # Numbering
    number_start: IntProperty(
        name="Start",
        description="Starting number",
        default=1,
        min=0
    )
    number_step: IntProperty(
        name="Step",
        description="Increment step",
        default=1,
        min=1
    )
    number_digits: IntProperty(
        name="Digits",
        description="Number of digits (zero padding)",
        default=3,
        min=1,
        max=10
    )
    number_separator: StringProperty(
        name="Separator",
        description="Separator before number",
        default="_"
    )
    number_base_name: StringProperty(
        name="Base Name",
        description="Base name for numbering (empty = keep original)",
        default=""
    )
    number_position: EnumProperty(
        name="Position",
        items=[
            ('SUFFIX', "Suffix", "Add number at end"),
            ('PREFIX', "Prefix", "Add number at beginning"),
        ],
        default='SUFFIX'
    )

    # Case conversion
    case_type: EnumProperty(
        name="Case Type",
        items=[
            ('UPPER', "UPPERCASE", "Convert to uppercase"),
            ('LOWER', "lowercase", "Convert to lowercase"),
            ('TITLE', "Title Case", "Capitalize each word"),
            ('SNAKE', "snake_case", "Convert to snake_case"),
            ('CAMEL', "CamelCase", "Convert to CamelCase"),
            ('LOWER_CAMEL', "lowerCamelCase", "Convert to lowerCamelCase"),
            ('KEBAB', "kebab-case", "Convert to kebab-case"),
        ],
        default='SNAKE'
    )

    # Regex
    regex_pattern: StringProperty(
        name="Pattern",
        description="Regular expression pattern",
        default=""
    )
    regex_replace: StringProperty(
        name="Replace",
        description="Replacement pattern (use \\1, \\2 for groups)",
        default=""
    )


# ------------------------------------------------------------
# Core Rename Functions
# ------------------------------------------------------------

def get_target_items(context, props):
    """Get items to rename based on target type and scope"""
    items = []

    if props.target_type == 'OBJECT':
        if props.scope == 'SELECTED':
            items = list(context.selected_objects)
        else:
            items = list(bpy.data.objects)

    elif props.target_type == 'BONE':
        armature = context.active_object
        if armature and armature.type == 'ARMATURE':
            if context.mode == 'EDIT_ARMATURE':
                if props.scope == 'SELECTED':
                    items = [b for b in armature.data.edit_bones if b.select]
                else:
                    items = list(armature.data.edit_bones)
            elif context.mode == 'POSE':
                if props.scope == 'SELECTED':
                    items = [b.bone for b in context.selected_pose_bones]
                else:
                    items = list(armature.data.bones)
            else:
                # Object mode - use bones directly
                items = list(armature.data.bones)

    elif props.target_type == 'MATERIAL':
        if props.scope == 'SELECTED':
            mats = set()
            for obj in context.selected_objects:
                for slot in obj.material_slots:
                    if slot.material:
                        mats.add(slot.material)
            items = list(mats)
        else:
            items = list(bpy.data.materials)

    elif props.target_type == 'COLLECTION':
        if props.scope == 'SELECTED':
            cols = set()
            for obj in context.selected_objects:
                for col in obj.users_collection:
                    cols.add(col)
            items = list(cols)
        else:
            items = list(bpy.data.collections)

    elif props.target_type == 'VERTEX_GROUP':
        obj = context.active_object
        if obj and obj.type == 'MESH' and obj.vertex_groups:
            items = list(obj.vertex_groups)

    elif props.target_type == 'SHAPE_KEY':
        obj = context.active_object
        if obj and obj.type == 'MESH' and obj.data.shape_keys:
            items = list(obj.data.shape_keys.key_blocks)

    return items


def apply_rename(name: str, props) -> str:
    """Apply rename operation to a name"""
    new_name = name

    if props.operation == 'REPLACE':
        if props.find_string:
            if props.case_sensitive:
                new_name = name.replace(props.find_string, props.replace_string)
            else:
                pattern = re.compile(re.escape(props.find_string), re.IGNORECASE)
                new_name = pattern.sub(props.replace_string, name)

    elif props.operation == 'PREFIX':
        new_name = props.prefix_string + name

    elif props.operation == 'SUFFIX':
        new_name = name + props.suffix_string

    elif props.operation == 'REMOVE_PREFIX':
        if props.prefix_string and name.startswith(props.prefix_string):
            new_name = name[len(props.prefix_string):]

    elif props.operation == 'REMOVE_SUFFIX':
        if props.suffix_string and name.endswith(props.suffix_string):
            new_name = name[:-len(props.suffix_string)]

    elif props.operation == 'CASE':
        new_name = apply_case_conversion(name, props.case_type)

    elif props.operation == 'REGEX':
        if props.regex_pattern:
            try:
                new_name = re.sub(props.regex_pattern, props.regex_replace, name)
            except re.error:
                pass  # Invalid regex, keep original

    return new_name


def apply_numbering(items, props) -> list:
    """Apply numbering to items, returns list of (item, new_name)"""
    result = []
    num = props.number_start

    for item in items:
        if props.number_base_name:
            base = props.number_base_name
        else:
            base = item.name

        num_str = str(num).zfill(props.number_digits)

        if props.number_position == 'SUFFIX':
            new_name = f"{base}{props.number_separator}{num_str}"
        else:
            new_name = f"{num_str}{props.number_separator}{base}"

        result.append((item, new_name))
        num += props.number_step

    return result


# ------------------------------------------------------------
# Operators
# ------------------------------------------------------------

def get_preview_data(context, props):
    """Generate preview data as list of (old_name, new_name) tuples"""
    items = get_target_items(context, props)
    preview = []

    if props.operation == 'NUMBERING':
        for item, new_name in apply_numbering(items, props):
            preview.append((item.name, new_name))
    else:
        for item in items:
            old_name = item.name
            new_name = apply_rename(old_name, props)
            preview.append((old_name, new_name))

    return preview


class SUPERRENAMER_OT_rename(Operator):
    """Execute the rename operation with preview"""
    bl_idname = "superrenamer.rename"
    bl_label = "Rename"
    bl_options = {'REGISTER', 'UNDO'}

    # Store preview data for drawing
    _preview_data = []

    def invoke(self, context, event):
        props = context.scene.super_renamer
        items = get_target_items(context, props)

        if not items:
            self.report({'WARNING'}, "No items to rename")
            return {'CANCELLED'}

        # Generate preview
        SUPERRENAMER_OT_rename._preview_data = get_preview_data(context, props)

        # Check if any changes
        changes = [(old, new) for old, new in self._preview_data if old != new]
        if not changes:
            self.report({'INFO'}, "No changes to make")
            return {'CANCELLED'}

        # Show dialog
        return context.window_manager.invoke_props_dialog(self, width=400)

    def draw(self, context):
        layout = self.layout

        # Header
        changes = [(old, new) for old, new in self._preview_data if old != new]
        layout.label(text=f"Rename {len(changes)} item(s)?", icon='QUESTION')
        layout.separator()

        # Preview list in a box
        box = layout.box()

        # Column headers
        row = box.row()
        row.label(text="Before")
        row.label(text="")
        row.label(text="After")

        # Separator line
        box.separator(factor=0.5)

        # Show changes (limit to 20 for performance)
        display_count = 0
        max_display = 20

        for old_name, new_name in self._preview_data:
            if old_name != new_name:
                row = box.row()
                # Truncate long names
                old_display = old_name[:25] + "..." if len(old_name) > 28 else old_name
                new_display = new_name[:25] + "..." if len(new_name) > 28 else new_name
                row.label(text=old_display)
                row.label(text="", icon='FORWARD')
                row.label(text=new_display)
                display_count += 1

                if display_count >= max_display:
                    remaining = len(changes) - max_display
                    if remaining > 0:
                        box.label(text=f"... and {remaining} more", icon='INFO')
                    break

    def execute(self, context):
        props = context.scene.super_renamer
        items = get_target_items(context, props)

        if not items:
            self.report({'WARNING'}, "No items to rename")
            return {'CANCELLED'}

        count = 0

        if props.operation == 'NUMBERING':
            for item, new_name in apply_numbering(items, props):
                if item.name != new_name:
                    item.name = new_name
                    count += 1
        else:
            for item in items:
                old_name = item.name
                new_name = apply_rename(old_name, props)
                if old_name != new_name:
                    item.name = new_name
                    count += 1

        self.report({'INFO'}, f"Renamed {count} item(s)")
        return {'FINISHED'}


# ------------------------------------------------------------
# UI Panel
# ------------------------------------------------------------

class SUPERRENAMER_PT_main(Panel):
    bl_label = "Super Renamer"
    bl_idname = "SUPERRENAMER_PT_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Super Renamer"

    def draw(self, context):
        layout = self.layout
        props = context.scene.super_renamer

        # Target & Scope
        box = layout.box()
        box.label(text="Target", icon='OBJECT_DATA')
        row = box.row()
        row.prop(props, "target_type", text="")
        row.prop(props, "scope", text="")

        # Show count
        items = get_target_items(context, props)
        box.label(text=f"Found: {len(items)} item(s)", icon='INFO')

        layout.separator()

        # Operation
        box = layout.box()
        box.label(text="Operation", icon='MODIFIER')
        box.prop(props, "operation", text="")

        # Operation-specific options with descriptions and examples
        if props.operation == 'REPLACE':
            # Description
            col = box.column(align=True)
            col.label(text="Find text and replace with new text.", icon='INFO')
            col.label(text="Example: 'Cube' -> 'Box'  =>  MyCube -> MyBox")
            box.separator(factor=0.5)
            # Options
            box.prop(props, "find_string")
            box.prop(props, "replace_string")
            box.prop(props, "case_sensitive")

        elif props.operation == 'PREFIX':
            col = box.column(align=True)
            col.label(text="Add text to the beginning of names.", icon='INFO')
            col.label(text="Example: 'SM_'  =>  Cube -> SM_Cube")
            box.separator(factor=0.5)
            box.prop(props, "prefix_string", text="Add")

        elif props.operation == 'SUFFIX':
            col = box.column(align=True)
            col.label(text="Add text to the end of names.", icon='INFO')
            col.label(text="Example: '_low'  =>  Cube -> Cube_low")
            box.separator(factor=0.5)
            box.prop(props, "suffix_string", text="Add")

        elif props.operation == 'REMOVE_PREFIX':
            col = box.column(align=True)
            col.label(text="Remove text from the beginning.", icon='INFO')
            col.label(text="Example: 'SM_'  =>  SM_Cube -> Cube")
            box.separator(factor=0.5)
            box.prop(props, "prefix_string", text="Remove")

        elif props.operation == 'REMOVE_SUFFIX':
            col = box.column(align=True)
            col.label(text="Remove text from the end.", icon='INFO')
            col.label(text="Example: '_low'  =>  Cube_low -> Cube")
            box.separator(factor=0.5)
            box.prop(props, "suffix_string", text="Remove")

        elif props.operation == 'NUMBERING':
            col = box.column(align=True)
            col.label(text="Add sequential numbers to names.", icon='INFO')
            col.label(text="Example: Base='Item', Start=1, Digits=3")
            col.label(text="         => Item_001, Item_002, Item_003...")
            box.separator(factor=0.5)
            box.prop(props, "number_base_name")
            row = box.row(align=True)
            row.prop(props, "number_start")
            row.prop(props, "number_step")
            row = box.row(align=True)
            row.prop(props, "number_digits")
            row.prop(props, "number_separator")
            box.prop(props, "number_position")

        elif props.operation == 'CASE':
            col = box.column(align=True)
            col.label(text="Convert letter case or naming style.", icon='INFO')
            col.label(text="Examples:")
            col.label(text="  snake_case: MyObject -> my_object")
            col.label(text="  CamelCase: my_object -> MyObject")
            box.separator(factor=0.5)
            box.prop(props, "case_type", text="")

        elif props.operation == 'REGEX':
            col = box.column(align=True)
            col.label(text="Advanced: Use regular expressions.", icon='INFO')
            col.label(text="Example: Pattern='(.+)_(\d+)'")
            col.label(text="         Replace='\\2_\\1'")
            col.label(text="         => Cube_001 -> 001_Cube")
            box.separator(factor=0.5)
            box.prop(props, "regex_pattern")
            box.prop(props, "regex_replace")

        layout.separator()

        # Action button
        row = layout.row()
        row.scale_y = 1.8
        row.operator("superrenamer.rename", text="Rename...", icon='GREASEPENCIL')


# ------------------------------------------------------------
# Registration
# ------------------------------------------------------------

classes = [
    SuperRenamerProperties,
    SUPERRENAMER_OT_rename,
    SUPERRENAMER_PT_main,
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.super_renamer = PointerProperty(type=SuperRenamerProperties)


def unregister():
    del bpy.types.Scene.super_renamer
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
