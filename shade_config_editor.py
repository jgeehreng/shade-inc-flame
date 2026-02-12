#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Shade Config Editor (Unified Global + User)
Uppercut VFX Pipeline
Accessible from Main Menu -> Shade -> Edit Config
Now with:
- Project Token (nickname | name)
- Debug Mode (bool)
"""

import flame
import os
import json
import requests
import webbrowser
from pathlib import Path
from PySide6 import QtWidgets, QtCore

# ---------------------------------------------------------------------
# Paths & Constants
# ---------------------------------------------------------------------
GLOBAL_CONFIG_PATH = "/opt/Autodesk/shared/python/shade/config/shared_config.json"
USER_CONFIG_DIR = Path.home() / "flame/python/shade"
USER_CONFIG_PATH = USER_CONFIG_DIR / "user_config.json"
SHADE_DOCS_URL = "https://academy.shade.inc/developers#authenticating-with-the-python-sdk"
SHADE_API_BASE = "https://api.shade.inc"

# valid values for project token
PROJECT_TOKEN_NICKNAME = "nickname"
PROJECT_TOKEN_NAME = "name"

FOLDER_NAME = "UC Shade"
SCRIPT_NAME = "Config Editor"
VERSION = "v1.1.1"

# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def log(msg):
    print(f"[Shade Config Editor] {msg}")


def load_json(path, fallback=None):
    try:
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
    except Exception as e:
        log(f"Error loading {path}: {e}")
    return fallback or {}


def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    log(f"Saved {path}")


def validate_api_key(api_key: str):
    """Validate key and return list of workspaces."""
    if not api_key:
        return False, "Missing API key.", []

    try:
        r = requests.get(
            f"{SHADE_API_BASE}/workspaces",
            headers={"Authorization": api_key},
            timeout=10,
        )
    except Exception as e:
        return False, f"Request failed: {e}", []

    if r.status_code == 401:
        return False, "Invalid API key.", []
    if r.status_code != 200:
        return False, f"Unexpected response: {r.status_code} {r.text[:120]}", []

    try:
        data = r.json()
    except Exception:
        return False, "Invalid JSON from Shade API.", []

    if isinstance(data, list) and data:
        return True, "API key validated successfully.", data
    return False, "No workspaces returned for this key.", []


# ---------------------------------------------------------------------
# Main Editor UI
# ---------------------------------------------------------------------
class ShadeConfigEditor(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Shade Config Editor — Uppercut Pipeline")
        self.setWindowFlags(QtCore.Qt.WindowStaysOnTopHint)
        self.resize(640, 480)
        self.layout = QtWidgets.QVBoxLayout(self)

        # Load configs
        self.global_cfg = load_json(
            GLOBAL_CONFIG_PATH,
            {
                "jobs_folder": "/Volumes/vfx/UC_Jobs",
                "preset_path_h264": "/opt/Autodesk/shared/flame_presets/h264.json",
                "preset_path_prores": "/opt/Autodesk/shared/flame_presets/prores4444.json",
                "shade_base_url": SHADE_API_BASE,
                # new ones
                "project_token": PROJECT_TOKEN_NICKNAME,
                "debug": False,
            },
        )
        self.user_cfg = load_json(
            USER_CONFIG_PATH,
            {
                "shade_api_key": "",
                "shade_workspace_id": "",
            },
        )

        self.build_ui()
        self.populate_fields()

    # ------------------------------------------------------
    def build_ui(self):
        tabs = QtWidgets.QTabWidget()
        self.layout.addWidget(tabs)

        # ------------------ GLOBAL TAB ------------------
        global_tab = QtWidgets.QWidget()
        g_layout = QtWidgets.QFormLayout(global_tab)

        self.g_jobs_folder = QtWidgets.QLineEdit()
        self.g_h264 = QtWidgets.QLineEdit()
        self.g_prores = QtWidgets.QLineEdit()
        self.g_base_url = QtWidgets.QLineEdit()

        # NEW: project token dropdown
        self.g_project_token = QtWidgets.QComboBox()
        self.g_project_token.addItem("Project Nickname", PROJECT_TOKEN_NICKNAME)
        self.g_project_token.addItem("Project Name", PROJECT_TOKEN_NAME)

        # NEW: debug checkbox
        self.g_debug = QtWidgets.QCheckBox("Enable verbose Shade debug logging")

        # Jobs folder row with browse button
        jobs_row = QtWidgets.QHBoxLayout()
        jobs_row.addWidget(self.g_jobs_folder)
        jobs_browse_btn = QtWidgets.QPushButton("Browse...")
        jobs_browse_btn.setFixedWidth(80)
        jobs_browse_btn.clicked.connect(lambda: self.browse_jobs_folder())
        jobs_row.addWidget(jobs_browse_btn)

        # H.264 preset row with browse button
        h264_row = QtWidgets.QHBoxLayout()
        h264_row.addWidget(self.g_h264)
        h264_browse_btn = QtWidgets.QPushButton("Browse...")
        h264_browse_btn.setFixedWidth(80)
        h264_browse_btn.clicked.connect(lambda: self.browse_h264_preset())
        h264_row.addWidget(h264_browse_btn)

        # ProRes preset row with browse button
        prores_row = QtWidgets.QHBoxLayout()
        prores_row.addWidget(self.g_prores)
        prores_browse_btn = QtWidgets.QPushButton("Browse...")
        prores_browse_btn.setFixedWidth(80)
        prores_browse_btn.clicked.connect(lambda: self.browse_prores_preset())
        prores_row.addWidget(prores_browse_btn)

        g_layout.addRow("Jobs Folder:", jobs_row)
        g_layout.addRow("H.264 Preset Path:", h264_row)
        g_layout.addRow("ProRes Preset Path:", prores_row)
        g_layout.addRow("Shade API Base URL:", self.g_base_url)
        g_layout.addRow("Project Token:", self.g_project_token)
        g_layout.addRow("Debug Mode:", self.g_debug)

        tabs.addTab(global_tab, "Global Settings")

        # ------------------ USER TAB ------------------
        user_tab = QtWidgets.QWidget()
        u_layout = QtWidgets.QFormLayout(user_tab)
        self.u_api_key = QtWidgets.QLineEdit()
        self.u_api_key.setEchoMode(QtWidgets.QLineEdit.Password)
        self.u_workspace_combo = QtWidgets.QComboBox()

        # API key row
        api_row = QtWidgets.QHBoxLayout()
        api_row.addWidget(self.u_api_key)

        validate_btn = QtWidgets.QPushButton("Validate Key")
        validate_btn.setFixedWidth(120)
        validate_btn.clicked.connect(self.validate_key_clicked)

        docs_btn = QtWidgets.QPushButton("Get API Key")
        docs_btn.setFixedWidth(120)
        docs_btn.clicked.connect(lambda: webbrowser.open(SHADE_DOCS_URL))

        api_row.addWidget(validate_btn)
        api_row.addWidget(docs_btn)

        u_layout.addRow("Shade API Key:", api_row)
        u_layout.addRow("Workspace:", self.u_workspace_combo)

        tabs.addTab(user_tab, "User Settings")

        # ------------------ FOOTER BUTTONS ------------------
        btns = QtWidgets.QHBoxLayout()
        self.save_btn = QtWidgets.QPushButton("Save All Settings")
        self.save_btn.clicked.connect(self.save_all)
        self.reload_btn = QtWidgets.QPushButton("Reload")
        self.reload_btn.clicked.connect(self.reload)
        self.close_btn = QtWidgets.QPushButton("Close")
        self.close_btn.clicked.connect(self.accept)
        btns.addStretch()
        btns.addWidget(self.save_btn)
        btns.addWidget(self.reload_btn)
        btns.addWidget(self.close_btn)
        self.layout.addLayout(btns)

        # ------------------ FOOTER INFO ------------------
        footer = QtWidgets.QLabel(
            f"<small><b>Global Config:</b> {GLOBAL_CONFIG_PATH}<br>"
            f"<b>User Config:</b> {USER_CONFIG_PATH}</small>"
        )
        footer.setTextFormat(QtCore.Qt.RichText)
        footer.setAlignment(QtCore.Qt.AlignCenter)
        self.layout.addWidget(footer)

    # ------------------------------------------------------
    def populate_fields(self):
        # Global
        self.g_jobs_folder.setText(self.global_cfg.get("jobs_folder", ""))
        self.g_h264.setText(self.global_cfg.get("preset_path_h264", ""))
        self.g_prores.setText(self.global_cfg.get("preset_path_prores", ""))
        self.g_base_url.setText(self.global_cfg.get("shade_base_url", SHADE_API_BASE))

        # NEW: project token
        project_token = self.global_cfg.get("project_token", PROJECT_TOKEN_NICKNAME)
        idx = self.g_project_token.findData(project_token)
        if idx < 0:
            idx = 0
        self.g_project_token.setCurrentIndex(idx)

        # NEW: debug
        self.g_debug.setChecked(bool(self.global_cfg.get("debug", False)))

        # User
        self.u_api_key.setText(self.user_cfg.get("shade_api_key", ""))

        self.u_workspace_combo.clear()
        wsid = self.user_cfg.get("shade_workspace_id", "")
        if wsid:
            self.u_workspace_combo.addItem(f"(saved) {wsid}", wsid)

    # ------------------------------------------------------
    def reload(self):
        self.global_cfg = load_json(GLOBAL_CONFIG_PATH, self.global_cfg)
        self.user_cfg = load_json(USER_CONFIG_PATH, self.user_cfg)
        self.populate_fields()

    # ------------------------------------------------------
    def browse_jobs_folder(self):
        """Browse for jobs folder directory."""
        current_path = self.g_jobs_folder.text().strip()
        if not current_path or not os.path.isdir(current_path):
            current_path = str(Path.home())
        
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "Select Jobs Folder",
            current_path,
            QtWidgets.QFileDialog.ShowDirsOnly | QtWidgets.QFileDialog.DontResolveSymlinks
        )
        if folder:
            self.g_jobs_folder.setText(folder)

    # ------------------------------------------------------
    def browse_h264_preset(self):
        """Browse for H.264 preset file."""
        current_path = self.g_h264.text().strip()
        if not current_path or not os.path.isfile(current_path):
            # Default to common preset locations
            default_dir = "/opt/Autodesk/shared/flame_presets"
            if not os.path.isdir(default_dir):
                default_dir = "/opt/Autodesk/presets"
            if not os.path.isdir(default_dir):
                default_dir = str(Path.home())
            current_path = default_dir
        
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select H.264 Preset File",
            current_path,
            "XML Files (*.xml);;JSON Files (*.json);;All Files (*)"
        )
        if file_path:
            self.g_h264.setText(file_path)

    # ------------------------------------------------------
    def browse_prores_preset(self):
        """Browse for ProRes preset file."""
        current_path = self.g_prores.text().strip()
        if not current_path or not os.path.isfile(current_path):
            # Default to common preset locations
            default_dir = "/opt/Autodesk/shared/flame_presets"
            if not os.path.isdir(default_dir):
                default_dir = "/opt/Autodesk/presets"
            if not os.path.isdir(default_dir):
                default_dir = str(Path.home())
            current_path = default_dir
        
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select ProRes Preset File",
            current_path,
            "XML Files (*.xml);;JSON Files (*.json);;All Files (*)"
        )
        if file_path:
            self.g_prores.setText(file_path)

    # ------------------------------------------------------
    def validate_key_clicked(self):
        api_key = self.u_api_key.text().strip()
        if not api_key:
            QtWidgets.QMessageBox.warning(self, "Missing Key", "Please enter your Shade API key first.")
            return

        self.setCursor(QtCore.Qt.WaitCursor)
        ok, msg, workspaces = validate_api_key(api_key)
        self.setCursor(QtCore.Qt.ArrowCursor)

        if ok:
            QtWidgets.QMessageBox.information(self, "Shade API", msg)
            self.u_workspace_combo.clear()
            for ws in workspaces:
                ws_name = ws.get("name", "Unnamed Workspace")
                ws_id = ws.get("id", "")
                self.u_workspace_combo.addItem(f"{ws_name} ({ws_id})", ws_id)
        else:
            QtWidgets.QMessageBox.critical(self, "Shade API", msg)

    # ------------------------------------------------------
    def save_all(self):
        # Update configs
        self.global_cfg.update(
            {
                "jobs_folder": self.g_jobs_folder.text().strip(),
                "preset_path_h264": self.g_h264.text().strip(),
                "preset_path_prores": self.g_prores.text().strip(),
                "shade_base_url": self.g_base_url.text().strip(),
                # new ones
                "project_token": self.g_project_token.currentData(),
                "debug": bool(self.g_debug.isChecked()),
            }
        )

        self.user_cfg.update(
            {
                "shade_api_key": self.u_api_key.text().strip(),
                "shade_workspace_id": self.u_workspace_combo.currentData() or "",
            }
        )

        save_json(GLOBAL_CONFIG_PATH, self.global_cfg)
        save_json(USER_CONFIG_PATH, self.user_cfg)
        QtWidgets.QMessageBox.information(
            self, "Saved", "Global and User settings saved successfully."
        )


# ---------------------------------------------------------------------
# Flame Menu Integration
# ---------------------------------------------------------------------
def launch_editor(*args, **kwargs):
    try:
        dlg = ShadeConfigEditor()
        dlg.exec()
    except Exception as e:
        print(f"[Shade Config Editor] Failed to launch: {e}")


def get_main_menu_custom_ui_actions():
    return [
        {
            "hierarchy": [FOLDER_NAME],
            "actions": [
                {
                    "name": SCRIPT_NAME,
                    "execute": launch_editor,
                    "minimumVersion": "2025",
                }
            ],
        }
    ]
