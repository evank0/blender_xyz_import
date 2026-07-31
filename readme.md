# XYZ Point Cloud Importer for Blender 5

Import space-delimited bathymetry and survey `.xyz` files as point clouds for visualization in Blender.

## Features

- Import whitespace-, tab-, comma-, or semicolon-delimited XYZ files
- Export mesh or point cloud vertices back to XYZ (edges and faces ignored)
- Round-trip support: import settings are stored on the object and reversed on export
- Configurable column mapping (X/Y/Z column indices)
- Native Blender point cloud objects (or mesh vertices)
- Fixed geographic origin for aligning multiple imports
- Optional subsampling for very large datasets
- Stores original coordinate offset on the imported object

## Requirements

- Blender 5.0 or later
- numpy (included with Blender)

## Installation

1. Copy the `xyz_importer` folder to your Blender add-ons directory:
   - **Windows**: `%APPDATA%\Blender Foundation\Blender\5.0\scripts\addons\`
   - **macOS**: `~/Library/Application Support/Blender/5.0/scripts/addons/`
   - **Linux**: `~/.config/blender/5.0/scripts/addons/`

2. Enable the add-on:
   - Open Blender
   - Go to `Edit > Preferences > Add-ons`
   - Search for "XYZ Point Cloud Importer"
   - Enable the checkbox

## Usage

1. In Blender, go to `File > Import > XYZ Point Cloud (.xyz)`
2. Select your `.xyz` file
3. Adjust options if needed:
   - **Origin → Geographic**: Fixed lon/lat placed at Blender `(0, 0)` — use the same origin when importing multiple files so they align
   - **Origin Longitude / Latitude**: Defaults to `-66.0748348784534`, `45.2694864733817`; remembered across imports in the same Blender session
   - **XY Scale / Z Scale**: Independent scaling for lon/lat (degrees) vs depth (meters)
   - **Max Points**: Limit import size for very large files (0 = all points)
   - **Invert Z**: Flip depth values if needed for visualization
4. The point cloud appears in the scene

### Exporting

1. Select the mesh or point cloud object to export
2. Go to `File > Export > XYZ Point Cloud (.xyz)`
3. Adjust options if needed:
   - **Restore Import Coordinates** (default on): reverses origin and scale so output is lon/lat/depth again
   - **Z Scale**: depth scale used on export (defaults to the import Z scale; set to `1.0` to write raw meters)
   - **Apply Object Transform**: include object move/rotate/scale before restoring coordinates
   - **Decimal Places**: precision for written values (default 6)
4. Only vertices/points are exported; edges and faces are ignored

## Round Trip

1. Import a `.xyz` file with your preferred origin and scale settings
2. Edit vertices in Blender (edit mode) or sculpt/transform the point set
3. Export with **Restore Import Coordinates** enabled
4. The exported file uses the same lon/lat/depth format as the original import

Import metadata stored on the object:

- `xyz_importer_offset`: origin removed during import
- `xyz_importer_xy_scale` / `xyz_importer_z_scale`: scale applied during import
- `xyz_importer_invert_z`: whether Z was inverted on import
- `xyz_importer_center_mode`: `GEOGRAPHIC`, `CENTROID`, or `NONE`

## File Format

Expected format is one point per line with at least three numeric columns:

```
-66.04424524 45.60210416 -8.306000
-66.04424524 45.60204131 -9.387000
-66.04415541 45.60204131 -8.884000
```

No header is expected by default. Use **Skip Lines** if your file has comment or header rows.

## Viewing Point Clouds

After import, switch the viewport shading to **Solid** or **Material Preview** and enable point display in the object properties if points are not visible at your scene scale.

## Object Metadata

Imported objects store custom properties for traceability and export:

- `xyz_importer_source`: original file path

To recover world coordinates manually: `world_xy = local_xy / xy_scale + offset_xy`, `world_z = local_z / z_scale + offset_z` (invert Z if needed)

## File Structure

```
xyz_importer/
├── __init__.py
├── xyz_importer.py
└── readme.md
```
