import time

import bmesh
import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, IntProperty

_vertex_count_cache = {}
_selected_vertex_count_cache = {}


def calculate_game_vertex_count(mesh, precision=5, selected_only=False):
    if not mesh.polygons:
        if selected_only:
            count = sum(1 for v in mesh.vertices if v.select)
        else:
            count = len(mesh.vertices)
        return count, 0, 0

    corner_normals = mesh.corner_normals
    uv_layers = mesh.uv_layers

    unique_corners = set()
    unique_normal_corners = set()
    unique_uv_corners = set()
    unique_vertices = set()

    for loop in mesh.loops:
        vertex_index = loop.vertex_index
        if selected_only and not mesh.vertices[vertex_index].select:
            continue
        unique_vertices.add(vertex_index)

        normal = corner_normals[loop.index].vector
        normal_key = (
            round(normal.x, precision),
            round(normal.z, precision),
        )

        uv_key = []
        for uv_layer in uv_layers:
            uv = uv_layer.data[loop.index].uv
            uv_key.append(round(uv.x, precision))
            uv_key.append(round(uv.y, precision))
        uv_key = tuple(uv_key)

        unique_corners.add((vertex_index, normal_key, uv_key))
        unique_normal_corners.add((vertex_index, normal_key))
        unique_uv_corners.add((vertex_index, uv_key))

    base_count = len(unique_vertices)
    normal_added = len(unique_normal_corners) - base_count
    uv_added = len(unique_uv_corners) - base_count

    return len(unique_corners), normal_added, uv_added


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

    start_time = time.perf_counter()
    real_count, normal_added, uv_added = calculate_game_vertex_count(mesh, precision)
    elapsed_time = time.perf_counter() - start_time
    blender_count = len(mesh.vertices)

    _vertex_count_cache[obj.name] = (real_count, blender_count, normal_added, uv_added, elapsed_time)
    return real_count, blender_count, normal_added, uv_added, elapsed_time


def get_preferences(context):
    addon = context.preferences.addons.get(__name__)
    return addon.preferences if addon else None


def is_countable_mesh_object(obj):
    return obj is not None and obj.type == "MESH" and obj.data is not None


def get_target_objects(context):
    active = context.active_object
    if active is not None and active.mode == "EDIT":
        objs = context.objects_in_mode_unique_data
    else:
        objs = context.selected_objects
        if not objs and active is not None:
            objs = [active]
    return [o for o in objs if is_countable_mesh_object(o)]


def get_selection_signature(bm):
    return (len(bm.verts), tuple(v.index for v in bm.verts if v.select))


def get_selected_vertex_counts(context, obj):
    prefs = get_preferences(context)
    precision = prefs.precision if prefs else 5

    bm = bmesh.from_edit_mesh(obj.data)
    signature = get_selection_signature(bm)

    cached = _selected_vertex_count_cache.get(obj.name)
    if cached is not None and cached[0] == signature:
        return cached[1]

    blender_count = len(signature[1])

    temp_mesh = bpy.data.meshes.new("GameVertexCount_temp")
    try:
        bm.to_mesh(temp_mesh)
        start_time = time.perf_counter()
        real_count, normal_added, uv_added = calculate_game_vertex_count(temp_mesh, precision, selected_only=True)
        elapsed_time = time.perf_counter() - start_time
    finally:
        bpy.data.meshes.remove(temp_mesh)

    result = (real_count, blender_count, normal_added, uv_added, elapsed_time)
    _selected_vertex_count_cache[obj.name] = (signature, result)
    return result


def draw_vertex_count_stats(layout, context, objs):
    prefs = get_preferences(context)
    enable_profiling = prefs.enable_profiling if prefs else False
    active = context.active_object
    multiple = len(objs) > 1

    if active is not None and active.mode == "EDIT":
        sel_real_count = sel_blender_count = sel_normal_added = sel_uv_added = 0
        sel_elapsed_time = 0.0
        for obj in objs:
            real_count, blender_count, normal_added, uv_added, elapsed_time = get_selected_vertex_counts(
                context, obj
            )
            sel_real_count += real_count
            sel_blender_count += blender_count
            sel_normal_added += normal_added
            sel_uv_added += uv_added
            sel_elapsed_time += elapsed_time

        sel_col = layout.column(align=True)
        if multiple:
            sel_col.label(text=f"Selected Objects: {len(objs)}")
        sel_col.label(text=f"Selected Vertices: {sel_blender_count:,}")
        sel_col.label(text=f"UV Vertices: {sel_uv_added:,}")
        sel_col.label(text=f"Normal Vertices: {sel_normal_added:,}")
        sel_col.label(text=f"Selected Game Vertices: {sel_real_count:,}")
        if enable_profiling:
            sel_col.label(text=f"Calculation Time: {sel_elapsed_time * 1000:.2f} ms")
        return

    use_modifiers = prefs.use_modifiers if prefs else True
    real_count = blender_count = normal_added = uv_added = 0
    elapsed_time = 0.0
    for obj in objs:
        counts = _vertex_count_cache.get(obj.name)
        if counts is None:
            counts = get_object_vertex_counts(context, obj, use_modifiers)
        obj_real_count, obj_blender_count, obj_normal_added, obj_uv_added, obj_elapsed_time = counts
        real_count += obj_real_count
        blender_count += obj_blender_count
        normal_added += obj_normal_added
        uv_added += obj_uv_added
        elapsed_time += obj_elapsed_time

    col = layout.column(align=True)
    if multiple:
        col.label(text=f"Selected Objects: {len(objs)}")
    col.label(text=f"Vertices: {blender_count:,}")
    col.label(text=f"UV Vertices: {uv_added:,}")
    col.label(text=f"Normal Vertices: {normal_added:,}")
    col.label(text=f"Game Vertices: {real_count:,}")
    if enable_profiling:
        col.label(text=f"Calculation Time: {elapsed_time * 1000:.2f} ms")


class VIEW3D_PT_game_vertex_count(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Item"
    bl_label = "Game Vertex Count"

    @classmethod
    def poll(cls, context):
        return bool(get_target_objects(context))

    def draw(self, context):
        draw_vertex_count_stats(self.layout, context, get_target_objects(context))


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
    enable_profiling: BoolProperty(
        name="Enable Profiling",
        description="Display how long the vertex count calculation took, to help profile the add-on's performance impact",
        default=False,
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "use_modifiers")
        layout.prop(self, "precision")
        layout.prop(self, "enable_profiling")


@persistent
def on_depsgraph_update(scene, depsgraph):
    context = bpy.context
    objs = get_target_objects(context)
    if not objs:
        return

    watched_names = {o.name for o in objs} | {o.data.name for o in objs}
    for update in depsgraph.updates:
        if update.id.name in watched_names:
            prefs = get_preferences(context)
            use_modifiers = prefs.use_modifiers if prefs else True
            for obj in objs:
                get_object_vertex_counts(context, obj, use_modifiers)
            for area in context.screen.areas:
                if area.type in {"VIEW_3D", "PROPERTIES"}:
                    area.tag_redraw()
            break


@persistent
def on_load_post(_dummy):
    _vertex_count_cache.clear()
    _selected_vertex_count_cache.clear()


classes = (
    VIEW3D_PT_game_vertex_count,
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
    _selected_vertex_count_cache.clear()


if __name__ == "__main__":
    register()
