#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Shade EDL Markers v1.0 — Uppercut VFX Pipeline

Imports a marker EDL exported from Shade and adds Flame markers.
Record timecode is frame-accurate. A 01:00:00:00 start is treated as
the head of the clip.
"""

import ast
import os
import re
import traceback
import flame
from os.path import expanduser

FOLDER_NAME = "UC Shade"
SCRIPT_NAME = "EDL Markers"
VERSION = "v1.0"

EVENT_RE = re.compile(
    r"(\d{2}:\d{2}:\d{2}:\d{2})\s+"
    r"(\d{2}:\d{2}:\d{2}:\d{2})\s+"
    r"(\d{2}:\d{2}:\d{2}:\d{2})\s+"
    r"(\d{2}:\d{2}:\d{2}:\d{2})\s*$"
)
TIMECODE_RE = re.compile(r"^\d{2}:\d{2}:\d{2}:\d{2}$")


def log(msg):
    print(f"[{SCRIPT_NAME}] {msg}")


def show_message(text, title=SCRIPT_NAME):
    try:
        if hasattr(flame, "message_dialog"):
            flame.message_dialog(title, text)
        else:
            from PySide6 import QtWidgets
            QtWidgets.QMessageBox.information(None, title, text)
    except Exception:
        print(f"[{SCRIPT_NAME}] {text}")


def clip_name(item):
    try:
        return str(item.name)[1:-1].strip()
    except Exception:
        return ""


def file_stem(name):
    return os.path.splitext(os.path.basename(name or ""))[0].strip().lower()


def frame_rate_of(item):
    if isinstance(item, flame.PySegment):
        try:
            item = item.parent.parent.parent
        except Exception:
            pass
    rate = getattr(item, "frame_rate", 24.0)
    if isinstance(rate, (int, float)):
        return float(rate)
    text = str(rate)
    number = text.split()[0] if text else "24"
    try:
        return float(number)
    except ValueError:
        return 24.0


def timecode_base(fps):
    """Non-drop timecode counts 24 or 30 frames per timecode second."""
    if fps >= 26:
        return 30
    return 24


def timecode_to_frames(value, base):
    hours, minutes, seconds, frames = [int(part) for part in value.split(":")]
    return ((hours * 3600) + (minutes * 60) + seconds) * base + frames


def parse_comment_line(line):
    text = line.strip()
    commenter = "Unknown"
    duration = None
    comment_parts = []
    for part in text.split("|"):
        piece = part.strip()
        if piece.startswith("M:"):
            meta = piece[2:].strip()
            if meta.startswith("@"):
                meta = meta[1:]
            name = meta.split(",", 1)[0].strip()
            if name:
                commenter = name
        elif piece.startswith("D:"):
            try:
                duration = int(piece[2:].strip())
            except ValueError:
                duration = None
        elif piece.startswith("C:"):
            continue
        elif piece:
            comment_parts.append(piece)
    return " ".join(comment_parts).strip(), commenter, duration


def read_shade_edl(edl_path):
    title = ""
    fcm = "NON-DROP FRAME"
    events = []
    current = None

    with open(edl_path, mode="r") as handle:
        for raw in handle:
            line = raw.rstrip("\n")
            stripped = line.strip()
            if stripped.startswith("TITLE:"):
                title = stripped.split(":", 1)[1].strip()
                continue
            if stripped.startswith("FCM:"):
                fcm = stripped.split(":", 1)[1].strip()
                continue
            match = EVENT_RE.search(stripped)
            if match and stripped[:3].strip().isdigit():
                current = {
                    "rec_in": match.group(3),
                    "rec_out": match.group(4),
                    "comment": "",
                    "commenter": "Unknown",
                    "duration": None,
                }
                events.append(current)
                continue
            if current is not None and stripped and not stripped.startswith("TITLE") and not TIMECODE_RE.match(stripped):
                comment, commenter, duration = parse_comment_line(stripped)
                if comment:
                    current["comment"] = f"{current['comment']} {comment}".strip() if current["comment"] else comment
                if commenter != "Unknown":
                    current["commenter"] = commenter
                if duration is not None:
                    current["duration"] = duration

    if "DROP" in fcm.upper() and "NON-DROP" not in fcm.upper():
        raise RuntimeError(f"Drop-frame EDLs are not supported ({fcm}). Export non-drop.")

    markers = [event for event in events if event.get("comment") and event.get("rec_in")]
    return title, markers


def marker_frames(event, base):
    start = timecode_to_frames(event["rec_in"], base)
    end = timecode_to_frames(event["rec_out"], base)
    span = event["duration"]
    if span is None:
        span = max(0, end - start)
    return start, span


def edl_origin(markers, base):
    """Shade marker EDLs start at 01:00:00:00. That hour is the head of the clip."""
    if markers and all(event["rec_in"].startswith("01:") for event in markers):
        return timecode_to_frames("01:00:00:00", base)
    return 0


def rows_for_item(title, markers, item):
    stem = file_stem(clip_name(item))
    title_stem = file_stem(title)
    if not title_stem or not stem or title_stem == stem:
        return markers
    log(f"Selection '{clip_name(item)}' does not match EDL title '{title_stem}'. Using the EDL anyway.")
    return markers


def _resolve_edl_path():
    selection = getattr(flame.browser, "selection", None)
    if isinstance(selection, str):
        try:
            parsed = ast.literal_eval(selection)
            if isinstance(parsed, (list, tuple)) and parsed:
                selection = parsed[0]
        except Exception:
            selection = selection.strip("[]'\" ")
    if isinstance(selection, (list, tuple)):
        selection = selection[0] if selection else ""
    return expanduser(selection) if selection else ""


def add_markers(selection):
    print(f"\n[{SCRIPT_NAME}] {VERSION} — Start")
    try:
        if not selection:
            show_message("Please select one or more clips, sequences, or segments first.")
            return

        flame.browser.show(
            title="Select Shade EDL",
            select_directory=False,
            multi_selection=False,
            extension="edl",
            default_path=expanduser("~/Downloads"),
        )
        edl_path = _resolve_edl_path()
        if not edl_path:
            return
        if not os.path.isfile(edl_path):
            show_message(f"EDL file not found: {edl_path}")
            return

        title, markers = read_shade_edl(edl_path)
        if not markers:
            show_message("No marker events found in the EDL.")
            return

        total = 0
        matched_items = 0
        for item in selection:
            if not isinstance(item, (flame.PyClip, flame.PySequence, flame.PySegment)):
                continue
            item_rows = rows_for_item(title, markers, item)
            if not item_rows:
                continue

            base = timecode_base(frame_rate_of(item))
            origin = edl_origin(item_rows, base)
            added = 0
            texts = []
            for event in item_rows:
                start, span = marker_frames(event, base)
                frame = start - origin
                if frame < 0:
                    log(f"Skipping {event['rec_in']}: before the clip head.")
                    continue
                try:
                    marker = item.create_marker(int(frame))
                except Exception as exc:
                    log(f"Could not create marker at frame {frame}: {exc}")
                    continue

                commenter = event["commenter"]
                comment = event["comment"]
                marker.name = commenter
                marker.comment = comment
                try:
                    marker.colour_label = "Address Comments"
                except Exception:
                    marker.colour = (0.1137, 0.2627, 0.1764)
                if span > 1:
                    try:
                        marker.duration = int(span)
                    except Exception as exc:
                        log(f"Could not set duration: {exc}")

                added += 1
                texts.append(comment)
                log(f"{clip_name(item)} {event['rec_in']} -> frame {frame} ({span}f): {commenter}: {comment}")

            if added:
                matched_items += 1
                total += added
                try:
                    item.colour_label = "Address Comments"
                except Exception:
                    item.colour = (0.1137, 0.2627, 0.1764)
                if isinstance(item, flame.PySegment):
                    try:
                        parent = item.parent.parent.parent
                        try:
                            parent.colour_label = "Address Comments"
                        except Exception:
                            parent.colour = (0.1137, 0.2627, 0.1764)
                    except Exception:
                        pass
                    try:
                        item.comment = "\n\n".join(texts)
                    except Exception:
                        pass
                log(f"Added {added} marker(s) to '{clip_name(item)}'.")

        if matched_items == 0:
            show_message("No markers were added.")
        else:
            show_message(f"Added {total} marker(s) across {matched_items} item(s).")
    except Exception as exc:
        log(f"Failed: {exc}\n{traceback.format_exc()}")
        show_message(f"Shade EDL Markers Error: {exc}")

    print(f"[{SCRIPT_NAME}] Done.")


def scope_clip_or_sequence(selection):
    return any(isinstance(item, (flame.PyClip, flame.PySequence)) for item in selection)


def scope_segment(selection):
    return any(isinstance(item, flame.PySegment) for item in selection)


def get_media_panel_custom_ui_actions():
    return [
        {
            "name": FOLDER_NAME,
            "actions": [
                {
                    "name": SCRIPT_NAME,
                    "order": 5,
                    "isVisible": scope_clip_or_sequence,
                    "execute": add_markers,
                    "minimumVersion": "2025",
                }
            ],
        }
    ]


def get_timeline_custom_ui_actions():
    return [
        {
            "name": FOLDER_NAME,
            "actions": [
                {
                    "name": SCRIPT_NAME,
                    "order": 2,
                    "isVisible": scope_segment,
                    "execute": add_markers,
                    "minimumVersion": "2025",
                }
            ],
        }
    ]
