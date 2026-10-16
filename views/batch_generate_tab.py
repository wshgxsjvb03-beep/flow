# -*- coding: utf-8 -*-
import os
import json
import logging
from pathlib import Path
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QTextEdit, QTableWidget, QTableWidgetItem, 
                             QHeaderView, QComboBox, QSpinBox, QFileDialog, QMessageBox,
                             QSplitter, QListWidget, QFrame, QInputDialog)
from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QGuiApplication

logger = logging.getLogger(__name__)
from models.batch_model import BatchProjectModel
from views.project_detail_widget import BatchExportDialog

class BatchGenerateTabWidget(QWidget):
    def __init__(self, plugin_server, parent=None):
        super().__init__(parent)
        self.plugin_server = plugin_server
        self.main_window = parent
        
        workspace = "."
        if self.main_window and hasattr(self.main_window, "workspace_dir"):
            workspace = self.main_window.workspace_dir
            
        self.model = BatchProjectModel(workspace)
        self.current_project = None
        self.init_ui()
        self.refresh_project_list()

    def init_ui(self):
        self.setStyleSheet("""
            QWidget#batch_root { background-color: #FAF6F0; }
            QLabel { font-size: 13px; color: #5D4037; font-weight: bold; }
            QPushButton { background-color: #E0A96D; color: white; border: none; border-radius: 4px; padding: 6px 12px; font-weight: bold; }
            QPushButton:hover { background-color: #D2904C; }
            QPushButton:pressed { background-color: #B87635; }
            QPushButton#btn_delete { background-color: #E57373; }
            QPushButton#btn_delete:hover { background-color: #EF5350; }
            QTextEdit, QTableWidget, QSpinBox, QComboBox, QListWidget { border: 1px solid #D7CCC8; border-radius: 4px; background-color: white; }
        """)
        self.setObjectName("batch_root")
        
        main_layout = QVBoxLayout(self)
        
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter, stretch=1)
        
        # ================= LEFT PANEL =================
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 10, 0)
        
        h_import = QHBoxLayout()
        self.btn_import_folder = QPushButton("📁 导入文件夹")
        self.btn_import_folder.clicked.connect(self.import_folder)
        self.btn_import_images = QPushButton("🖼️ 导入图片")
        self.btn_import_images.clicked.connect(self.import_images)
        h_import.addWidget(self.btn_import_folder)
        h_import.addWidget(self.btn_import_images)
        left_layout.addLayout(h_import)
        
        self.list_projects = QListWidget()
        self.list_projects.currentRowChanged.connect(self.on_project_selected)
        left_layout.addWidget(self.list_projects)
        
        self.btn_delete_project = QPushButton("🗑️ 删除选中任务")
        self.btn_delete_project.setObjectName("btn_delete")
        self.btn_delete_project.clicked.connect(self.delete_selected_project)
        left_layout.addWidget(self.btn_delete_project)
        
        # ================= RIGHT PANEL =================
        self.right_panel = QWidget()
        right_layout = QVBoxLayout(self.right_panel)
        right_layout.setContentsMargins(10, 0, 0, 0)
        
        config_frame = QFrame()
        config_frame.setStyleSheet("QFrame { background-color: white; border: 1px solid #D7CCC8; border-radius: 6px; }")
        config_layout = QHBoxLayout(config_frame)
        
        config_layout.addWidget(QLabel("批量模板:"))
        self.cb_template = QComboBox()
        self.cb_template.currentIndexChanged.connect(self.on_template_changed)
        config_layout.addWidget(self.cb_template)
        
        config_layout.addWidget(QLabel("单个任务块时长:"))
        self.cb_duration = QComboBox()
        self.cb_duration.addItems(["4秒", "6秒", "8秒", "10秒"])
        self.cb_duration.setCurrentText("8秒")
        self.cb_duration.currentIndexChanged.connect(self.save_current_project)
        config_layout.addWidget(self.cb_duration)
        
        config_layout.addWidget(QLabel("尺寸比例:"))
        self.cb_aspect = QComboBox()
        self.cb_aspect.addItems(["16:9", "9:16"])
        self.cb_aspect.setCurrentText("16:9")
        self.cb_aspect.currentIndexChanged.connect(self.save_current_project)
        config_layout.addWidget(self.cb_aspect)
        
        config_layout.addWidget(QLabel("单批次生成积分上限:"))
        self.sb_points = QSpinBox()
        self.sb_points.setRange(1, 1000)
        self.sb_points.setValue(50)
        self.sb_points.setToolTip("每个导出的JSON任务块最高消耗积分")
        self.sb_points.valueChanged.connect(self.save_current_project)
        config_layout.addWidget(self.sb_points)
        
        right_layout.addWidget(config_frame)
        
        h_action = QHBoxLayout()
        self.btn_allocate = QPushButton("🚀 一键多开分配生成 (分批JSON)")
        self.btn_allocate.setStyleSheet("background-color: #4CAF50; font-size: 14px;")
        self.btn_allocate.clicked.connect(self.export_batch_json)
        h_action.addWidget(self.btn_allocate)
        
        self.btn_export_all = QPushButton("💾 导出全部JSON")
        self.btn_export_all.clicked.connect(self.export_all_json)
        h_action.addWidget(self.btn_export_all)
        right_layout.addLayout(h_action)
        
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["序号", "图片名称", "时长", "提示词", "操作"])
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        right_layout.addWidget(self.table)
        
        splitter.addWidget(left_panel)
        splitter.addWidget(self.right_panel)
        splitter.setSizes([300, 700])
        self.right_panel.setEnabled(False)

    def refresh_project_list(self):
        self.list_projects.clear()
        for p in self.model.projects:
            self.list_projects.addItem(f"{p['name']} ({len(p['images'])}图)")
            
    def refresh_template_list(self):
        self.cb_template.blockSignals(True)
        self.cb_template.clear()
        self.cb_template.addItem("未选择", "")
        if self.main_window and hasattr(self.main_window, "template_manager"):
            tm = self.main_window.template_manager
            if hasattr(tm, "batch_templates"):
                for t in tm.batch_templates:
                    self.cb_template.addItem(t.get("name", "未命名"), t.get("id"))
        self.cb_template.blockSignals(False)

    def _get_next_task_name(self):
        def to_chinese_num(n):
            units = ["", "一", "二", "三", "四", "五", "六", "七", "八", "九"]
            if n < 10: return units[n]
            if n == 10: return "十"
            if n < 20: return "十" + units[n % 10]
            if n < 100:
                tens = units[n // 10] + "十"
                return tens if n % 10 == 0 else tens + units[n % 10]
            return str(n)
            
        import re
        max_idx = 0
        for p in self.model.projects:
            name = p.get("name", "")
            if name.startswith("批量生成"):
                # fallback for basic numbers just in case
                num_str = name.replace("批量生成", "")
                if num_str.isdigit():
                    max_idx = max(max_idx, int(num_str))
                else:
                    # simplistic check for chinese numbering up to 99
                    for i in range(1, 100):
                        if num_str == to_chinese_num(i):
                            max_idx = max(max_idx, i)
                            break
                            
        return f"批量生成{to_chinese_num(max_idx + 1)}"

    def import_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择图片文件夹")
        if not folder:
            return
        
        valid_exts = {'.png', '.jpg', '.jpeg', '.webp'}
        images = []
        try:
            for f in os.listdir(folder):
                if Path(f).suffix.lower() in valid_exts:
                    images.append(os.path.join(folder, f))
            images.sort()
        except Exception as e:
            logger.error(f"Error reading directory: {e}")
            
        if not images:
            QMessageBox.warning(self, "无图片", "该文件夹下没有支持的图片文件。")
            return
            
        name = self._get_next_task_name()
        self.create_new_project(name, images)

    def import_images(self):
        files, _ = QFileDialog.getOpenFileNames(self, "选择图片", "", "Images (*.png *.jpg *.jpeg *.webp)")
        if not files:
            return
        files.sort()
        name = self._get_next_task_name()
        self.create_new_project(name, files)
        
    def create_new_project(self, name, files):
        images_data = []
        for f in files:
            images_data.append({
                "path": f,
                "prompt": "",
                "duration": 8
            })
        self.model.create_project(name, images_data)
        self.refresh_project_list()
        self.list_projects.setCurrentRow(len(self.model.projects) - 1)

    def delete_selected_project(self):
        row = self.list_projects.currentRow()
        if row < 0: return
        p = self.model.projects[row]
        reply = QMessageBox.question(self, "删除确认", f"确定要删除任务 '{p['name']}' 吗？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.model.delete_project(p["id"])
            self.refresh_project_list()
            self.right_panel.setEnabled(False)

    def on_project_selected(self, row):
        if row < 0 or row >= len(self.model.projects):
            self.current_project = None
            self.right_panel.setEnabled(False)
            return
            
        self.current_project = self.model.projects[row]
        self.right_panel.setEnabled(True)
        self.refresh_template_list()
        
        self.cb_duration.blockSignals(True)
        self.sb_points.blockSignals(True)
        self.cb_template.blockSignals(True)
        self.cb_aspect.blockSignals(True)
        
        self.cb_duration.setCurrentText(f"{self.current_project.get('duration', 8)}秒")
        self.cb_aspect.setCurrentText(self.current_project.get('aspect_ratio', "16:9"))
        self.sb_points.setValue(self.current_project.get('points_cost', 50))
        
        tpl_id = self.current_project.get("template_id", "")
        idx = self.cb_template.findData(tpl_id)
        if idx >= 0:
            self.cb_template.setCurrentIndex(idx)
        else:
            self.cb_template.setCurrentIndex(0)
            
        self.cb_duration.blockSignals(False)
        self.sb_points.blockSignals(False)
        self.cb_template.blockSignals(False)
        self.cb_aspect.blockSignals(False)
        
        self.render_table()

    def on_template_changed(self):
        if not self.current_project: return
        tpl_id = self.cb_template.currentData()
        self.current_project["template_id"] = tpl_id
        
        content = ""
        if tpl_id and self.main_window and hasattr(self.main_window, "template_manager"):
            tm = self.main_window.template_manager
            if hasattr(tm, "batch_templates"):
                for t in tm.batch_templates:
                    if t["id"] == tpl_id:
                        content = t.get("content", "")
                        break
                        
        for img in self.current_project["images"]:
            img["prompt"] = content
            
        self.model.save_project(self.current_project)
        self.render_table()

    def save_current_project(self):
        if not self.current_project: return
        new_dur = int(self.cb_duration.currentText().replace("秒", ""))
        self.current_project["duration"] = new_dur
        self.current_project["points_cost"] = self.sb_points.value()
        self.current_project["aspect_ratio"] = self.cb_aspect.currentText()
        
        # Apply the new duration to all images in this project
        for img in self.current_project.get("images", []):
            img["duration"] = new_dur
            
        self.model.save_project(self.current_project)
        self.render_table()

    def export_batch_json(self):
        if not self.current_project: return
        
        images = self.current_project["images"]
        if not images:
            QMessageBox.warning(self, "提示", "没有可导出的任务。")
            return
            
        # Format tasks for batch dialog
        all_tasks = []
        skipped_count = 0
        
        cm = getattr(self.main_window, "config_manager", None) if self.main_window else None
        default_mode = getattr(cm, "default_generation_mode", "VIDEO_FRAMES") if cm else "VIDEO_FRAMES"
        default_model = getattr(cm, "default_video_model", "omni_1_1_flash") if cm else "omni_1_1_flash"
        default_aspect = getattr(cm, "default_aspect_ratio", "9:16") if cm else "9:16"
        task_interval = getattr(cm, "task_interval", 5) if cm else 5
        
        for idx, img in enumerate(images):
            image_path = Path(img.get("path", ""))
            image_stem = image_path.stem
            download_name = f"{image_stem}.mp4"
            
            # Just create a path in workspace so it's valid for JSON payload parsing by UI.js
            ws = Path(self.main_window.workspace_dir) if hasattr(self.main_window, 'workspace_dir') else Path('.')
            project_name = self.current_project.get("name", "批量任务")
            download_path_obj = ws / project_name / download_name
            
            # Check if video already exists on the actual disk location
            base_path = self.main_window.storage_manager.get_base_path() if hasattr(self.main_window, 'storage_manager') else None
            if not base_path:
                base_path = Path.home() / "Downloads"
            check_path = Path(base_path) / "Flow" / project_name / f"{image_stem}.mp4"
            
            if check_path.exists() and check_path.stat().st_size > 0:
                skipped_count += 1
                continue
            
            task_dict = {
                "_original_index": idx,
                "index": idx + 1,
                "prompt": img.get("prompt", ""),
                "image_name": image_path.name,
                "local_image_path": str(image_path.resolve()),
                "duration": img.get("duration", 8),
                "mode": default_mode,
                "model": default_model,
                "interval": task_interval,
                "aspect_ratio": self.current_project.get("aspect_ratio", default_aspect),
                "download_path": str(download_path_obj.resolve())
            }
            all_tasks.append(task_dict)
            
        if not all_tasks:
            if skipped_count > 0:
                QMessageBox.information(self, "提示", f"该任务中的 {skipped_count} 个视频已全部生成成功，无需再次分配！")
            else:
                QMessageBox.warning(self, "提示", "没有可导出的任务。")
            return
            
        # Partition tasks using First Fit Decreasing (FFD)
        batches = []
        max_batch_points = self.sb_points.value()
        
        class MockCM:
            def __init__(self, pts, real_cm=None):
                self.max_batch_points = pts
                self.default_generation_mode = getattr(real_cm, "default_generation_mode", "VIDEO_FRAMES") if real_cm else "VIDEO_FRAMES"
                self.default_aspect_ratio = getattr(real_cm, "default_aspect_ratio", "9:16") if real_cm else "9:16"
                self.default_video_model = getattr(real_cm, "default_video_model", "omni_1_1_flash") if real_cm else "omni_1_1_flash"
                self.task_interval = getattr(real_cm, "task_interval", 5) if real_cm else 5
            def get_points_for_duration(self, dur):
                points_map = {10: 15, 8: 12, 6: 10, 4: 7}
                return points_map.get(dur, 10)
                
        cm_mock = MockCM(max_batch_points, cm)
        
        def get_task_points(task):
            return cm_mock.get_points_for_duration(task.get("duration", 4))

        all_tasks.sort(key=get_task_points, reverse=True)

        for task in all_tasks:
            pts = get_task_points(task)
            placed = False
            for batch in batches:
                current_batch_pts = sum(get_task_points(t) for t in batch)
                if current_batch_pts + pts <= max_batch_points:
                    batch.append(task)
                    placed = True
                    break
            if not placed:
                batches.append([task])
                
        # Sort back to original chronological index for clear display
        for batch in batches:
            batch.sort(key=lambda t: t["_original_index"])
            
        # Open the standard batch dialog
        dialog = BatchExportDialog(self, batches, cm_mock, skipped_count=skipped_count)
        # Override the dialog title/label to reflect the current batch points
        dialog.setWindowTitle(f"分批生成与多浏览器调度 (最高{max_batch_points}积分/批)")
        dialog.exec()

    def change_row_color(self, row, copied=True):
        from PyQt6.QtGui import QColor
        if copied:
            bg_color = QColor("#D4EDDA") # Light green
            text_color = QColor("#155724") # Dark green
        
        for col in range(self.table.columnCount()):
            item = self.table.item(row, col)
            if item:
                if copied:
                    item.setBackground(bg_color)
                    item.setForeground(text_color)
                else:
                    item.setData(Qt.ItemDataRole.BackgroundRole, None)
                    item.setData(Qt.ItemDataRole.ForegroundRole, None)

    def render_table(self):
        if not self.current_project: return
        images = self.current_project["images"]
        self.table.setRowCount(len(images))
        
        ws = Path(self.main_window.workspace_dir) if hasattr(self.main_window, 'workspace_dir') else Path('.')
        project_name = self.current_project.get("name", "批量任务")
        
        for i, img in enumerate(images):
            image_path = Path(img.get("path", ""))
            name = image_path.name
            dur = f"{img.get('duration', 8)}秒"
            prompt = img.get("prompt", "")
            
            self.table.setItem(i, 0, QTableWidgetItem(str(i+1)))
            self.table.setItem(i, 1, QTableWidgetItem(name))
            self.table.setItem(i, 2, QTableWidgetItem(dur))
            self.table.setItem(i, 3, QTableWidgetItem(prompt))
            
            w_action = QWidget()
            l_action = QHBoxLayout(w_action)
            l_action.setContentsMargins(2, 2, 2, 2)
            
            btn_copy_prompt = QPushButton("复制提示词")
            btn_copy_prompt.clicked.connect(lambda _, p=prompt: QGuiApplication.clipboard().setText(p))
            
            btn_copy_path = QPushButton("复制路径")
            btn_copy_path.clicked.connect(lambda _, p=img.get("path", ""): QGuiApplication.clipboard().setText(p))
            
            btn_export = QPushButton("导出JSON")
            btn_export.clicked.connect(lambda _, idx=i: self.export_single_json(idx))
            
            l_action.addWidget(btn_copy_prompt)
            l_action.addWidget(btn_copy_path)
            l_action.addWidget(btn_export)
            self.table.setCellWidget(i, 4, w_action)
            # Get the actual base storage path where Chrome downloads
            base_path = self.main_window.storage_manager.get_base_path() if hasattr(self.main_window, 'storage_manager') else None
            if not base_path:
                base_path = Path.home() / "Downloads"
                
            check_path = Path(base_path) / "Flow" / project_name / f"{image_path.stem}.mp4"
            
            if check_path.exists() and check_path.stat().st_size > 0:
                self.change_row_color(i, copied=True)
            else:
                self.change_row_color(i, copied=False)

    def export_single_json(self, index):
        img = self.current_project["images"][index]
        image_path = Path(img.get("path", ""))
        ws = Path(self.main_window.workspace_dir) if hasattr(self.main_window, 'workspace_dir') else Path('.')
        project_name = self.current_project.get("name", "批量任务")
        download_path = str((ws / project_name / f"{image_path.stem}.mp4").resolve())
        cm = getattr(self.main_window, "config_manager", None) if self.main_window else None
        default_mode = getattr(cm, "default_generation_mode", "VIDEO_FRAMES") if cm else "VIDEO_FRAMES"
        default_model = getattr(cm, "default_video_model", "omni_1_1_flash") if cm else "omni_1_1_flash"
        default_aspect = getattr(cm, "default_aspect_ratio", "9:16") if cm else "9:16"
        task_interval = getattr(cm, "task_interval", 5) if cm else 5
        data = [{
            "prompt": img.get("prompt", ""),
            "image": image_path.name,
            "duration": img.get("duration", 8),
            "mode": default_mode,
            "model": default_model,
            "interval": task_interval,
            "aspect_ratio": self.current_project.get("aspect_ratio", default_aspect),
            "download_path": download_path
        }]
        json_str = json.dumps(data, ensure_ascii=False, indent=2)
        QGuiApplication.clipboard().setText(json_str)
        QMessageBox.information(self, "复制成功", "单条 JSON 已复制到剪贴板！")
        
    def export_all_json(self):
        if not self.current_project: return
        images = self.current_project["images"]
        if not images: return
        
        ws = Path(self.main_window.workspace_dir) if hasattr(self.main_window, 'workspace_dir') else Path('.')
        project_name = self.current_project.get("name", "批量任务")
        cm = getattr(self.main_window, "config_manager", None) if self.main_window else None
        default_mode = getattr(cm, "default_generation_mode", "VIDEO_FRAMES") if cm else "VIDEO_FRAMES"
        default_model = getattr(cm, "default_video_model", "omni_1_1_flash") if cm else "omni_1_1_flash"
        default_aspect = getattr(cm, "default_aspect_ratio", "9:16") if cm else "9:16"
        task_interval = getattr(cm, "task_interval", 5) if cm else 5
        out = []
        for i in images:
            image_path = Path(i.get("path", ""))
            download_path = str((ws / project_name / f"{image_path.stem}.mp4").resolve())
            out.append({
                "prompt": i.get("prompt", ""), 
                "image": image_path.name, 
                "duration": i.get("duration", 8), 
                "mode": default_mode,
                "model": default_model,
                "interval": task_interval,
                "aspect_ratio": self.current_project.get("aspect_ratio", default_aspect),
                "download_path": download_path
            })
            
        QGuiApplication.clipboard().setText(json.dumps(out, ensure_ascii=False, indent=2))
        QMessageBox.information(self, "复制成功", "已复制全部任务 JSON！")
