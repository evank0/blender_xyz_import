"""
XYZ Point Cloud Importer for Blender 5
Import space-delimited bathymetry/survey .xyz files as point clouds
"""

bl_info = {
    "name": "XYZ Point Cloud Importer",
    "author": "Evan Kennedy",
    "version": (1, 1, 0),
    "blender": (5, 0, 0),
    "location": "File > Import/Export > XYZ Point Cloud (.xyz)",
    "description": "Import and export space-delimited XYZ bathymetry point clouds",
    "category": "Import-Export",
}

import bpy
from . import xyz_importer


def register():
    xyz_importer.register()


def unregister():
    xyz_importer.unregister()


if __name__ == "__main__":
    register()
