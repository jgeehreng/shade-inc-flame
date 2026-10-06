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
import re
import time

# ---------------------------------------------------------------------
# Config locations
# ---------------------------------------------------------------------

API_BASE = "https://api.shade.inc"
FS_BASE = "https://fs.shade.inc"
# ShadeFS JWTs last about five minutes. Refresh before they get inside this window.
TOKEN_MIN_VALID_SECONDS = 240
DEFAULT_PART_SIZE = 64 * 1024 * 1024

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
    "preset_path_h264": "/opt/Autodesk/shared/python/shade/presets/UC H264 10Mbits.xml",
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
        print(f"[shade_api] Failed to load {path}: {e}")
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

def _flame_value(value):
    """Unwrap a Flame attribute. str() on those objects includes angle brackets."""
    try:
        if hasattr(value, "get_value"):
            return value.get_value()
    except Exception:
        pass
    return value


def get_project_token(cfg, flame_project):
    """Return the correct token value for the given Flame project."""
    mode = cfg.get("project_token") or "nickname"
    raw = flame_project.name if mode == "name" else flame_project.nickname
    return str(_flame_value(raw))

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
            log(f"[get_or_create_drive] Found drive: {d['id']}")
            return d["id"]

    # 2️⃣ Drive not found -> create it
    log(f"[get_or_create_drive] Drive '{drive_name}' not found. Creating new one...")

    payload = {
        "name": drive_name,
        "description": f"Auto-created by Flame for project {drive_name}",
        "type": "magic",
        "icon_type": "color",
        "public_template_key": "video_production",
    }

    try:
        create_url = f"{base}/workspaces/{workspace_id}/drives"
        rc = requests.post(create_url, headers=headers, json=payload, timeout=15)
        if rc.status_code not in (200, 201):
            raise RuntimeError(f"Drive creation failed: {rc.status_code} {rc.text}")
        new_drive = rc.json()
        log(f"[get_or_create_drive] Created new drive: {new_drive.get('id')}")
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

    log(f"[search_shade_assets] Searching Shade for '{query}' in drive {drive_id}")
    r = requests.post(f"{base_url}/search", headers=headers, data=json.dumps(payload), timeout=15)
    log(f"[search_shade_assets] -> {r.status_code}")

    if r.status_code != 200:
        log(f"[search_shade_assets] Shade search failed: {r.text[:200]}")
        return []

    try:
        data = r.json()
    except Exception:
        log(f"[search_shade_assets] Non-JSON response:\n{r.text[:300]}")
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

    log("[fetch_shadefs_token] ShadeFS token OK")
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
        log(f"[b64url_json] Failed to decode token: {e}")
        return {}


def _token_seconds_remaining(token: str) -> float:
    """Seconds until a ShadeFS JWT expires. Missing exp is treated as expired."""
    exp = _b64url_json(token).get("exp")
    if not exp:
        return 0
    return float(exp) - time.time()


class ShadeFSSession:
    """ShadeFS auth that refreshes the JWT before it expires."""

    def __init__(self, api_key: str, drive_id: str):
        self.api_key = api_key
        self.drive_id = drive_id
        self._token = None

    def token(self) -> str:
        if (
            not self._token
            or _token_seconds_remaining(self._token) < TOKEN_MIN_VALID_SECONDS
        ):
            self._token = fetch_shadefs_token(self.api_key, self.drive_id)
        return self._token

    def email(self) -> str:
        return _b64url_json(self.token()).get("sub")

# ---------------------------------------------------------------------
# ShadeFS Helpers (mkdir + multipart upload)
# ---------------------------------------------------------------------

def ensure_dir(session: ShadeFSSession, drive_id: str, dest_path: str, email: str):
    """Ensure remote directory exists before upload."""
    directory = os.path.dirname(dest_path)
    log(f"[ensure_dir] Ensuring directory exists: {directory}")
    r = requests.post(
        f"{FS_BASE}/{drive_id}/fs/mkdir",
        headers={"Authorization": f"Bearer {session.token()}"},
        params={"email": email, "path": directory, "drive": drive_id},
        json={}
    )
    if r.status_code not in (200, 201):
        raise RuntimeError(f"mkdir failed: {r.status_code} {r.text}")
    log("[ensure_dir] Directory ready")


def _http_error(response, action):
    """Include the response body. ShadeFS 422s otherwise surface as "unknown"."""
    body = (response.text or "").strip().replace("\n", " ")
    if len(body) > 800:
        body = body[:800] + "..."
    return RuntimeError(f"{action} failed: {response.status_code} {response.reason}: {body}")


def initiate_multipart(session: ShadeFSSession, drive_id: str, dest_path: str, part_size: int = DEFAULT_PART_SIZE):
    """Initiate a multipart upload session."""
    log("[initiate_multipart] Initiating multipart upload.")
    r = requests.post(
        f"{FS_BASE}/{drive_id}/upload/multipart",
        headers={"Authorization": f"Bearer {session.token()}"},
        json={
            "path": dest_path,
            "partSize": part_size,
        }
    )
    if not r.ok:
        raise _http_error(r, "initiate_multipart")
    data = r.json()
    log(f"[initiate_multipart] Upload initiated: partSize={data['partSize']}")
    return data["partSize"], data["token"]


def presign_part(drive_id: str, finish_token: str, session: ShadeFSSession, part_number: int):
    """Request presigned upload URL for one part."""
    log(f"[presign_part] Requesting presigned URL for part {part_number}.")
    r = requests.post(
        f"{FS_BASE}/{drive_id}/upload/multipart/part/{part_number}",
        headers={"Authorization": f"Bearer {session.token()}"},
        params={"token": finish_token},
    )
    if not r.ok:
        raise _http_error(r, "presign_part")
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


def complete_multipart(drive_id: str, finish_token: str, session: ShadeFSSession, parts):
    """Finalize multipart upload on the ShadeFS server."""
    log("[complete_multipart] Finalizing upload on server.")
    r = requests.post(
        f"{FS_BASE}/{drive_id}/upload/multipart/complete",
        headers={"Authorization": f"Bearer {session.token()}"},
        params={"token": finish_token},
        json={"parts": parts},
    )
    if not r.ok:
        raise _http_error(r, "complete_multipart")
    log("[complete_multipart] Upload fully complete.")

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
        auto_stack: Stack the new asset onto the previous version when that version exists
        dest_path: Optional destination path on Shade. If not provided, defaults to /CONFORMS/{filename}
    """
    log(f"[upload_to_shade] Starting upload for project '{project_token}'")

    cfg = validate_config()
    api_key = cfg.get("shade_api_key") or cfg.get("api_key")
    drive_id = get_or_create_drive(cfg, project_token)

    # --------------------------------------------------------
    # Step 1: Request a temporary ShadeFS token for the drive
    # --------------------------------------------------------
    session = ShadeFSSession(api_key, drive_id)
    email = session.email()

    # --------------------------------------------------------
    # Step 2: Ensure the folder structure exists on Shade
    # --------------------------------------------------------
    if dest_path is None:
        dest_path = f"/CONFORMS/{os.path.basename(local_path)}"
    ensure_dir(session, drive_id, dest_path, email)

    # --------------------------------------------------------
    # Step 3: Initiate multipart upload
    # --------------------------------------------------------
    file_size = os.path.getsize(local_path)
    part_size, finish_token = initiate_multipart(session, drive_id, dest_path)
    total_parts = (file_size + part_size - 1) // part_size
    completed = []

    log(f"[upload_to_shade] Uploading {os.path.basename(local_path)} in {total_parts} parts.")
    bytes_uploaded = 0

    # --------------------------------------------------------
    # Step 4: Upload each part
    # --------------------------------------------------------
    for part_number in range(1, total_parts + 1):
        start = (part_number - 1) * part_size
        end = min(start + part_size, file_size)

        presigned = presign_part(drive_id, finish_token, session, part_number)
        etag = upload_part(presigned["url"], presigned.get("headers") or {}, local_path, start, end)
        completed.append({"PartNumber": part_number, "ETag": etag})

        bytes_uploaded = end
        percent = int((bytes_uploaded / file_size) * 100)
        if progress_callback:
            progress_callback(percent, f"{os.path.basename(local_path)} ({percent}%)")

        log(f"[upload_to_shade] Finished part {part_number}/{total_parts} ({end - start} bytes)")

    # --------------------------------------------------------
    # Step 5: Complete multipart upload
    # --------------------------------------------------------
    complete_multipart(drive_id, finish_token, session, completed)
    log(f"[upload_to_shade] Upload complete for {os.path.basename(local_path)}")

    # --------------------------------------------------------
    # Optional: auto stack new asset onto previous version
    # --------------------------------------------------------
    if auto_stack:
        try:
            _maybe_auto_stack_asset(
                api_key=api_key,
                drive_id=drive_id,
                dest_path=dest_path,
                filename=os.path.basename(local_path),
            )
        except Exception as stack_err:
            log(f"[upload_to_shade] Auto-stack skipped: {stack_err}")


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
    """Convert seconds -> HH:MM:SS:FF for marker placement."""
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
    print(f"[shade_api] -> Fetching comments for asset {asset_id_str} .")

    headers = {"Authorization": api_key, "Accept": "application/json"}
    r = requests.get(url, headers=headers, timeout=20)

    if r.status_code != 200:
        raise RuntimeError(f"get_asset_comments failed: {r.status_code} {r.text}")

    comments = r.json()
    if not comments:
        print("[shade_api] No comments found.")
        return []

    # Inner helper to convert seconds -> timecode
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
    print(f"[shade_api] Retrieved {len(normalized)} comment(s)")
    return normalized


# -----------------------------------------------
# Version stacking helpers
# -----------------------------------------------

def next_version_name(api_key: str, drive_id: str, clip_name: str):
    """
    Return the next versioned name when Shade already has this version or a higher one.

    Names without a trailing version tag, and names newer than anything in Shade,
    return None so the caller keeps the current name.
    Example: clip shot_v01 becomes shot_v02 when Shade's highest match is v01,
    or shot_v04 when Shade already has v03.
    """
    match = re.search(r"([vV])(\d+)$", clip_name)
    if not match:
        return None

    prefix = match.group(1)
    current_version = int(match.group(2))
    base_no_version = clip_name[:match.start()]
    results = search_shade_assets(api_key, drive_id, base_no_version or clip_name, limit=50)
    pattern = re.compile(rf"^{re.escape(base_no_version)}[vV](\d+)$")

    max_found = None
    for result in results:
        shade_name = result.get("name", "")
        no_ext = os.path.splitext(shade_name)[0]
        version_match = pattern.match(no_ext)
        if not version_match:
            continue
        try:
            version_num = int(version_match.group(1))
        except Exception:
            continue
        if max_found is None or version_num > max_found:
            max_found = version_num

    if max_found is None or max_found < current_version:
        return None
    return f"{base_no_version}{prefix}{max_found + 1:02d}"


def _prev_version_name(filename_no_ext: str) -> str or None:
    """
    Given a filename without extension that ends with vNN, return the previous version name.
    Example: 'shot_v03' -> 'shot_v02'
    """
    m = re.search(r"^(?P<base>.+?)(?P<prefix>[vV])(?P<num>\d+)$", filename_no_ext)
    if not m:
        return None
    num = int(m.group("num"))
    if num <= 0:
        return None
    return f"{m.group('base')}{m.group('prefix')}{num - 1:02d}"


def _find_asset_by_name(api_key: str, drive_id: str, name: str):
    """
    Search for an asset by its name (case-insensitive), returning the first match.
    """
    results = search_shade_assets(api_key, drive_id, name, limit=10)
    for r in results:
        shade_name = r.get("name", "")
        if shade_name.lower() == name.lower():
            return r
        no_ext = os.path.splitext(shade_name)[0]
        if no_ext.lower() == name.lower():
            return r
    return None


def _get_asset_by_path(api_key: str, drive_id: str, path: str):
    """
    GET /assets/path?path={path}&drive_id={drive_id}
    """
    url = f"{API_BASE}/assets/path"
    headers = {"Authorization": api_key, "Accept": "application/json"}

    def try_path(p):
        params = {"path": p, "drive_id": drive_id}
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        return resp

    # Try as-is
    r = try_path(path)
    if r.status_code == 200:
        return r.json()

    # Try with drive prefix if missing
    if not str(path).startswith(f"/{drive_id}"):
        prefixed = f"/{drive_id}{path}"
        r2 = try_path(prefixed)
        if r2.status_code == 200:
            return r2.json()
        r = r2

    raise RuntimeError(f"get_asset_by_path failed: {r.status_code} {r.text}")


def _stack_asset(api_key: str, drive_id: str, asset_id: str, target_asset_id: str):
    """
    POST /assets/{asset_id}/stack?target_asset_id=...&drive_id=...
    """
    url = f"{API_BASE}/assets/{asset_id}/stack"
    headers = {"Authorization": api_key, "Content-Type": "application/json"}
    params = {"target_asset_id": target_asset_id, "drive_id": drive_id}
    r = requests.post(url, headers=headers, params=params, json={})
    if r.status_code in (200, 201):
        return r.json() if r.text else None

    # If target is not part of a stack yet, create one containing both assets
    if r.status_code == 404 and "Target asset is not part of a stack" in r.text:
        return _create_stack(api_key, drive_id, [target_asset_id, asset_id])

    raise RuntimeError(f"Stack request failed: {r.status_code} {r.text}")


def _create_stack(api_key: str, drive_id: str, asset_ids):
    """
    POST /assets/stack — create a new stack with the provided asset ids
    """
    url = f"{API_BASE}/assets/stack"
    headers = {"Authorization": api_key, "Content-Type": "application/json"}
    payload = {"asset_ids": asset_ids, "drive_id": drive_id}
    r = requests.post(url, headers=headers, json=payload)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Create stack failed: {r.status_code} {r.text}")
    return r.json() if r.text else None


def _maybe_auto_stack_asset(api_key: str, drive_id: str, dest_path: str, filename: str):
    """
    Attempt to stack the newly uploaded asset onto the previous version (vNN-1) if it exists.
    """
    base_no_ext = os.path.splitext(filename)[0]
    m_base = re.match(r"(.+?)[vV]\d+$", base_no_ext)
    base_root = m_base.group(1) if m_base else base_no_ext
    prev_name = _prev_version_name(base_no_ext)
    if not prev_name:
        log("[auto_stack] No version pattern found; skipping stacking.")
        return

    # Find previous asset to target
    prev_asset = _find_asset_by_name(api_key, drive_id, prev_name)
    if not prev_asset:
        log(f"[auto_stack] No previous asset found for '{prev_name}'; skipping.")
        return
    target_asset_id = prev_asset.get("id")
    if not target_asset_id:
        log("[auto_stack] Previous asset missing id; skipping.")
        return

    # Find newly uploaded asset (prefer direct path lookup, then fallback search with retries)
    new_asset = None
    errors = []

    for attempt in range(10):
        try:
            if dest_path:
                try:
                    new_asset = _get_asset_by_path(api_key, drive_id, dest_path)
                except Exception as e:
                    errors.append(f"path lookup attempt {attempt+1}: {e}")
            if not new_asset:
                new_asset = _find_asset_by_name(api_key, drive_id, base_no_ext)
            if not new_asset:
                new_asset = _find_asset_by_name(api_key, drive_id, filename)
            if not new_asset:
                if base_root and base_root != base_no_ext:
                    new_asset = _find_asset_by_name(api_key, drive_id, base_root)
        except Exception as e:
            errors.append(str(e))

        if new_asset:
            break
        time.sleep(1)  # give the indexer a moment

    if not new_asset:
        raise RuntimeError(f"Uploaded asset not found via search/path; cannot stack. Details: {errors}")

    new_asset_id = new_asset.get("id")
    if not new_asset_id:
        raise RuntimeError("Uploaded asset missing id; cannot stack.")

    log(f"[auto_stack] Stacking asset {new_asset_id} onto {target_asset_id}")
    _stack_asset(api_key, drive_id, new_asset_id, target_asset_id)
    log("[auto_stack] Stacked successfully.")


# ---------------------------------------------------------------------
# Paths, approval status, and published share links
# ---------------------------------------------------------------------

APPROVAL_STATUS_NAME = "Approval Status"
PUBLISH_BASE = "https://app.shade.inc/publish"
# Commenting preset: view, download, and comment, including stack versions.
REVIEW_SHARE_ACTIONS = [
    "read",
    "comment",
    "download",
    "read_asset_details",
    "read_metadata",
    "view_stack_versions",
]

_APPROVAL_FIELD_CACHE = {}


def drive_path(drive_id: str, path: str) -> str:
    """Shade file routes require /{drive_id}/... paths."""
    path = path if str(path).startswith("/") else f"/{path}"
    prefix = f"/{drive_id}"
    if path == prefix or path.startswith(prefix + "/"):
        return path
    return f"{prefix}{path}"


def logical_path(drive_id: str, path: str) -> str:
    """ShadeFS and published links use paths without the drive id prefix."""
    path = path if str(path).startswith("/") else f"/{path}"
    prefix = f"/{drive_id}"
    if path == prefix:
        return "/"
    if path.startswith(prefix + "/"):
        return path[len(prefix):] or "/"
    return path


def _auth_headers(api_key: str) -> dict:
    return {
        "Authorization": api_key,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def get_metadata_attributes(api_key: str, drive_id: str):
    r = requests.get(
        f"{API_BASE}/workspaces/drives/{drive_id}/metadata",
        headers=_auth_headers(api_key),
        timeout=20,
    )
    if not r.ok:
        raise _http_error(r, "get_metadata_attributes")
    data = r.json()
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("metadata", "attributes", "data"):
            if isinstance(data.get(key), list):
                return data[key]
    return []


def get_approval_status_field(api_key: str, drive_id: str) -> dict:
    """Return the drive's Approval Status select field and its option ids."""
    cached = _APPROVAL_FIELD_CACHE.get(drive_id)
    if cached:
        return cached

    field = next(
        (attr for attr in get_metadata_attributes(api_key, drive_id) if attr.get("name") == APPROVAL_STATUS_NAME),
        None,
    )
    if not field:
        raise RuntimeError(
            f"No '{APPROVAL_STATUS_NAME}' metadata field on this Shade drive."
        )

    names_by_id = {}
    ids_by_name = {}
    for option in field.get("options") or []:
        option_id = option.get("id")
        option_name = option.get("name")
        if option_id and option_name:
            names_by_id[option_id] = option_name
            ids_by_name[option_name] = option_id

    parsed = {
        "id": field["id"],
        "names_by_id": names_by_id,
        "ids_by_name": ids_by_name,
    }
    _APPROVAL_FIELD_CACHE[drive_id] = parsed
    return parsed


def get_asset_record(api_key: str, drive_id: str, asset_id: str) -> dict:
    r = requests.get(
        f"{API_BASE}/assets/{asset_id}",
        headers=_auth_headers(api_key),
        params={"drive_id": drive_id},
        timeout=20,
    )
    if not r.ok:
        raise _http_error(r, "get_asset")
    return r.json()


def find_asset_for_clip(api_key: str, drive_id: str, clip_name: str):
    """Exact name match, hydrating path from the asset record when search omits it."""
    asset = _find_asset_by_name(api_key, drive_id, clip_name)
    if not asset or not asset.get("id"):
        return None
    if not asset.get("path"):
        try:
            full = get_asset_record(api_key, drive_id, asset["id"])
            if full:
                asset = full
        except Exception as e:
            log(f"[find_asset_for_clip] Asset record lookup failed for '{clip_name}': {e}")
    return asset


def get_approval_status(api_key: str, drive_id: str, asset_id: str):
    """Return the Approval Status option name, or None when unset."""
    field = get_approval_status_field(api_key, drive_id)
    asset = get_asset_record(api_key, drive_id, asset_id)
    option_id = (asset.get("custom_metadata") or {}).get(field["id"])
    if not option_id:
        return None
    return field["names_by_id"].get(option_id)


def set_approval_status(api_key: str, drive_id: str, asset_id: str, option_name):
    """Set Approval Status to an option name. None clears it."""
    field = get_approval_status_field(api_key, drive_id)
    if option_name is None:
        value = None
    else:
        value = field["ids_by_name"].get(option_name)
        if not value:
            known = ", ".join(sorted(field["ids_by_name"]))
            raise RuntimeError(f"Unknown Approval Status '{option_name}'. Options: {known}")

    r = requests.put(
        f"{API_BASE}/assets/metadata/values",
        headers=_auth_headers(api_key),
        json={
            "drive_id": drive_id,
            "asset_ids": [asset_id],
            "metadata_attributes": [{"id": field["id"], "value": value}],
        },
        timeout=20,
    )
    if not r.ok:
        raise _http_error(r, "set_approval_status")
    log(f"[set_approval_status] {asset_id} -> {option_name or 'cleared'}")
    return r.json()


def copy_shade_file(api_key: str, drive_id: str, source: str, destination: str):
    """Server-side copy. Paths may be logical or drive-prefixed."""
    r = requests.post(
        f"{API_BASE}/files/copy",
        headers=_auth_headers(api_key),
        json={
            "drive_id": drive_id,
            "source": drive_path(drive_id, source),
            "destination": drive_path(drive_id, destination),
        },
        timeout=60,
    )
    if not r.ok:
        raise _http_error(r, "copy_shade_file")
    log(f"[copy_shade_file] {logical_path(drive_id, source)} -> {logical_path(drive_id, destination)}")
    return r.json() if r.text and r.text != "null" else None


def create_public_share(
    api_key: str,
    drive_id: str,
    path: str,
    name: str,
    password: str = None,
    allowed_actions=None,
):
    """Create a published link for one file or folder and attach its public URL."""
    body = {
        "path": logical_path(drive_id, path),
        "is_public_enabled": True,
        "allowed_actions": list(allowed_actions or REVIEW_SHARE_ACTIONS),
        "name": name,
    }
    if password:
        body["password"] = password

    r = requests.post(
        f"{API_BASE}/workspaces/drives/{drive_id}/public-file-shares",
        headers=_auth_headers(api_key),
        json=body,
        timeout=30,
    )
    if not r.ok:
        raise _http_error(r, "create_public_share")
    share = r.json()
    share_id = share.get("id")
    if share_id:
        share["url"] = f"{PUBLISH_BASE}/{share_id}"
    log(f"[create_public_share] {share.get('name')}: {share.get('url')}")
    return share
