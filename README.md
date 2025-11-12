# Shade Integration for Autodesk Flame

A comprehensive integration suite for connecting Autodesk Flame with Shade, enabling seamless uploads, comment synchronization, and project management within the Uppercut VFX Pipeline.

## Overview

This package provides several Python scripts that integrate Shade's review and collaboration platform with Autodesk Flame. The integration supports:

- **Config Management**: Unified global and user configuration editor
- **Conform Uploads**: Automated upload of conform sequences to Shade
- **MediaHub Uploads**: Direct upload of files/folders from Flame's MediaHub
- **Comment Synchronization**: Fetch comments from Shade and create Flame markers
- **Automatic Versioning**: The API for this doesn't work yet as it's a new feature for them.

## Requirements

- **Autodesk Flame 2025 or later**
- **Python 3** (bundled with Flame)
- **Shade API Key** (get one at [Shade Academy](https://academy.shade.inc/developers#authenticating-with-the-python-sdk))
- **Required Python packages** (automatically installed via `shade_packages.py`):
  - `requests`
  - `PyJWT`
  - `shade-python-sdk` (optional, if using Shade SDK features)

## Installation

1. **Copy the files** to your Flame Python scripts directory:
   ```
   /opt/Autodesk/shared/python/shade/
   ```
   Or for user-specific installation:
   ```
   ~/flame/python/shade/
   ```

2. **Ensure the directory structure** matches:
   ```
   shade/
   ├── lib/
   │   ├── shade_api.py
   │   └── shade_packages.py
   ├── config/
   │   └── shared_config.json
   ├── shade_config_editor.py
   ├── shade_conform_uploader.py
   ├── shade_get_comments.py
   └── shade_mediahub_uploader.py
   ```

3. **First-time setup**: Launch Flame and use the config editor to set up your Shade API key and workspace.

## User Configuration
<img width="642" height="516" alt="user_settings" src="https://github.com/user-attachments/assets/359a3829-2ece-4547-8913-6db335c4f50d" />

### Global Configuration
<img width="648" height="517" alt="global_settings" src="https://github.com/user-attachments/assets/58c25bd8-e3f1-4fca-b388-02b9aebca1c7" />

Global settings are stored at:
```
/opt/Autodesk/shared/python/shade/config/shared_config.json
```

**Global Settings:**
- `jobs_folder`: Base path for exported files (default: `/Volumes/vfx/UC_Jobs`)
- `preset_path_h264`: Path to H.264 export preset XML
- `preset_path_prores`: Path to ProRes export preset XML
- `shade_base_url`: Shade API base URL (default: `https://api.shade.inc`)
- `project_token`: Which project identifier to use - `"nickname"` or `"name"` (default: `"nickname"`)
- `debug`: Enable verbose debug logging (default: `false`)

### User Configuration

User-specific settings are stored at:
```
~/flame/python/shade/user_config.json
```

**User Settings:**
- `shade_api_key`: Your Shade API key (required)
- `shade_workspace_id`: Your Shade workspace ID (required)

### Config Editor

Access the configuration editor from Flame's main menu:
```
Main Menu → Shade → Edit Config
```

The editor provides:
- **Global Settings Tab**: Configure shared pipeline settings
- **User Settings Tab**: Configure your personal API key and workspace
- **API Key Validation**: Test your API key and auto-populate available workspaces
- **Documentation Links**: Quick access to Shade API documentation

## Scripts

### 1. Shade Config Editor (`shade_config_editor.py`)

**Location**: Main Menu → Shade → Edit Config

A GUI tool for managing both global and user-specific Shade configuration. Features:
- Separate tabs for global and user settings
- API key validation with workspace auto-discovery
- Real-time configuration updates
- Support for both project nickname and name token modes

### 2. Shade Conform Uploader (`shade_conform_uploader.py`)

**Location**: Media Panel → Shade → Upload Conform to Shade

Uploads selected sequences to Shade with automatic versioning:
- Exports sequences to H.264 format
- Automatically increments version numbers (e.g., `v01` → `v02`) if asset exists in Shade
- Creates organized folder structure: `FROM_FLAME/YYYY-MM-DD/HHMM/`
- Uploads to Shade drive named after project token
- Progress tracking with detailed status updates

**Usage:**
1. Select one or more sequences in the Media Panel
2. Right-click → Shade → Upload Conform to Shade
3. Confirm the upload
4. Wait for export and upload to complete

**Features:**
- Automatic version increment before export
- Creates shared library `FROM_FLAME` if it doesn't exist
- Uses global H.264 preset for export
- Supports auto-stacking (when enabled)

### 3. Shade MediaHub Uploader (`shade_mediahub_uploader.py`)

**Location**: MediaHub → Shade → Upload to Shade

Uploads files and folders directly from MediaHub to Shade:
- Supports both individual files and entire folders
- Preserves relative folder structure in Shade
- Uploads to `/CONFORMS/` path in Shade drive
- Progress tracking per file

**Usage:**
1. Select files or folders in MediaHub
2. Right-click → Shade → Upload to Shade
3. Confirm the upload
4. Files upload with preserved directory structure

**Features:**
- Recursive folder upload
- Relative path preservation
- Automatic drive detection/creation
- Batch upload support

### 4. Shade Get Comments (`shade_get_comments.py`)

**Location**: 
- Timeline → Shade → Get Comments (for segments)
- Media Panel → Shade → Get Comments (for sequences)

Fetches comments from Shade and creates Flame markers:
- Searches Shade for assets matching sequence/segment names
- Downloads all comments with timestamps
- Creates Flame markers at comment timecodes
- Includes comment author, content, and replies
- Colors sequences/segments with "Address Comments" label

**Usage:**
1. Select sequences or segments in Timeline or Media Panel
2. Right-click → Shade → Get Comments
3. Markers are automatically created at comment positions
4. Items with comments are colored for easy identification

**Features:**
- Timecode conversion (handles frame rate differences)
- Segment-aware marker placement (respects segment boundaries)
- Comment replies included in marker text
- Duration support (if comment has duration)
- Caching to avoid duplicate API calls

## API Library (`lib/shade_api.py`)

Core library providing shared functionality:

### Key Functions

- **`validate_config()`**: Loads and merges global/user/legacy configs
- **`get_or_create_drive(cfg, drive_name)`**: Finds or creates a Shade drive
- **`upload_to_shade(local_path, project_token, ...)`**: Uploads files using ShadeFS multipart upload
- **`search_shade_assets(api_key, drive_id, query, ...)`**: Searches for assets in Shade
- **`get_asset_comments(api_key, drive_id, asset_id, ...)`**: Fetches comments for an asset

### Configuration Merging

The library merges configuration in this order (later values override earlier):
1. Default configuration
2. Global config (`/opt/Autodesk/shared/python/shade/config/shared_config.json`)
3. User config (`~/flame/python/shade/user_config.json`)
4. Legacy config (`~/flame/python/shade/config.json`) - for backward compatibility

## Package Management (`lib/shade_packages.py`)

Automatically installs required Python packages on first launch. Handles:
- Detection of missing packages
- Installation to Flame's versioned Python environment
- Sudo password prompt for system-wide installation
- Support for Flame version detection

## Project Token Modes

The integration supports two modes for identifying projects in Shade:

- **`nickname`** (default): Uses the project's nickname as the drive identifier
- **`name`**: Uses the project's full name as the drive identifier

Configure this in the global config editor or `shared_config.json`:
```json
{
  "project_token": "nickname"  // or "name"
}
```

## Troubleshooting

### API Key Issues

- **Error**: "Shade API key missing in config"
  - **Solution**: Use the config editor to set your API key in the User Settings tab

- **Error**: "Invalid API key"
  - **Solution**: Verify your API key at [Shade Academy](https://academy.shade.inc/developers#authenticating-with-the-python-sdk)

### Upload Issues

- **Error**: "Could not find or create Shade drive"
  - **Solution**: Verify your workspace ID is correct and you have permission to create drives

- **Error**: "Failed to fetch ShadeFS token"
  - **Solution**: Check your API key permissions and network connectivity

### Comment Issues

- **No markers created**: Check that:
  - Asset names in Shade match sequence/segment names exactly
  - Comments exist in Shade for the selected items
  - Frame rates match between Flame and Shade

### Debug Mode

Enable debug logging by setting in global config:
```json
{
  "debug": true
}
```

This will output detailed logging to help diagnose issues.

## File Structure

```
shade/
├── lib/
│   ├── shade_api.py          # Core API library
│   └── shade_packages.py     # Package installer
├── config/
│   └── shared_config.json    # Global configuration
├── shade_config_editor.py    # Configuration GUI
├── shade_conform_uploader.py # Sequence upload tool
├── shade_get_comments.py     # Comment synchronization
└── shade_mediahub_uploader.py # MediaHub upload tool
```

## Version History

- **v1.5.1** - Conform Uploader: Auto-version-up, improved export workflow
- **v1.3.0** - MediaHub Uploader: Folder support, path preservation
- **v1.1.1** - Get Comments: Segment support, caching, duration handling

## Support

For issues, questions, or contributions:
- Check the [Shade API Documentation](https://academy.shade.inc/developers)
- Review debug logs with `debug: true`
- Contact the Uppercut VFX Pipeline team

## License

This integration is part of the Uppercut VFX Pipeline and is intended for internal use.

