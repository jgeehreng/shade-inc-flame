#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Shade Get Comments — Uppercut VFX Pipeline
Fetches comments from Shade for the selected sequence or segment and adds Flame markers.
"""

import flame
import os
import re
import traceback
from PySide6 import QtWidgets
from lib.shade_api import (
    validate_config,
    get_or_create_drive,
    search_shade_assets,
    get_asset_comments,
)

FOLDER_NAME = "UC Shade"
SCRIPT_NAME = "Get Comments"
VERSION = "v1.1.2"


# ----------------------------------------------------------
# Helpers
# ----------------------------------------------------------

def log(msg):
    print(f"[{SCRIPT_NAME}] {msg}")


def show_message(text, title=SCRIPT_NAME):
    """Cross-version safe popup for Flame."""
    try:
        if hasattr(flame, "message_dialog"):
            flame.message_dialog(title, text)
        else:
            QtWidgets.QMessageBox.information(None, title, text)
    except Exception:
        print(f"[{SCRIPT_NAME}] {text}")


def _extract_fps(rate):
    """Sanitize frame rate string like '23.98 fps' -> 23.98."""
    if isinstance(rate, (float, int)):
        return float(rate)
    regex = r"\s[a-zA-Z]*"
    test_str = str(rate)
    subst = ""
    fixed_framerate = float(re.sub(regex, subst, test_str, 0))
    return round(fixed_framerate, 2)


def timecode_to_frames(tc, fps):
    """Convert HH:MM:SS:FF to frame number."""
    try:
        h, m, s, f = [int(x) for x in tc.split(":")]
        return int(round(((h * 3600) + (m * 60) + s) * fps + f))
    except Exception:
        return 0


def seconds_to_frames(sec, fps):
    try:
        return int(round(float(sec) * float(fps)))
    except Exception:
        return 0


def pytime_to_frame(val):
    """
    Flame sometimes gives PyTime objects for record_in/out.
    Try to get a frame/int out of it gracefully.
    """
    # already int
    if isinstance(val, int):
        return val
    # some Flame objects expose .frame
    if hasattr(val, "frame"):
        try:
            return int(val.frame)
        except Exception:
            pass
    # some expose .value
    if hasattr(val, "value"):
        try:
            return int(val.value)
        except Exception:
            pass
    # last resort
    try:
        return int(val)
    except Exception:
        return 0


def get_clip_and_fps(selection):
    """Return (clip_object, fps, asset_name) from a PySequence, PyClip, or PySegment."""
    for item in selection:
        # Flame PySequence
        if isinstance(item, flame.PySequence):
            fps = _extract_fps(item.frame_rate)
            raw_name = str(item.name)[1:-1]
            asset_name = raw_name.strip()
            return item, fps, asset_name

        # Flame PyClip (treat like sequence-level, no segment offset)
        if isinstance(item, flame.PyClip):
            fps = _extract_fps(getattr(item, "frame_rate", 24.0))
            raw_name = str(item.name)[1:-1]
            asset_name = raw_name.strip()
            return item, fps, asset_name

        # Flame PySegment
        elif isinstance(item, flame.PySegment):
            try:
                parent_sequence = item.parent.parent.parent
                fps = _extract_fps(parent_sequence.frame_rate)
                raw_name = str(parent_sequence.name)[1:-1]
                asset_name = raw_name.strip()
                return item, fps, asset_name
            except Exception:
                pass
    return None, 24.0, None

# ----------------------------------------------------------
# Main
# ----------------------------------------------------------

def shade_get_comments(selection):
    try:
        if not selection:
            show_message("Please select one or more clips or segments first.")
            return

        cfg = validate_config()
        api_key = cfg.get("shade_api_key") or cfg.get("api_key")
        project_token = str(flame.projects.current_project.nickname)
        drive_id = get_or_create_drive(cfg, project_token)
        log(f"Connected to Shade (drive: {drive_id}, project: {project_token})")

        total_markers = 0
        total_items_with_comments = 0
        comment_cache = {}  # Cache by asset_name to avoid re-fetching per segment

        for item in selection:
            clip, fps, asset_name = get_clip_and_fps([item])
            if not clip or not asset_name:
                continue

            # --- Use cache if available ---
            if asset_name in comment_cache:
                comments = comment_cache[asset_name]
                log(f"Using cached comments for '{asset_name}'")
            else:
                results = search_shade_assets(api_key, drive_id, asset_name)
                if not results:
                    log(f"WARNING: No Shade asset found for {asset_name}")
                    continue

                # Strip extensions from all results and check for exact match
                cleaned_results = []
                for r in results:
                    shade_name = r.get("name", "")
                    no_ext = os.path.splitext(shade_name)[0]  # strip .mp4, .mov, etc
                    cleaned_results.append(no_ext)

                # Find exact match
                exact_match_found = asset_name in cleaned_results
                if not exact_match_found:
                    log(f"WARNING: No exact match found for '{asset_name}' in search results")
                    continue

                # Get the matching asset (find the index and use corresponding result)
                match_index = cleaned_results.index(asset_name)
                asset_id = results[match_index]
                comments = get_asset_comments(api_key, drive_id, asset_id)
                comment_cache[asset_name] = comments
                log(f"Retrieved {len(comments)} comment(s) for '{asset_name}'")

            if not comments:
                continue

            total_items_with_comments += 1
            total_markers_this_item = 0
            combined_texts = []  # Collect all comment texts for segment comment field

            # --- Segment timing info (temporarily disabled) ---
            is_segment = isinstance(item, flame.PySegment)
            # seg_rec_in = seg_rec_out = None
            # if is_segment:
            #     record_in = str(item.record_in).replace("+", ":")[1:-1]
            #     record_out = str(item.record_out).replace("+", ":")[1:-1]
            #     try:
            #         seg_rec_in = timecode_to_frames(record_in, fps)
            #         seg_rec_out = timecode_to_frames(record_out, fps)
            #     except Exception:
            #         seg_rec_in = seg_rec_out = None

            # --- Calculate offset dynamically (disabled: use 0) ---
            offset_frames = 0

            # --- Add markers ---
            base_offset = 0  # Shade starts at frame 0, Flame at frame 1...still trying to sort this out
            for c in comments:
                tc_str = c.get("tc_start")
                if tc_str:
                    frame_num = timecode_to_frames(tc_str, fps)
                else:
                    ts_sec = c.get("timestamp", 0.0)
                    frame_num = int(round(ts_sec * fps))

                adjusted_frame = frame_num + offset_frames + base_offset

                try:
                    marker = clip.create_marker(int(adjusted_frame))
                    author = c.get("author", "Unknown")
                    content = (c.get("content") or "").strip()
                    replies = c.get("replies", [])
                    if replies:
                        reply_strs = [
                            f"**REPLY** {r.get('author', 'Unknown')}: {r.get('content', '').strip()}"
                            for r in replies if r.get("content")
                        ]
                        content += "  " + "  ".join(reply_strs)
                    marker.name = author
                    try:
                        marker.colour_label = "Address Comments"
                    except Exception:
                        marker.colour = (0.1137, 0.2627, 0.1764)
                    marker.comment = content

                    # Apply duration (seconds -> frames) if present
                    duration_sec = c.get("duration")
                    if duration_sec:
                        try:
                            marker.duration = int(round(float(duration_sec) * fps))
                            log(f"Set duration={marker.duration} frames for '{asset_name}'")
                        except Exception as e:
                            log(f"WARNING: Could not set duration for marker: {e}")

                    # Color the item itself
                    total_markers_this_item += 1
                    combined_texts.append(content)  # Collect comment text for segment comment field
                    try:
                        item.colour_label = "Address Comments"
                    except Exception:
                        item.colour = (0.1137, 0.2627, 0.1764)

                except Exception as e:
                    log(f"WARNING: Could not create marker at frame {adjusted_frame}: {e}")

            total_markers += total_markers_this_item
            log(f"Added {total_markers_this_item} comment marker(s) for '{asset_name}'")

            # If this was a segment and we successfully added any markers,
            # color its parent sequence as "Address Comments" and set item.comment
            if is_segment and total_markers_this_item > 0:
                try:
                    parent_sequence = item.parent.parent.parent
                    try:
                        parent_sequence.colour_label = "Address Comments"
                    except Exception:
                        parent_sequence.colour = (0.1137, 0.2627, 0.1764)
                    log(f"Colored parent sequence for segment '{asset_name}'")
                except Exception as e:
                    log(f"WARNING: Could not color parent sequence: {e}")
                
                # Combine all comment texts into item.comment
                if combined_texts:
                    try:
                        item.comment = "\n\n".join(combined_texts)
                        log(f"Set item.comment with {len(combined_texts)} comment(s) for segment '{asset_name}'")
                    except Exception as e:
                        log(f"WARNING: Could not set item.comment: {e}")

        if total_items_with_comments == 0:
            show_message("No comments found on Shade for any selected items.")
        else:
            show_message(f"Added {total_markers} markers across {total_items_with_comments} item(s).")

    except Exception as e:
        log(f"ERROR: Failed: {e}\n{traceback.format_exc()}")
        show_message(f"Error: {e}")

# ----------------------------------------------------------
# Flame Menu Integration
# ----------------------------------------------------------

def scope_segment(selection):
    return any(isinstance(s, flame.PySegment) for s in selection)

def scope_clip_or_sequence(selection):
    return all(isinstance(item, (flame.PyClip, flame.PySequence)) for item in selection)


def get_timeline_custom_ui_actions():
    return [
        {
            "name": FOLDER_NAME,
            "actions": [
                {
                    "name": SCRIPT_NAME,
                    "execute": shade_get_comments,
                    "isVisible": scope_segment,
                    "minimumVersion": "2025",
                }
            ],
        }
    ]


def get_media_panel_custom_ui_actions():
    return [
        {
            "name": FOLDER_NAME,
            "actions": [
                {
                    "name": SCRIPT_NAME,
                    "execute": shade_get_comments,
                    "isVisible": scope_clip_or_sequence,
                    "minimumVersion": "2025",
                }
            ],
        }
    ]
