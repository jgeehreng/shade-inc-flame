#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Shade API Helpers — Uppercut VFX Pipeline
Merged Config, Drive Management, Uploading, and Comments
"""

import os
import json
import requests
import base64

# ---------------------------------------------------------------------
# Config locations
# ---------------------------------------------------------------------

API_BASE = "https://api.shade.inc"
FS_BASE = "https://fs.shade.inc"

GLOBAL_CONFIG_PATH = "/opt/Autodesk/shared/python/shade/config/shared_config.json"
USER_CONFIG_PATH = os.path.expanduser("~/flame/python/shade/user_config.json")
LEGACY_CONFIG_PATH = os.path.expanduser("~/flame/python/shade/config.json")

DEFAULT_CONFIG = {
    "shade_api_key": "",
    "shade_remote_url": "https://api.shade.inc",
    "shade_workspace_domain": "",
    "shade_base_url": "https://api.shade.inc",
    "jobs_folder": "/Volumes/vfx/UC_Jobs",
    "project_token": "nickname",
    "debug": False,
    "preset_path_h264": "/opt/Autodesk/presets/2026.2/export/presets/flame/movie_file/MP4/Baseline (1080p 12Mbits).xml",
    "preset_path_prores": "/opt/Autodesk/presets/2026.2/export/presets/flame/movie_file/Apple Final Cut Pro/Final Cut Pro (Apple ProRes 4444 XQ).xml",
}

# ---------------------------------------------------------------------
# Debug helpers
# ---------------------------------------------------------------------
def debug_print(cfg, msg):
    if cfg.get("debug"):
        print(f"[shade_api DEBUG] {msg}")

def log(msg):
    print(f"[shade_api] {msg}")

# ---------------------------------------------------------------------
# Load + Merge Configs
# ---------------------------------------------------------------------
def _load_json(path):
    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
    except Exception as e:
        print(f"[shade_api] ⚠️ Failed to load {path}: {e}")
    return {}

def validate_config():
    """Merge global, user, and legacy configs, ensuring Shade API key exists."""
    cfg = DEFAULT_CONFIG.copy()

    for path in [GLOBAL_CONFIG_PATH, USER_CONFIG_PATH, LEGACY_CONFIG_PATH]:
        if os.path.exists(path):
            cfg.update(_load_json(path))

    if "shade_remote_url" in cfg and not cfg.get("shade_base_url"):
        cfg["shade_base_url"] = cfg["shade_remote_url"]

    cfg["project_token"] = cfg.get("project_token", "nickname")
    cfg["debug"] = bool(cfg.get("debug", False))

    api_key = cfg.get("shade_api_key") or cfg.get("api_key")
    if not api_key:
        raise RuntimeError("Shade API key missing in config.")
    cfg["shade_api_key"] = api_key

    return cfg

# ---------------------------------------------------------------------
# Project Token Helper
# ---------------------------------------------------------------------

def get_project_token(cfg, flame_project):
    """Return the correct token value for the given Flame project."""
    mode = cfg.get("project_token") or "nickname"
    if mode == "name":
        return str(flame_project.name)
    return str(flame_project.nickname)

# ---------------------------------------------------------------------
# Drive Handling
# ---------------------------------------------------------------------

def get_or_create_drive(cfg, drive_name):
    """
    Find or create a Shade drive by name.
    Uses POST /workspaces/{workspace_id}/drives if not found.
    """
    base = cfg.get("shade_base_url", "https://api.shade.inc")
    api_key = cfg["shade_api_key"] if "shade_api_key" in cfg else cfg.get("api_key")
    workspace_id = cfg.get("workspace_id") or cfg.get("shade_workspace_id")

    if not workspace_id:
        raise RuntimeError("Missing workspace_id in config — cannot list drives.")

    headers = {"Authorization": api_key, "Content-Type": "application/json"}

    log(f"[get_or_create_drive] Checking for drive '{drive_name}' in workspace {workspace_id}")

    # 1️⃣ Get existing drives
    try:
        r = requests.get(f"{base}/workspaces/{workspace_id}/drives", headers=headers, timeout=10)
        r.raise_for_status()
    except Exception as e:
        raise RuntimeError(f"Failed to list drives: {e}")

    drives = r.json()
    for d in drives:
        name = d.get("name", "").strip().lower()
        ident = d.get("identifier", "").strip().lower()
        if drive_name.lower() in (name, ident):
            log(f"[get_or_create_drive] ✅ Found drive: {d['id']}")
            return d["id"]

    # 2️⃣ Drive not found → create it
    log(f"[get_or_create_drive] ❌ Drive '{drive_name}' not found. Creating new one...")

    payload = {
        "name": drive_name,
        "description": f"Auto-created by Flame for project {drive_name}",
        "type": "magic",
        "icon_type": "color",
        "public_template_key": "video_production",
        "default_storage_backend": {
            "provider": "r2",
            "bucket": "shade-prod-enam"
        },
    }

    try:
        create_url = f"{base}/workspaces/{workspace_id}/drives"
        rc = requests.post(create_url, headers=headers, json=payload, timeout=15)
        if rc.status_code not in (200, 201):
            raise RuntimeError(f"Drive creation failed: {rc.status_code} {rc.text}")
        new_drive = rc.json()
        log(f"[get_or_create_drive] ✅ Created new drive: {new_drive.get('id')}")
        return new_drive.get("id")
    except Exception as e:
        raise RuntimeError(f"Failed to create drive '{drive_name}': {e}")


# ---------------------------------------------------------------------
# Asset Search
# ---------------------------------------------------------------------

def search_shade_assets(api_key: str, drive_id: str, query: str, limit: int = 20, base_url="https://api.shade.inc"):
    """
    POST /search — Shade asset search (workspace-scoped)
    """
    payload = {"query": query, "drive_id": drive_id, "limit": limit}
    headers = {"Authorization": api_key, "Content-Type": "application/json"}

    log(f"[search_shade_assets] 🔍 Searching Shade for '{query}' in drive {drive_id}")
    r = requests.post(f"{base_url}/search", headers=headers, data=json.dumps(payload), timeout=15)
    log(f"[search_shade_assets] → {r.status_code}")

    if r.status_code != 200:
        log(f"[search_shade_assets] ⚠️ Shade search failed: {r.text[:200]}")
        return []

    try:
        data = r.json()
    except Exception:
        log(f"[search_shade_assets] ⚠️ Non-JSON response:\n{r.text[:300]}")
        return []

    if isinstance(data, list):
        return data
    return []

# ---------------------------------------------------------------------
# Fetch ShadeFS Token
# ---------------------------------------------------------------------

def fetch_shadefs_token(api_key: str, drive_id: str) -> str:
    """
    Request a temporary ShadeFS upload token.
    Uses the confirmed working endpoint:
    GET /workspaces/drives/{drive_id}/shade-fs-token
    """
    url = f"{API_BASE}/workspaces/drives/{drive_id}/shade-fs-token"
    log(f"[fetch_shadefs_token] Trying: {url}")

    headers = {"Authorization": api_key}
    r = requests.get(url, headers=headers, timeout=15)

    if r.status_code != 200:
        raise RuntimeError(f"Failed to fetch ShadeFS token: {r.status_code} {r.text}")

    # Accept raw JWT or JSON { "token": "..." }
    try:
        data = r.json()
        token = data.get("token")
    except Exception:
        token = r.text.strip()

    if not token or not token.startswith("ey"):
        raise RuntimeError(f"Invalid token response: {r.text[:200]}")

    log("[fetch_shadefs_token] ✅ ShadeFS token OK")
    return token

# ---------------------------------------------------------------------
# ShadeFS Upload Helpers (final verified routes)
# ---------------------------------------------------------------------

def _b64url_json(token: str) -> dict:
    """Decode the payload of a JWT without verifying its signature."""
    try:
        payload_b64 = token.split(".")[1]
        # pad base64 if needed
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
        return json.loads(decoded)
    except Exception as e:
        log(f"[b64url_json] ⚠️ Failed to decode token: {e}")
        return {}

# ---------------------------------------------------------------------
# ShadeFS Helpers (mkdir + multipart upload)
# ---------------------------------------------------------------------

def ensure_dir(token: str, drive_id: str, dest_path: str, email: str):
    """Ensure remote directory exists before upload."""
    directory = os.path.dirname(dest_path)
    log(f"[ensure_dir] 📁 Ensuring directory exists: {directory}")
    r = requests.post(
        f"{FS_BASE}/{drive_id}/fs/mkdir",
        headers={"Authorization": f"Bearer {token}"},
        params={"email": email, "path": directory, "drive": drive_id},
        json={}
    )
    if r.status_code not in (200, 201):
        raise RuntimeError(f"mkdir failed: {r.status_code} {r.text}")
    log("[ensure_dir] ✅ Directory ready")


def initiate_multipart(token: str, drive_id: str, dest_path: str, part_size: int = 8 * 1024 * 1024):
    """Initiate a multipart upload session."""
    log("[initiate_multipart] 🚦 Initiating multipart upload…")
    mime = "video/mp4" if dest_path.lower().endswith(".mp4") else "application/octet-stream"
    r = requests.post(
        f"{FS_BASE}/{drive_id}/upload/multipart",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "path": dest_path,
            "partSize": part_size,
            "mime": mime,
            "driveId": drive_id,
        }
    )
    r.raise_for_status()
    data = r.json()
    log(f"[initiate_multipart] ✅ Upload initiated: partSize={data['partSize']}")
    return data["partSize"], data["token"]


def presign_part(drive_id: str, finish_token: str, auth_token: str, part_number: int):
    """Request presigned upload URL for one part."""
    log(f"[presign_part] 🔑 Requesting presigned URL for part {part_number}…")
    r = requests.post(
        f"{FS_BASE}/{drive_id}/upload/multipart/part/{part_number}",
        headers={"Authorization": f"Bearer {auth_token}"},
        params={"token": finish_token},
    )
    r.raise_for_status()
    return r.json()


def upload_part(url: str, headers: dict, file_path: str, start: int, end: int):
    """Upload a file chunk to the presigned URL."""
    size = end - start
    with open(file_path, "rb") as f:
        f.seek(start)
        chunk = f.read(size)

    h = {"Content-Length": str(size)}
    if headers:
        h.update(headers)

    resp = requests.put(url, data=chunk, headers=h)
    if not resp.ok:
        raise RuntimeError(f"UploadPart failed: {resp.status_code} {resp.text[:200]}")

    etag = resp.headers.get("ETag") or resp.headers.get("etag")
    if not etag:
        raise RuntimeError("Missing ETag")
    return etag


def complete_multipart(drive_id: str, finish_token: str, auth_token: str, parts):
    """Finalize multipart upload on the ShadeFS server."""
    log("[complete_multipart] 🔄 Finalizing upload on server…")
    r = requests.post(
        f"{FS_BASE}/{drive_id}/upload/multipart/complete",
        headers={"Authorization": f"Bearer {auth_token}"},
        params={"token": finish_token},
        json={"parts": parts},
    )
    r.raise_for_status()
    log("[complete_multipart] 🎉 Upload Fully Complete!")

# ---------------------------------------------------------------------
# Upload (ShadeFS multipart)
# ---------------------------------------------------------------------

def upload_to_shade(local_path: str, project_token: str, progress_callback=None, auto_stack: bool = False, dest_path: str = None):
    """
    Upload a single file to the Shade drive named after the project_token.
    Uses ShadeFS multipart upload system (stable path).
    
    Args:
        local_path: Local filesystem path to the file to upload
        project_token: Project identifier (nickname or name) to determine drive
        progress_callback: Optional callback function(percent, message) for progress updates
        auto_stack: Whether to automatically stack versions (currently not implemented)
        dest_path: Optional destination path on Shade. If not provided, defaults to /CONFORMS/{filename}
    """
    log(f"[upload_to_shade] 🔄 Starting upload for project '{project_token}'")

    cfg = validate_config()
    api_key = cfg.get("shade_api_key") or cfg.get("api_key")
    drive_id = get_or_create_drive(cfg, project_token)

    # --------------------------------------------------------
    # Step 1: Request a temporary ShadeFS token for the drive
    # --------------------------------------------------------
    token = fetch_shadefs_token(api_key, drive_id)
    decoded = _b64url_json(token)
    email = decoded.get("sub")

    # --------------------------------------------------------
    # Step 2: Ensure the folder structure exists on Shade
    # --------------------------------------------------------
    if dest_path is None:
        dest_path = f"/CONFORMS/{os.path.basename(local_path)}"
    ensure_dir(token, drive_id, dest_path, email)

    # --------------------------------------------------------
    # Step 3: Initiate multipart upload
    # --------------------------------------------------------
    file_size = os.path.getsize(local_path)
    part_size, finish_token = initiate_multipart(token, drive_id, dest_path)
    total_parts = (file_size + part_size - 1) // part_size
    completed = []

    log(f"[upload_to_shade] Uploading {os.path.basename(local_path)} in {total_parts} parts…")
    bytes_uploaded = 0

    # --------------------------------------------------------
    # Step 4: Upload each part
    # --------------------------------------------------------
    for part_number in range(1, total_parts + 1):
        start = (part_number - 1) * part_size
        end = min(start + part_size, file_size)

        presigned = presign_part(drive_id, finish_token, token, part_number)
        etag = upload_part(presigned["url"], presigned.get("headers") or {}, local_path, start, end)
        completed.append({"PartNumber": part_number, "ETag": etag})

        bytes_uploaded = end
        percent = int((bytes_uploaded / file_size) * 100)
        if progress_callback:
            progress_callback(percent, f"{os.path.basename(local_path)} ({percent}%)")

        log(f"[upload_to_shade] ✅ Finished part {part_number}/{total_parts} ({end - start} bytes)")

    # --------------------------------------------------------
    # Step 5: Complete multipart upload
    # --------------------------------------------------------
    complete_multipart(drive_id, finish_token, token, completed)
    log(f"[upload_to_shade] ✅ Upload complete for {os.path.basename(local_path)}")


# -----------------------------------------------
# Utilities
# -----------------------------------------------

def seconds_to_tc(seconds, fps=24):
    """Convert seconds to timecode string (HH:MM:SS:FF)."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    frames = int(round((seconds % 1) * fps))
    return f"{hours:02}:{minutes:02}:{secs:02}:{frames:02}"


def _seconds_to_tc(seconds: float, fps: float) -> str:
    """Convert seconds → HH:MM:SS:FF for marker placement."""
    if seconds is None:
        return "00:00:00:00"
    total_frames = int(round(seconds * fps))
    f = total_frames % int(round(fps))
    total_seconds = total_frames // int(round(fps))
    h = total_seconds // 3600
    m = (total_seconds % 3600) // 60
    s = total_seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"


# -----------------------------------------------
# Comments
# -----------------------------------------------
def get_asset_comments(api_key, drive_id, asset_id, fps=None):
    """
    Fetch comments for an asset from Shade.
    Uses the verified working route:
      GET /assets/{asset_id}/comments?drive_id={drive_id}
    """

    BASE_URL = "https://api.shade.inc"
    asset_id_str = asset_id.get("id") if isinstance(asset_id, dict) else str(asset_id)
    url = f"{BASE_URL}/assets/{asset_id_str}/comments?drive_id={drive_id}"
    print(f"[shade_api] → Fetching comments for asset {asset_id_str} …")

    headers = {"Authorization": api_key, "Accept": "application/json"}
    r = requests.get(url, headers=headers, timeout=20)

    if r.status_code != 200:
        raise RuntimeError(f"get_asset_comments failed: {r.status_code} {r.text}")

    comments = r.json()
    if not comments:
        print("[shade_api] 🕳️ No comments found.")
        return []

    # Inner helper to convert seconds → timecode
    def secs_to_tc(sec, fps):
        if not fps or sec is None:
            return None
        total_frames = int(round(sec * fps))
        f = total_frames % int(round(fps))
        total_seconds = total_frames // int(round(fps))
        h = total_seconds // 3600
        m = (total_seconds % 3600) // 60
        s = total_seconds % 60
        return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"

    def normalize(c):
        # Safely extract author
        author_field = c.get("author", {})
        if isinstance(author_field, dict):
            author = author_field.get("name") or author_field.get("email") or "Unknown"
        else:
            author = author_field or "Unknown"

        content = (c.get("content") or "").strip()
        timestamp = c.get("timestamp", 0.0)
        duration = c.get("duration", 0.0)
        tc_start = secs_to_tc(timestamp, fps)
        tc_end = secs_to_tc(timestamp + duration, fps) if duration else None

        # Normalize replies recursively
        replies = [normalize(r) for r in c.get("replies", [])]

        return {
            "author": author,
            "content": content,
            "timestamp": timestamp,
            "duration": duration,
            "tc_start": tc_start,
            "tc_end": tc_end,
            "created": c.get("created"),
            "replies": replies,
        }

    normalized = [normalize(c) for c in comments]
    print(f"[shade_api] ✅ Retrieved {len(normalized)} comment(s)")
    return normalized
