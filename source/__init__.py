import bmesh
import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, IntProperty

_vertex_count_cache = {}


def calculate_game_vertex_count(mesh, precision=5, selected_only=False):
    if not mesh.polygons:
        if selected_only:
            return sum(1 for v in mesh.vertices if v.select)
        return len(mesh.vertices)

    corner_normals = mesh.corner_normals
    uv_layers = mesh.uv_layers

    unique_corners = set()
    for loop in mesh.loops:
        if selected_only and not mesh.vertices[loop.vertex_index].select:
            continue
        normal = corner_normals[loop.index].vector
        key = [
            loop.vertex_index,
            round(normal.x, precision),
            round(normal.y, precision),
            round(normal.z, precision),
        ]
        for uv_layer in uv_layers:
            uv = uv_layer.data[loop.index].uv
            key.append(round(uv.x, precision))
            key.append(round(uv.y, precision))
        unique_corners.add(tuple(key))

    return len(unique_corners)


def get_evaluated_mesh(context, obj):
    depsgraph = context.evaluated_depsgraph_get()
    obj_eval = obj.evaluated_get(depsgraph)
    return obj_eval.data


def get_object_vertex_counts(context, obj, use_modifiers=True):
    if use_modifiers:
        mesh = get_evaluated_mesh(context, obj)
    else:
        mesh = obj.data

    prefs = get_preferences(context)
    precision = prefs.precision if prefs else 5

    real_count = calculate_game_vertex_count(mesh, precision)
    blender_count = len(mesh.vertices)

    _vertex_count_cache[obj.name] = (real_count, blender_count)
    return real_count, blender_count


def get_preferences(context):
    addon = context.preferences.addons.get(__name__)
    return addon.preferences if addon else None


def is_countable_mesh_object(obj):
    return obj is not None and obj.type == "MESH" and obj.data is not None


def get_selected_vertex_counts(context, obj):
    prefs = get_preferences(context)
    precision = prefs.precision if prefs else 5

    bm = bmesh.from_edit_mesh(obj.data)
    blender_count = sum(1 for v in bm.verts if v.select)

    temp_mesh = bpy.data.meshes.new("GameVertexCount_temp")
    try:
        bm.to_mesh(temp_mesh)
        real_count = calculate_game_vertex_count(temp_mesh, precision, selected_only=True)
    finally:
        bpy.data.meshes.remove(temp_mesh)

    return real_count, blender_count


def draw_vertex_count_stats(layout, context, obj):
    if obj.mode == "EDIT":
        sel_real_count, sel_blender_count = get_selected_vertex_counts(context, obj)
        sel_col = layout.column(align=True)
        sel_col.label(text=f"Selected Vertices: {sel_blender_count:,}")
        sel_col.label(text=f"Selected Game Vertices: {sel_real_count:,}")
        return

    prefs = get_preferences(context)
    use_modifiers = prefs.use_modifiers if prefs else True
    counts = _vertex_count_cache.get(obj.name)
    if counts is None:
        counts = get_object_vertex_counts(context, obj, use_modifiers)
    real_count, blender_count = counts

    col = layout.column(align=True)
    col.label(text=f"Vertices: {blender_count:,}")
    col.label(text=f"Game Vertices: {real_count:,}")


class VIEW3D_PT_game_vertex_count(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Item"
    bl_label = "Game Vertex Count"

    @classmethod
    def poll(cls, context):
        return is_countable_mesh_object(context.active_object)

    def draw(self, context):
        draw_vertex_count_stats(self.layout, context, context.active_object)


class DATA_PT_game_vertex_count(bpy.types.Panel):
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "data"
    bl_label = "Game Vertex Count"

    @classmethod
    def poll(cls, context):
        return is_countable_mesh_object(context.active_object)

    def draw(self, context):
        draw_vertex_count_stats(self.layout, context, context.active_object)


class GameVertexCountPreferences(bpy.types.AddonPreferences):
    bl_idname = __name__

    use_modifiers: BoolProperty(
        name="Apply Modifiers",
        description="Calculate the count on the evaluated mesh (with modifiers applied) instead of the base mesh",
        default=True,
    )
    precision: IntProperty(
        name="Precision",
        description="Number of decimal places used to compare normals and UVs",
        default=5,
        min=1,
        max=8,
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "use_modifiers")
        layout.prop(self, "precision")


@persistent
def on_depsgraph_update(scene, depsgraph):
    context = bpy.context
    obj = context.active_object
    if not is_countable_mesh_object(obj):
        return

    for update in depsgraph.updates:
        if update.id.name == obj.name or update.id.name == obj.data.name:
            prefs = get_preferences(context)
            use_modifiers = prefs.use_modifiers if prefs else True
            get_object_vertex_counts(context, obj, use_modifiers)
            for area in context.screen.areas:
                if area.type in {"VIEW_3D", "PROPERTIES"}:
                    area.tag_redraw()
            break


@persistent
def on_load_post(_dummy):
    _vertex_count_cache.clear()


classes = (
    VIEW3D_PT_game_vertex_count,
    DATA_PT_game_vertex_count,
    GameVertexCountPreferences,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.app.handlers.depsgraph_update_post.append(on_depsgraph_update)
    bpy.app.handlers.load_post.append(on_load_post)


def unregister():
    if on_depsgraph_update in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(on_depsgraph_update)
    if on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(on_load_post)

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    _vertex_count_cache.clear()


if __name__ == "__main__":
    register()
