"""
XYZ Importer Operator
Loads space-delimited .xyz bathymetry files and creates Blender point cloud objects.
"""

import os

import bpy
import numpy as np
from bpy_extras.io_utils import ExportHelper, ImportHelper
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import Operator


DELIMITER_MAP = {
    'WHITESPACE': None,
    'TAB': '\t',
    'COMMA': ',',
    'SEMICOLON': ';',
}


def _parse_xyz_file(filepath, delimiter_key, skip_lines):
    """Load numeric columns from an XYZ text file into an (N, 3+) array."""
    delimiter = DELIMITER_MAP[delimiter_key]

    with open(filepath, 'r', encoding='utf-8', errors='replace') as handle:
        for _ in range(skip_lines):
            next(handle, None)

        if delimiter is None:
            data = np.loadtxt(handle, dtype=np.float64)
        else:
            data = np.loadtxt(handle, dtype=np.float64, delimiter=delimiter)

    if data.size == 0:
        raise ValueError("File contains no numeric data")

    if data.ndim == 1:
        if data.shape[0] < 3:
            raise ValueError("Each row must contain at least X, Y, and Z values")
        data = data.reshape(1, -1)

    if data.shape[1] < 3:
        raise ValueError(f"Expected at least 3 columns, found {data.shape[1]}")

    return data


def _select_columns(data, col_x, col_y, col_z):
    n_cols = data.shape[1]
    for name, index in (("X", col_x), ("Y", col_y), ("Z", col_z)):
        if index < 0 or index >= n_cols:
            raise ValueError(f"{name} column index {index} is out of range (0-{n_cols - 1})")

    return np.column_stack((data[:, col_x], data[:, col_y], data[:, col_z]))


def _subsample_points(coords, max_points):
    if max_points <= 0 or len(coords) <= max_points:
        return coords

    rng = np.random.default_rng(0)
    indices = rng.choice(len(coords), size=max_points, replace=False)
    indices.sort()
    return coords[indices]


def _sanitize_coordinates(coords):
    coords = np.asarray(coords, dtype=np.float64)
    invalid = ~np.isfinite(coords).all(axis=1)
    if np.any(invalid):
        coords = coords[~invalid]
    if len(coords) == 0:
        raise ValueError("No valid coordinates remain after filtering NaN/Inf values")
    return coords


def _apply_center(coords, center_mode, center_lon, center_lat):
    """Return coordinates shifted to the chosen origin and the offset that was removed."""
    offset = np.zeros(3, dtype=np.float64)
    if center_mode == 'CENTROID':
        offset = coords.mean(axis=0)
        coords = coords - offset
    elif center_mode == 'GEOGRAPHIC':
        offset[0] = center_lon
        offset[1] = center_lat
        coords[:, 0] -= center_lon
        coords[:, 1] -= center_lat
    return coords, offset


def _reverse_import_transform(coords, offset, xy_scale, z_scale, invert_z):
    """Convert local Blender coordinates back to file coordinates."""
    coords = np.asarray(coords, dtype=np.float64).copy()

    if xy_scale != 0.0:
        coords[:, 0] /= xy_scale
        coords[:, 1] /= xy_scale

    if z_scale != 0.0:
        coords[:, 2] /= z_scale

    if invert_z:
        coords[:, 2] *= -1.0

    coords += offset
    return coords


def _extract_local_coordinates(obj):
    """Read vertex/point positions from a mesh or point cloud object."""
    data = obj.data

    if isinstance(data, bpy.types.Mesh):
        count = len(data.vertices)
        if count == 0:
            raise ValueError("Mesh has no vertices")
        coords = np.empty(count * 3, dtype=np.float64)
        data.vertices.foreach_get("co", coords)
        return coords.reshape(count, 3)

    if isinstance(data, bpy.types.PointCloud):
        count = len(data.points)
        if count == 0:
            raise ValueError("Point cloud has no points")
        position_attr = data.attributes.get("position")
        if position_attr is None:
            raise ValueError("Point cloud has no position attribute")
        coords = np.empty(count * 3, dtype=np.float64)
        position_attr.data.foreach_get("vector", coords)
        return coords.reshape(count, 3)

    raise ValueError(f"Unsupported object data type: {type(data).__name__}")


def _apply_object_transform(coords, obj):
    """Transform local coordinates into world space."""
    matrix = np.array(obj.matrix_world, dtype=np.float64)
    ones = np.ones((len(coords), 1), dtype=np.float64)
    homogenous = np.hstack((coords, ones))
    return homogenous @ matrix.T[:, :3]


def _get_object_metadata(obj):
    """Return import metadata stored on an object, with defaults when absent."""
    offset = np.zeros(3, dtype=np.float64)
    if "xyz_importer_offset" in obj:
        offset = np.array(obj["xyz_importer_offset"], dtype=np.float64)

    return {
        "offset": offset,
        "xy_scale": float(obj.get("xyz_importer_xy_scale", 1.0)),
        "z_scale": float(obj.get("xyz_importer_z_scale", 1.0)),
        "invert_z": bool(obj.get("xyz_importer_invert_z", False)),
        "has_metadata": "xyz_importer_offset" in obj,
    }


def _write_xyz_file(filepath, coords, delimiter_key, precision):
    """Write coordinates to a delimited text file."""
    delimiter = DELIMITER_MAP[delimiter_key]
    fmt = f"%.{precision}f"

    if delimiter is None:
        np.savetxt(filepath, coords, fmt=fmt)
    else:
        np.savetxt(filepath, coords, fmt=fmt, delimiter=delimiter)


def _create_point_cloud_object(name, coords):
    """Create a Blender point cloud object from an (N, 3) coordinate array."""
    pointcloud = bpy.data.pointclouds.new(name=name)
    pointcloud.resize(len(coords))

    position_attr = pointcloud.attributes.get("position")
    if position_attr is None:
        position_attr = pointcloud.attributes.new("position", 'FLOAT_VECTOR', 'POINT')

    position_attr.data.foreach_set("vector", coords.astype(np.float32).ravel())
    pointcloud.update_tag()

    obj = bpy.data.objects.new(name, pointcloud)
    return obj


def _create_mesh_vertices_object(name, coords):
    """Create a mesh object containing vertices only (no edges or faces)."""
    mesh = bpy.data.meshes.new(name=name)
    mesh.vertices.add(len(coords))
    mesh.vertices.foreach_set("co", coords.astype(np.float32).ravel())
    mesh.update()
    return bpy.data.objects.new(name, mesh)


class ImportXYZ(Operator, ImportHelper):
    """Import a space-delimited XYZ file as a point cloud"""
    bl_idname = "import_scene.xyz"
    bl_label = "Import XYZ Point Cloud"
    bl_options = {'PRESET', 'UNDO'}

    filename_ext = ".xyz"
    filter_glob: StringProperty(
        default="*.xyz",
        options={'HIDDEN'},
        maxlen=255,
    )

    delimiter: EnumProperty(
        name="Delimiter",
        description="Column delimiter used in the file",
        items=[
            ('WHITESPACE', "Whitespace", "One or more spaces (default for bathymetry XYZ)"),
            ('TAB', "Tab", "Tab-separated values"),
            ('COMMA', "Comma", "Comma-separated values"),
            ('SEMICOLON', "Semicolon", "Semicolon-separated values"),
        ],
        default='WHITESPACE',
    )

    skip_lines: IntProperty(
        name="Skip Lines",
        description="Number of header or comment lines to skip at the start of the file",
        default=0,
        min=0,
    )

    column_x: IntProperty(
        name="X Column",
        description="Zero-based column index for X (or longitude/easting)",
        default=0,
        min=0,
    )
  
    column_y: IntProperty(
        name="Y Column",
        description="Zero-based column index for Y (or latitude/northing)",
        default=1,
        min=0,
    )

    column_z: IntProperty(
        name="Z Column",
        description="Zero-based column index for Z (or depth/elevation)",
        default=2,
        min=0,
    )

    center_mode: EnumProperty(
        name="Origin",
        description="How to place the imported data relative to the Blender origin",
        items=[
            (
                'GEOGRAPHIC',
                "Geographic",
                "Place origin at a fixed longitude/latitude so multiple imports align",
            ),
            (
                'CENTROID',
                "Centroid",
                "Place origin at the mean of all imported points",
            ),
            ('NONE', "None", "Use raw file coordinates without shifting"),
        ],
        default='GEOGRAPHIC',
    )

    center_longitude: FloatProperty(
        name="Origin Longitude",
        description="Longitude placed at Blender X=0 when using geographic origin",
        default=-66.0748348784534,
        precision=6,
    )

    center_latitude: FloatProperty(
        name="Origin Latitude",
        description="Latitude placed at Blender Y=0 when using geographic origin",
        default=45.2694864733817,
        precision=6,
    )

    invert_z: BoolProperty(
        name="Invert Z",
        description="Multiply Z by -1 (useful when depth values are negative and you want positive elevation)",
        default=False,
    )

    xy_scale: FloatProperty(
        name="XY Scale",
        description="Scale factor for X and Y (longitude/latitude columns)",
        default=1.0,
        min=0.000001,
        max=1000000.0,
    )

    z_scale: FloatProperty(
        name="Z Scale",
        description="Scale factor for Z (depth/elevation in meters)",
        default=1.0,
        min=0.000001,
        max=1000000.0,
    )

    max_points: IntProperty(
        name="Max Points",
        description="Maximum number of points to import (0 = import all points)",
        default=0,
        min=0,
    )

    object_type: EnumProperty(
        name="Object Type",
        description="How to represent the imported data in Blender",
        items=[
            ('POINT_CLOUD', "Point Cloud", "Create a native Blender point cloud object"),
            ('MESH_VERTICES', "Mesh Vertices", "Create a mesh with vertices only"),
        ],
        default='POINT_CLOUD',
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "delimiter")
        layout.prop(self, "skip_lines")

        box = layout.box()
        box.label(text="Columns (0-based)")
        row = box.row(align=True)
        row.prop(self, "column_x")
        row.prop(self, "column_y")
        row.prop(self, "column_z")

        layout.prop(self, "object_type")

        box = layout.box()
        box.label(text="Origin")
        box.prop(self, "center_mode")
        if self.center_mode == 'GEOGRAPHIC':
            row = box.row(align=True)
            row.prop(self, "center_longitude")
            row.prop(self, "center_latitude")

        layout.prop(self, "invert_z")

        box = layout.box()
        box.label(text="Scale (XY = degrees, Z = meters)")
        row = box.row(align=True)
        row.prop(self, "xy_scale")
        row.prop(self, "z_scale")

        layout.prop(self, "max_points")

    def invoke(self, context, event):
        scene = context.scene
        self.center_longitude = scene.xyz_importer_center_lon
        self.center_latitude = scene.xyz_importer_center_lat
        self.center_mode = scene.xyz_importer_center_mode
        return ImportHelper.invoke(self, context, event)

    def execute(self, context):
        filepath = self.filepath
        if not os.path.exists(filepath):
            self.report({'ERROR'}, f"File not found: {filepath}")
            return {'CANCELLED'}

        try:
            data = _parse_xyz_file(filepath, self.delimiter, self.skip_lines)
            coords = _select_columns(data, self.column_x, self.column_y, self.column_z)
            coords = _sanitize_coordinates(coords)

            total_points = len(coords)
            coords = _subsample_points(coords, self.max_points)

            coords, offset = _apply_center(
                coords,
                self.center_mode,
                self.center_longitude,
                self.center_latitude,
            )

            if self.invert_z:
                coords[:, 2] *= -1.0

            if self.xy_scale != 1.0:
                coords[:, 0] *= self.xy_scale
                coords[:, 1] *= self.xy_scale

            if self.z_scale != 1.0:
                coords[:, 2] *= self.z_scale

            base_name = os.path.splitext(os.path.basename(filepath))[0]
            if self.max_points > 0 and total_points > self.max_points:
                obj_name = f"{base_name}_{len(coords)}pts"
            else:
                obj_name = base_name

            if self.object_type == 'MESH_VERTICES':
                obj = _create_mesh_vertices_object(obj_name, coords)
            else:
                obj = _create_point_cloud_object(obj_name, coords)

            obj["xyz_importer_offset"] = tuple(float(v) for v in offset)
            obj["xyz_importer_center_mode"] = self.center_mode
            obj["xyz_importer_xy_scale"] = float(self.xy_scale)
            obj["xyz_importer_z_scale"] = float(self.z_scale)
            obj["xyz_importer_invert_z"] = self.invert_z
            obj["xyz_importer_source"] = filepath

            scene = context.scene
            scene.xyz_importer_center_lon = self.center_longitude
            scene.xyz_importer_center_lat = self.center_latitude
            scene.xyz_importer_center_mode = self.center_mode

            context.collection.objects.link(obj)
            context.view_layer.objects.active = obj
            obj.select_set(True)

            if len(coords) < total_points:
                self.report(
                    {'INFO'},
                    f"Imported {len(coords):,} of {total_points:,} points as '{obj_name}'",
                )
            else:
                self.report({'INFO'}, f"Imported {len(coords):,} points as '{obj_name}'")
            return {'FINISHED'}

        except Exception as exc:
            self.report({'ERROR'}, f"Error importing XYZ file: {exc}")
            import traceback
            traceback.print_exc()
            return {'CANCELLED'}


class ExportXYZ(Operator, ExportHelper):
    """Export mesh or point cloud vertices to a space-delimited XYZ file"""
    bl_idname = "export_scene.xyz"
    bl_label = "Export XYZ Point Cloud"
    bl_options = {'PRESET'}

    filename_ext = ".xyz"
    filter_glob: StringProperty(
        default="*.xyz",
        options={'HIDDEN'},
        maxlen=255,
    )

    delimiter: EnumProperty(
        name="Delimiter",
        description="Column delimiter used in the exported file",
        items=[
            ('WHITESPACE', "Whitespace", "One or more spaces"),
            ('TAB', "Tab", "Tab-separated values"),
            ('COMMA', "Comma", "Comma-separated values"),
            ('SEMICOLON', "Semicolon", "Semicolon-separated values"),
        ],
        default='WHITESPACE',
    )

    precision: IntProperty(
        name="Decimal Places",
        description="Number of decimal places written for each coordinate",
        default=6,
        min=1,
        max=12,
    )

    use_object_metadata: BoolProperty(
        name="Restore Import Coordinates",
        description=(
            "Reverse the import origin and scale stored on the object so exported "
            "values match the original lon/lat/depth file format"
        ),
        default=True,
    )

    apply_object_transform: BoolProperty(
        name="Apply Object Transform",
        description=(
            "Include object location, rotation, and scale before restoring file "
            "coordinates"
        ),
        default=False,
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "delimiter")
        layout.prop(self, "precision")
        layout.prop(self, "use_object_metadata")
        layout.prop(self, "apply_object_transform")

    def execute(self, context):
        obj = context.active_object
        if obj is None:
            self.report({'ERROR'}, "No active object selected")
            return {'CANCELLED'}

        if obj.type not in {'MESH', 'POINTCLOUD'}:
            self.report({'ERROR'}, "Active object must be a mesh or point cloud")
            return {'CANCELLED'}

        try:
            coords = _extract_local_coordinates(obj)

            if self.apply_object_transform:
                coords = _apply_object_transform(coords, obj)

            if self.use_object_metadata:
                metadata = _get_object_metadata(obj)
                coords = _reverse_import_transform(
                    coords,
                    metadata["offset"],
                    metadata["xy_scale"],
                    metadata["z_scale"],
                    metadata["invert_z"],
                )
                if not metadata["has_metadata"]:
                    self.report(
                        {'WARNING'},
                        "Object has no import metadata; exported local coordinates only",
                    )

            _write_xyz_file(self.filepath, coords, self.delimiter, self.precision)

            self.report({'INFO'}, f"Exported {len(coords):,} points to {self.filepath}")
            return {'FINISHED'}

        except Exception as exc:
            self.report({'ERROR'}, f"Error exporting XYZ file: {exc}")
            import traceback
            traceback.print_exc()
            return {'CANCELLED'}


def menu_func_import(self, context):
    self.layout.operator(ImportXYZ.bl_idname, text="XYZ Point Cloud (.xyz)")


def menu_func_export(self, context):
    self.layout.operator(ExportXYZ.bl_idname, text="XYZ Point Cloud (.xyz)")


def register():
    bpy.types.Scene.xyz_importer_center_lon = FloatProperty(
        name="XYZ Importer Origin Longitude",
        default=-66.0748348784534,
        precision=6,
    )
    bpy.types.Scene.xyz_importer_center_lat = FloatProperty(
        name="XYZ Importer Origin Latitude",
        default=45.2694864733817,
        precision=6,
    )
    bpy.types.Scene.xyz_importer_center_mode = EnumProperty(
        name="XYZ Importer Origin Mode",
        items=[
            ('GEOGRAPHIC', "Geographic", ""),
            ('CENTROID', "Centroid", ""),
            ('NONE', "None", ""),
        ],
        default='GEOGRAPHIC',
    )
    bpy.utils.register_class(ImportXYZ)
    bpy.utils.register_class(ExportXYZ)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)


def unregister():
    bpy.utils.unregister_class(ExportXYZ)
    bpy.utils.unregister_class(ImportXYZ)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)
    del bpy.types.Scene.xyz_importer_center_lon
    del bpy.types.Scene.xyz_importer_center_lat
    del bpy.types.Scene.xyz_importer_center_mode
