# -*- coding: utf-8 -*-
import os
import re
import sys
import logging
from pathlib import Path

logger = logging.getLogger(__name__)
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QTextEdit, QTableWidget, QTableWidgetItem, 
                             QHeaderView, QTabWidget, QListWidget, QListWidgetItem, 
                             QMessageBox, QSplitter, QLineEdit, QAbstractItemView, 
                             QToolTip, QComboBox, QFrame, QDialog, QCheckBox, QScrollArea)
from PyQt6.QtCore import Qt, pyqtSlot, QUrl, QTimer, QDateTime
from PyQt6.QtGui import QDesktopServices, QGuiApplication, QCursor, QPixmap
from models.project_model import ProjectModel
from services.text_processor import TextProcessor
from services.downloader import DownloadThread

class ProjectDetailWidget(QWidget):
    """Widget displaying detail and editing options for a selected project."""
    
    project_saved_signal = pyqtSlot() # To trigger sidebar reload if names change (not needed in v1, but good to have)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project_path = None
        self.project_model = None
        self.download_thread = None
        self.template_manager = None
        self.config_manager = None
        self.plugin_server = None
        self.copied_rows = set()
        self.dispatched_indices = set()
        self.is_auto_polling_active = False
        self.polling_timer = None
        self.active_batch_dialog = None
        self.enable_end_frame = False
        self.current_prop_row = -1
        self.init_ui()

    def set_template_manager(self, tm):
        self.template_manager = tm

    def set_config_manager(self, cm):
        self.config_manager = cm

    def set_plugin_server(self, ps):
        self.plugin_server = ps
        if self.plugin_server:
            self.plugin_server.report_received_signal.connect(self.on_plugin_report_received)
            self.plugin_server.client_connected_signal.connect(self.on_plugin_clients_changed)
            self.plugin_server.client_disconnected_signal.connect(self.on_plugin_clients_changed)
            self.plugin_server.client_updated_signal.connect(self.on_plugin_clients_changed)

    def on_plugin_clients_changed(self, info=None):
        if self.active_batch_dialog and self.active_batch_dialog.isVisible():
            self.active_batch_dialog.refresh_workers_list()

    def init_ui(self):
        # Base styling for warm theme
        self.setStyleSheet("""
            QWidget#detail_root {
                background-color: #FAF6F0;
            }
            QLabel#lbl_proj_title {
                font-size: 16px;
                font-weight: bold;
                color: #5D4037;
            }
            QLabel {
                font-size: 13px;
                color: #5D4037;
                font-weight: bold;
            }
            QPushButton {
                background-color: #E0A96D;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #D2904C;
            }
            QPushButton:pressed {
                background-color: #B87635;
            }
            QPushButton#btn_delete_segment {
                background-color: #E57373;
            }
            QPushButton#btn_delete_segment:hover {
                background-color: #EF5350;
            }
            QPushButton#btn_open_folder {
                background-color: #D7CCC8;
                color: #5D4037;
            }
            QPushButton#btn_open_folder:hover {
                background-color: #BCAAA4;
            }
            QTextEdit {
                background-color: white;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                color: #3E2723;
                font-family: Consolas, sans-serif;
                font-size: 13px;
            }
            QTableWidget {
                background-color: white;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                gridline-color: #EFEBE9;
                selection-background-color: #FFE0B2;
                selection-color: #5D4037;
            }
            QHeaderView::section {
                background-color: #D7CCC8;
                color: #5D4037;
                padding: 4px;
                font-weight: bold;
                border: 1px solid #EFEBE9;
            }
            QTabWidget::pane {
                border: 1px solid #D7CCC8;
                background-color: #FAF6F0;
                border-radius: 4px;
            }
            QTabBar::tab {
                background-color: #EFEBE9;
                color: #795548;
                padding: 8px 16px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                font-weight: bold;
            }
            QTabBar::tab:selected {
                background-color: #FAF6F0;
                color: #5D4037;
                border: 1px solid #D7CCC8;
                border-bottom-color: #FAF6F0;
            }
        """)
        
        self.setObjectName("detail_root")
        
        # We start in a "No Selection" state
        self.layout_stack = QVBoxLayout(self)
        
        self.no_selection_widget = QLabel("请在左侧选择一个工程项目以查看详情...")
        self.no_selection_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.no_selection_widget.setStyleSheet("font-size: 16px; color: #8D6E63; font-style: italic;")
        self.layout_stack.addWidget(self.no_selection_widget)
        
        # Create the main content widget (initially hidden)
        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        
        # Header Row
        header_layout = QHBoxLayout()
        self.lbl_proj_title = QLabel("项目名称:")
        self.lbl_proj_title.setObjectName("lbl_proj_title")
        header_layout.addWidget(self.lbl_proj_title)
        
        header_layout.addStretch()
        
        self.btn_open_folder = QPushButton("📂 在文件夹中显示")
        self.btn_open_folder.setObjectName("btn_open_folder")
        self.btn_open_folder.clicked.connect(self.open_project_folder)
        header_layout.addWidget(self.btn_open_folder)
        
        self.content_layout.addLayout(header_layout)
        
        # Tabs
        self.tabs = QTabWidget()
        self.init_text_tab()
        self.init_media_tab()
        self.init_compare_tab()
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.content_layout.addWidget(self.tabs)
        
        self.layout_stack.addWidget(self.content_widget)
        self.content_widget.setVisible(False)

    def _on_tab_changed(self, index):
        """Pauses media playback if switching away from video compare tab."""
        if hasattr(self, 'video_compare_widget') and self.video_compare_widget:
            compare_index = self.tabs.indexOf(self.video_compare_widget)
            if compare_index != -1 and index != compare_index:
                if hasattr(self.video_compare_widget, 'media_player') and self.video_compare_widget.media_player:
                    try:
                        self.video_compare_widget.media_player.pause()
                    except Exception:
                        pass

    def cleanup(self):
        """Cleans up active download threads and video compare widget resources."""
        if hasattr(self, 'download_thread') and self.download_thread:
            try:
                if self.download_thread.isRunning():
                    self.download_thread.stop()
            except Exception:
                pass
            self.download_thread = None
            
        if hasattr(self, 'video_compare_widget') and self.video_compare_widget:
            if hasattr(self.video_compare_widget, 'cleanup'):
                self.video_compare_widget.cleanup()

    def init_text_tab(self):
        tab_widget = QWidget()
        tab_layout = QVBoxLayout(tab_widget)
        tab_layout.setContentsMargins(10, 10, 10, 10)
        tab_layout.setSpacing(10)
        
        # 1. Top Selectors Layout
        selectors_layout = QHBoxLayout()
        selectors_layout.setSpacing(10)
        
        selectors_layout.addWidget(QLabel("选择统一提示词模板:"))
        self.combo_templates = QComboBox()
        self.combo_templates.setMaxVisibleItems(15)
        self.combo_templates.view().setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.combo_templates.setStyleSheet("""
            QComboBox {
                background-color: white;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 13px;
            }
            QComboBox QAbstractItemView {
                border: 1px solid #D7CCC8;
                background-color: white;
                selection-background-color: #FFE0B2;
                selection-color: #5D4037;
                outline: none;
            }
            QComboBox QAbstractItemView::item {
                min-height: 26px;
            }
        """)
        self.combo_templates.currentIndexChanged.connect(self.on_template_changed)
        selectors_layout.addWidget(self.combo_templates, stretch=1)
        
        selectors_layout.addWidget(QLabel("选择统一运镜预设:"))
        self.combo_motions = QComboBox()
        self.combo_motions.setMaxVisibleItems(15)
        self.combo_motions.view().setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.combo_motions.setStyleSheet("""
            QComboBox {
                background-color: white;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 13px;
            }
            QComboBox QAbstractItemView {
                border: 1px solid #D7CCC8;
                background-color: white;
                selection-background-color: #FFE0B2;
                selection-color: #5D4037;
                outline: none;
            }
            QComboBox QAbstractItemView::item {
                min-height: 26px;
            }
        """)
        self.combo_motions.currentIndexChanged.connect(self.on_motion_changed)
        selectors_layout.addWidget(self.combo_motions, stretch=1)
        
        self.btn_reset_all_segments = QPushButton("⚡ 重置所有片段为统一设置")
        self.btn_reset_all_segments.setStyleSheet("""
            QPushButton {
                background-color: #8D6E63;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 5px 10px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #795548;
            }
        """)
        self.btn_reset_all_segments.setToolTip("清空所有片段的单独模板与镜头设置，重新统一使用上方的全局设置。")
        self.btn_reset_all_segments.clicked.connect(self.reset_all_segments_to_unified)
        selectors_layout.addWidget(self.btn_reset_all_segments)
        
        tab_layout.addLayout(selectors_layout)
        
        # 2. Main Splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Left pane: Chinese & Spanish texts
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        left_layout.addWidget(QLabel("中文原文 (Chinese Source):"))
        self.txt_chinese = QTextEdit()
        left_layout.addWidget(self.txt_chinese)
        
        left_layout.addWidget(QLabel("西班牙语原文 (Spanish Source):"))
        self.txt_spanish = QTextEdit()
        left_layout.addWidget(self.txt_spanish)
        
        self.btn_segment = QPushButton("✨ 自动清洗并智能切分西文")
        self.btn_segment.clicked.connect(self.run_segmentation)
        left_layout.addWidget(self.btn_segment)
        
        left_widget.setLayout(left_layout)
        splitter.addWidget(left_widget)
        
        # Right pane: Segment Table
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)
        
        # Header Layout with Title and Search Input
        table_header_layout = QHBoxLayout()
        lbl_table_title = QLabel("切分段落与提示词工作台 (Segments & Prompts):")
        table_header_layout.addWidget(lbl_table_title)
        table_header_layout.addStretch()
        
        self.txt_search = QLineEdit()
        self.txt_search.setObjectName("txt_search")
        self.txt_search.setPlaceholderText("🔍 搜索本项目文案或提示词...")
        self.txt_search.setClearButtonEnabled(True)
        self.txt_search.setFixedWidth(240)
        self.txt_search.setStyleSheet("""
            QLineEdit#txt_search {
                background-color: white;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                padding: 3px 8px;
                font-size: 12px;
                color: #5D4037;
            }
            QLineEdit#txt_search:focus {
                border: 1px solid #E0A96D;
            }
        """)
        self.txt_search.textChanged.connect(self.filter_segments_table)
        table_header_layout.addWidget(self.txt_search)
        
        right_layout.addLayout(table_header_layout)
        
        # Inner splitter for Table and Property Panel
        self.table_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        self.table_segments = QTableWidget()
        self.table_segments.setColumnCount(6)
        self.table_segments.setHorizontalHeaderLabels([
            "序号", "分句文案 (双击可修改)", "字数", "时长 (秒)", "生成的提示词 (双击可复制)", "操作"
        ])
        self.table_segments.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_segments.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table_segments.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table_segments.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.table_segments.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table_segments.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Interactive)
        self.table_segments.cellChanged.connect(self.on_cell_changed)
        self.table_segments.cellDoubleClicked.connect(self.on_cell_double_clicked)
        self.table_segments.currentItemChanged.connect(self.on_table_selection_changed)
        
        self.table_splitter.addWidget(self.table_segments)
        
        # Property Panel Scroll Area
        self.property_scroll = QScrollArea()
        self.property_scroll.setWidgetResizable(True)
        self.property_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.property_scroll.setStyleSheet("QScrollArea { border: none; background-color: #FAF6F0; }")
        
        self.property_panel = QWidget()
        self.init_property_panel()
        self.property_scroll.setWidget(self.property_panel)
        self.table_splitter.addWidget(self.property_scroll)
        
        # Set default proportions
        self.table_splitter.setSizes([640, 260])
        from PyQt6.QtWidgets import QSizePolicy
        self.table_splitter.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        
        right_layout.addWidget(self.table_splitter, 1)
        
        # Table edit buttons
        table_buttons_layout = QHBoxLayout()
        self.btn_add_segment = QPushButton("＋ 添加行")
        self.btn_add_segment.clicked.connect(self.add_segment_row)
        table_buttons_layout.addWidget(self.btn_add_segment)
        
        self.btn_delete_segment = QPushButton("－ 删除选中行")
        self.btn_delete_segment.setObjectName("btn_delete_segment")
        self.btn_delete_segment.clicked.connect(self.delete_selected_segment)
        table_buttons_layout.addWidget(self.btn_delete_segment)
        
        table_buttons_layout.addStretch()
        
        self.btn_export_batch = QPushButton("📋 导出批量生成 JSON")
        self.btn_export_batch.setStyleSheet("background-color: #8B5CF6; color: white; font-weight: bold;")
        self.btn_export_batch.clicked.connect(self.export_batch_json)
        table_buttons_layout.addWidget(self.btn_export_batch)
        
        self.btn_import_report = QPushButton("📥 导入报告并归位视频")
        self.btn_import_report.setStyleSheet("background-color: #10B981; color: white; font-weight: bold;")
        self.btn_import_report.clicked.connect(self.import_execution_report)
        table_buttons_layout.addWidget(self.btn_import_report)
        
        self.btn_save_project = QPushButton("💾 保存修改")
        self.btn_save_project.clicked.connect(self.save_project_data)
        table_buttons_layout.addWidget(self.btn_save_project)
        
        right_layout.addLayout(table_buttons_layout)
        right_widget.setLayout(right_layout)
        splitter.addWidget(right_widget)
        
        # Collapse the left widget (Chinese & Spanish text inputs) by default.
        splitter.setSizes([0, 900])
        tab_layout.addWidget(splitter, stretch=1)
        
        tab_widget.setLayout(tab_layout)
        self.tabs.addTab(tab_widget, "📝 文案、切分与提示词")

    def init_media_tab(self):
        """Initializes the media management tab."""
        tab_widget = QWidget()
        layout = QVBoxLayout(tab_widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        
        # 1. Google Drive URL Downloader block
        dl_layout = QHBoxLayout()
        dl_layout.addWidget(QLabel("谷歌云盘链接 (Google Drive URL):"))
        
        self.txt_gdrive_url = QTextEdit()
        self.txt_gdrive_url.setMaximumHeight(60)
        self.txt_gdrive_url.setPlaceholderText("可包含多个谷歌云盘链接，每行一个...")
        dl_layout.addWidget(self.txt_gdrive_url)
        
        self.btn_download = QPushButton("📥 下载全部资源")
        self.btn_download.clicked.connect(self.start_download)
        dl_layout.addWidget(self.btn_download)
        
        layout.addLayout(dl_layout)
        
        # 2. Download status
        self.lbl_download_status = QLabel("下载状态: 未开始")
        self.lbl_download_status.setStyleSheet("color: #795548; font-style: italic;")
        layout.addWidget(self.lbl_download_status)
        
        # 3. Split-screen List and Image Preview
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Left side: List
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("下载的本地素材列表 (Double-click to open):"))
        
        self.list_media = QListWidget()
        self.list_media.doubleClicked.connect(self.open_media_file)
        self.list_media.currentItemChanged.connect(self.on_media_selection_changed)
        left_layout.addWidget(self.list_media)
        
        left_widget.setLayout(left_layout)
        splitter.addWidget(left_widget)
        
        # Right side: Preview
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(QLabel("图片素材预览 (Preview):"))
        
        self.lbl_preview = QLabel("选择左侧素材以预览...")
        self.lbl_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_preview.setStyleSheet("""
            QLabel {
                background-color: #EFEBE9;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                color: #8D6E63;
                font-weight: normal;
            }
        """)
        self.lbl_preview.setMinimumWidth(300)
        right_layout.addWidget(self.lbl_preview, stretch=1)
        
        right_widget.setLayout(right_layout)
        splitter.addWidget(right_widget)
        
        splitter.setSizes([350, 450])
        layout.addWidget(splitter, stretch=1)
        
        tab_widget.setLayout(layout)
        self.tabs.addTab(tab_widget, "📁 资源下载与管理")

    def reset_to_no_selection(self):
        """Resets the detail widget to the 'No Selection' state."""
        self.cleanup()
        self.project_path = None
        self.project_model = None
        self.content_widget.setVisible(False)
        self.no_selection_widget.setVisible(True)
        # Also clear the compare widget
        if hasattr(self, 'video_compare_widget'):
            self.video_compare_widget.set_project(None, None)

    def init_compare_tab(self):
        """Initializes the video vs script comparison tab (Tab 3)."""
        from views.video_compare_widget import VideoCompareWidget
        self.video_compare_widget = VideoCompareWidget()
        self.video_compare_widget.videos_deleted.connect(self.populate_segments_table)
        self.tabs.addTab(self.video_compare_widget, "🎬 视频与文案比对")

    def set_project(self, project_path):
        """Loads and binds project data."""
        self.project_path = Path(project_path)
        self.project_model = ProjectModel(self.project_path)
        self.copied_rows = set()
        self.dispatched_indices = set()
        self.failed_skip_indices = set()
        self.segment_retry_counts = {}
        
        # Switch visible UI
        self.no_selection_widget.setVisible(False)
        self.content_widget.setVisible(True)
        
        # Update labels and fields
        self.lbl_proj_title.setText(f"项目名称: {self.project_model.project_id} (序号: {self.project_model.index:02d})")
        self.txt_chinese.setPlainText(self.project_model.chinese_text)
        self.txt_spanish.setPlainText(self.project_model.spanish_text)
        self.txt_gdrive_url.setPlainText(self.project_model.google_drive_url)
        
        # Load end frame setting (project override or global default)
        if self.project_model.enable_end_frame is not None:
            self.enable_end_frame = bool(self.project_model.enable_end_frame)
        else:
            self.enable_end_frame = bool(getattr(self.config_manager, "enable_end_frame", False)) if self.config_manager else False

        if hasattr(self, "chk_enable_end_frame"):
            self.chk_enable_end_frame.blockSignals(True)
            self.chk_enable_end_frame.setChecked(self.enable_end_frame)
            self.chk_enable_end_frame.blockSignals(False)
        if hasattr(self, "container_end_image"):
            self.container_end_image.setVisible(self.enable_end_frame)

        # Populate table segments
        self.populate_segments_table()
        
        # Refresh media list
        self.refresh_media_list()
        
        # Refresh templates dropdowns & prompts table
        self.refresh_template_comboboxes()
        
        # Check if this project has an active background download running in MainWindow
        main_win = self.window()
        if hasattr(main_win, "active_downloads") and self.project_model.project_id in main_win.active_downloads:
            self.lbl_download_status.setText("下载状态: 正在后台自动下载中...")
            self.btn_download.setEnabled(False)
        else:
            # Check if downloads folder already contains files to prevent duplicate download triggers
            downloads_dir = self.project_path / "downloads" if self.project_path else None
            existing_files = [f for f in downloads_dir.iterdir() if f.is_file() and not f.name.endswith(".part")] if (downloads_dir and downloads_dir.exists()) else []
            if existing_files:
                self.lbl_download_status.setText(f"下载状态: 已下载完成 (共 {len(existing_files)} 个素材)")
                self.btn_download.setEnabled(True)
            else:
                self.lbl_download_status.setText("下载状态: 未开始")
                self.btn_download.setEnabled(True)
        
        # Refresh the video compare tab
        if hasattr(self, 'video_compare_widget'):
            self.video_compare_widget.set_project(self.project_model, self.project_path, self.config_manager)

    def populate_segments_table(self):
        """Fills QTableWidget with stored Spanish segments and generated prompts."""
        self.table_segments.blockSignals(True)
        self.table_segments.clearContents()
        
        if not self.project_model:
            self.table_segments.setRowCount(0)
            self.table_segments.blockSignals(False)
            return
            
        segments = self.project_model.spanish_segments
        self.table_segments.setRowCount(len(segments))
        
        for idx, seg in enumerate(segments):
            # 智能解析关联首帧图片素材
            img_name, _, _ = self.resolve_segment_image_and_data(idx, seg)
            if img_name:
                seg["image_name"] = img_name

            # 智能解析关联尾帧图片素材（若启用）
            if getattr(self, "enable_end_frame", False):
                end_img_name, _, _ = self.resolve_segment_end_image_and_data(idx, seg)
                if end_img_name:
                    seg["end_image_name"] = end_img_name

            # 0. Index & Icons (📷: 首帧图片, 🎬: 尾帧图片, ⚙️: 自定义模板/运镜)
            has_image = bool(seg.get("image_name"))
            has_end_image = bool(seg.get("end_image_name")) if getattr(self, "enable_end_frame", False) else False
            has_custom = bool(seg.get("template_id")) or bool(seg.get("motion_id"))
            idx_text = str(idx + 1)
            if has_image:
                idx_text += " 📷"
            if has_end_image:
                idx_text += " 🎬"
            if has_custom:
                idx_text += " ⚙️"
            self.table_segments.setItem(idx, 0, QTableWidgetItem(idx_text))
            self.table_segments.item(idx, 0).setFlags(Qt.ItemFlag.ItemIsEnabled)
            
            # 1. Spanish segment text (editable)
            text = TextProcessor.remove_punctuation(seg.get("text", ""))
            seg["text"] = text
            self.table_segments.setItem(idx, 1, QTableWidgetItem(text))
            
            # Calculate length and duration dynamically
            length = len(text)
            
            # Determine duration label
            if self.config_manager:
                duration_label = self.config_manager.get_duration_label(length)
                duration_val = self.config_manager.get_duration_for_length(length)
            else:
                if length <= 40:
                    duration_label = "4s"
                    duration_val = 4
                elif length <= 90:
                    duration_label = "6s"
                    duration_val = 6
                elif length <= 130:
                    duration_label = "8s"
                    duration_val = 8
                elif length <= 170:
                    duration_label = "10s"
                    duration_val = 10
                else:
                    duration_label = "超时 (>10s)"
                    duration_val = 10
                    
            seg["duration"] = duration_val
                
            # 2. Length (read-only)
            self.table_segments.setItem(idx, 2, QTableWidgetItem(str(length)))
            self.table_segments.item(idx, 2).setFlags(Qt.ItemFlag.ItemIsEnabled)
            
            # 3. Duration (read-only)
            duration_item = QTableWidgetItem(duration_label)
            duration_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            if "超时" in duration_label:
                duration_item.setForeground(Qt.GlobalColor.red)
            self.table_segments.setItem(idx, 3, duration_item)
            
            # 4. Generated final prompt (read-only, taking segment override or global fallback)
            tpl, motion = self.get_effective_template_and_motion(idx)
            template_content = tpl["content"] if tpl else "{spanish_text}"
            motion_content = motion["content"] if motion else ""
            
            final_prompt = template_content.replace("{spanish_text}", text)
            final_prompt = final_prompt.replace("{camera_motion}", motion_content)
            final_prompt = re.sub(r' +', ' ', final_prompt).strip()
            
            prompt_item = QTableWidgetItem(final_prompt)
            prompt_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table_segments.setItem(idx, 4, prompt_item)
            
            # 5. Single action button (Copy Prompt)
            btn_widget = QWidget()
            btn_layout = QHBoxLayout(btn_widget)
            btn_layout.setContentsMargins(2, 2, 2, 2)
            btn_layout.setSpacing(4)
            
            btn_copy_prompt = QPushButton("🤖 复制提示词")
            btn_copy_prompt.setStyleSheet("padding: 2px 6px; font-size: 11px; font-weight: bold; background-color: #E0A96D; color: white;")
            btn_copy_prompt.clicked.connect(self.copy_segment_prompt)
            
            btn_layout.addWidget(btn_copy_prompt)
            btn_widget.setLayout(btn_layout)
            
            self.table_segments.setCellWidget(idx, 5, btn_widget)
            
        # Apply colors for rows based on whether local video exists on disk
        if not hasattr(self, 'copied_rows'):
            self.copied_rows = set()
        self.copied_rows.clear()
            
        videos_dir = self.project_path / "downloads" / "videos" if self.project_path else Path("downloads/videos")
        for idx, seg in enumerate(segments):
            vid_file = (videos_dir / f"{idx+1:02d}.mp4").resolve()
            if vid_file.exists() and vid_file.stat().st_size > 0:
                seg["copied"] = True
                seg["completed"] = True
                self.copied_rows.add(idx)
                self.change_row_color(idx, copied=True)
            else:
                seg["copied"] = False
                seg["completed"] = False
                self.change_row_color(idx, copied=False)
            
        self.table_segments.blockSignals(False)
        self.filter_segments_table()

    def filter_segments_table(self, query=None):
        """Filters the segments table based on search query in segment text or final prompt."""
        if query is None:
            query = self.txt_search.text() if hasattr(self, 'txt_search') else ""
            
        query = str(query).strip().lower()
        
        for row in range(self.table_segments.rowCount()):
            if not query:
                self.table_segments.setRowHidden(row, False)
                continue
                
            # Column 1: Segment text
            text_item = self.table_segments.item(row, 1)
            text_content = text_item.text().lower() if text_item else ""
            
            # Column 4: Final prompt
            prompt_item = self.table_segments.item(row, 4)
            prompt_content = prompt_item.text().lower() if prompt_item else ""
            
            # Match if query appears in segment text or final prompt
            match = (query in text_content) or (query in prompt_content)
            self.table_segments.setRowHidden(row, not match)

    def on_cell_changed(self, row, column):
        """Saves edited segment text, updates character count, duration and prompt columns in the UI."""
        if column != 1:
            return
            
        text_item = self.table_segments.item(row, 1)
        raw_text = text_item.text().strip() if text_item else ""
        new_text = TextProcessor.remove_punctuation(raw_text)
        
        # Calculate length and duration
        length = len(new_text)
        
        if self.config_manager:
            duration_label = self.config_manager.get_duration_label(length)
            duration_val = self.config_manager.get_duration_for_length(length)
        else:
            if length <= 40:
                duration_label = "4s"
                duration_val = 4
            elif length <= 90:
                duration_label = "6s"
                duration_val = 6
            elif length <= 130:
                duration_label = "8s"
                duration_val = 8
            elif length <= 170:
                duration_label = "10s"
                duration_val = 10
            else:
                duration_label = "超时 (>10s)"
                duration_val = 10
            
        self.table_segments.blockSignals(True)
        
        if new_text != raw_text:
            self.table_segments.setItem(row, 1, QTableWidgetItem(new_text))
            
        # 1. Update length cell
        self.table_segments.setItem(row, 2, QTableWidgetItem(str(length)))
        self.table_segments.item(row, 2).setFlags(Qt.ItemFlag.ItemIsEnabled)
        
        # 2. Update duration cell
        dur_item = QTableWidgetItem(duration_label)
        dur_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        max_limit = self.config_manager.get_max_chars() if self.config_manager else 170
        if length > max_limit:
            dur_item.setForeground(Qt.GlobalColor.red)
        self.table_segments.setItem(row, 3, dur_item)
        
        # 3. Update generated final prompt cell
        tpl, motion = self.get_effective_template_and_motion(row)
        template_content = tpl["content"] if tpl else "{spanish_text}"
        motion_content = motion["content"] if motion else ""
        
        final_prompt = template_content.replace("{spanish_text}", new_text)
        final_prompt = final_prompt.replace("{camera_motion}", motion_content)
        final_prompt = re.sub(r' +', ' ', final_prompt).strip()
        
        prompt_item = QTableWidgetItem(final_prompt)
        prompt_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        self.table_segments.setItem(row, 4, prompt_item)
        
        self.table_segments.blockSignals(False)
        
        # 4. Update in-memory model
        if self.project_model and row < len(self.project_model.spanish_segments):
            self.project_model.spanish_segments[row]["text"] = new_text
            self.project_model.spanish_segments[row]["length"] = length
            self.project_model.spanish_segments[row]["duration"] = duration_val

    def add_segment_row(self):
        """Adds a blank row to the segments table."""
        self.table_segments.blockSignals(True)
        row_idx = self.table_segments.rowCount()
        self.table_segments.insertRow(row_idx)
        
        self.table_segments.setItem(row_idx, 0, QTableWidgetItem(str(row_idx + 1)))
        self.table_segments.item(row_idx, 0).setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.table_segments.setItem(row_idx, 1, QTableWidgetItem(""))
        self.table_segments.setItem(row_idx, 2, QTableWidgetItem("0"))
        self.table_segments.item(row_idx, 2).setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.table_segments.setItem(row_idx, 3, QTableWidgetItem("6s"))
        
        self.table_segments.setItem(row_idx, 4, QTableWidgetItem(""))
        self.table_segments.item(row_idx, 4).setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        
        # Add copy button in Col 5
        btn_widget = QWidget()
        btn_layout = QHBoxLayout(btn_widget)
        btn_layout.setContentsMargins(2, 2, 2, 2)
        btn_layout.setSpacing(4)
        
        btn_copy_prompt = QPushButton("🤖 复制提示词")
        btn_copy_prompt.setStyleSheet("padding: 2px 6px; font-size: 11px; font-weight: bold; background-color: #E0A96D; color: white;")
        btn_copy_prompt.clicked.connect(self.copy_segment_prompt)
        
        btn_layout.addWidget(btn_copy_prompt)
        btn_widget.setLayout(btn_layout)
        
        self.table_segments.setCellWidget(row_idx, 5, btn_widget)
        
        self.table_segments.blockSignals(False)
        
        if self.project_model:
            single_img = self.get_project_single_image()
            self.project_model.spanish_segments.append({
                "text": "",
                "length": 0,
                "duration": 6,
                "image_name": single_img if single_img else "",
                "end_image_name": "",
                "mode": "VIDEO_FRAMES"
            })



    def copy_segment_prompt(self):
        """Copies generated prompt from corresponding row to clipboard."""
        button = self.sender()
        if not button:
            return
            
        target_row = -1
        for row in range(self.table_segments.rowCount()):
            widget = self.table_segments.cellWidget(row, 5)
            if widget and button in widget.findChildren(QPushButton):
                target_row = row
                break
                
        if target_row != -1:
            # Highlight this row programmatically and update property panel
            self.table_segments.selectRow(target_row)
            item = self.table_segments.item(target_row, 0)
            if item:
                self.table_segments.setCurrentItem(item)
                
            prompt_item = self.table_segments.item(target_row, 4)
            if prompt_item:
                prompt_text = prompt_item.text().strip()
                if prompt_text:
                    clipboard = QGuiApplication.clipboard()
                    clipboard.setText(prompt_text)
                    QToolTip.showText(QCursor.pos(), "已复制完整提示词！", self)
                    self.change_row_color(target_row, copied=True)

    def on_cell_double_clicked(self, row, column):
        """Handle double-clicks on the table segments."""
        if column == 3: # Double clicked on "秒数" (Duration) column
            self.change_row_color(row, copied=False)
            return
            
        if column == 4: # Double clicked on "生成的提示词" column
            prompt_item = self.table_segments.item(row, 4)
            if not prompt_item:
                return
                
            prompt_text = prompt_item.text().strip()
            if not prompt_text:
                return
                
            from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QPushButton, QHBoxLayout
            dialog = QDialog(self)
            dialog.setWindowTitle(f"完整提示词 (第 {row + 1} 句)")
            dialog.resize(600, 400)
            
            layout = QVBoxLayout(dialog)
            
            text_edit = QTextEdit()
            text_edit.setPlainText(prompt_text)
            text_edit.setReadOnly(True)
            layout.addWidget(text_edit)
            
            btn_layout = QHBoxLayout()
            btn_layout.addStretch()
            
            btn_copy = QPushButton("📋 复制全部提示词")
            btn_copy.clicked.connect(lambda: self.copy_text_to_clipboard(prompt_text, dialog, row))
            btn_layout.addWidget(btn_copy)
            
            btn_close = QPushButton("关闭")
            btn_close.clicked.connect(dialog.accept)
            btn_layout.addWidget(btn_close)
            
            layout.addLayout(btn_layout)
            
            dialog.setStyleSheet(self.styleSheet())
            dialog.exec()

    def copy_text_to_clipboard(self, text, dialog, row):
        """Utility method to copy text and show tooltip inside dialog context."""
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(text)
        QToolTip.showText(QCursor.pos(), "已复制完整提示词！", dialog)
        self.change_row_color(row, copied=True)

    def change_row_color(self, row, copied=True):
        """Change the background color of a specific row to indicate status."""
        from PyQt6.QtGui import QColor
        if not hasattr(self, 'copied_rows'):
            self.copied_rows = set()
            
        if copied:
            bg_color = QColor("#D4EDDA") # Light green
            text_color = QColor("#155724") # Dark green
            self.copied_rows.add(row)
        else:
            bg_color = QColor()
            text_color = QColor()
            self.copied_rows.discard(row)

        if self.project_model and row < len(self.project_model.spanish_segments):
            self.project_model.spanish_segments[row]["copied"] = copied
            self.project_model.save()

        for col in range(5):
            item = self.table_segments.item(row, col)
            if item:
                if copied:
                    item.setBackground(bg_color)
                    item.setForeground(text_color)
                else:
                    item.setData(Qt.ItemDataRole.BackgroundRole, None)
                    item.setData(Qt.ItemDataRole.ForegroundRole, None)

    def reset_all_segments_completed_state(self):
        """Resets all segments in the current project from completed/green back to uncompleted."""
        if hasattr(self, 'copied_rows'):
            self.copied_rows.clear()
        if hasattr(self, 'dispatched_indices'):
            self.dispatched_indices.clear()

        if self.project_model and self.project_model.spanish_segments:
            for seg in self.project_model.spanish_segments:
                seg["copied"] = False
                seg["completed"] = False
            self.project_model.save()

        self.populate_segments_table()
        QMessageBox.information(self, "重置完成", "✅ 已成功重置所有分句为【未完成状态】！\n\n再次点击分发时，所有浏览器将全量并发重新开刷。")

    def delete_selected_segment(self):
        """Deletes selected row in segments table."""
        selected_rows = self.table_segments.selectedRanges()
        if not selected_rows:
            return
            
        # Delete from bottom to top to avoid offset errors
        rows_to_delete = []
        for r in selected_rows:
            for i in range(r.topRow(), r.bottomRow() + 1):
                rows_to_delete.append(i)
        
        rows_to_delete = sorted(list(set(rows_to_delete)), reverse=True)
        for r in rows_to_delete:
            self.table_segments.removeRow(r)
            if self.project_model and r < len(self.project_model.spanish_segments):
                self.project_model.spanish_segments.pop(r)
            if hasattr(self, 'copied_rows'):
                # Remove this index, and shift all indices greater than r down by 1
                new_copied = set()
                for idx in self.copied_rows:
                    if idx < r:
                        new_copied.add(idx)
                    elif idx > r:
                        new_copied.add(idx - 1)
                self.copied_rows = new_copied
            
        # Recalculate IDs
        self.table_segments.blockSignals(True)
        for idx in range(self.table_segments.rowCount()):
            self.refresh_table_row_index_label(idx)
        self.table_segments.blockSignals(False)

    def run_segmentation(self):
        """Cleans and segments the Spanish text."""
        if not self.project_model:
            return
            
        text = self.txt_spanish.toPlainText()
        if not text.strip():
            QMessageBox.warning(self, "提示", "西班牙语文案为空，请先输入。")
            return
            
        # Perform segmentation
        segments = TextProcessor.segment_spanish_text(text, self.config_manager)
        self.project_model.spanish_segments = segments
        self.populate_segments_table()
        QMessageBox.information(self, "成功", "已完成西文的表情清理与智能切分！")

    def save_project_data(self):
        """Saves text changes and segments back to metadata.json."""
        if not self.project_model:
            return
            
        # 1. Update basic texts
        self.project_model.chinese_text = self.txt_chinese.toPlainText()
        self.project_model.spanish_text = self.txt_spanish.toPlainText()
        self.project_model.google_drive_url = self.txt_gdrive_url.toPlainText().strip()
        
        # 2. Update segments from table in-place to preserve other properties (image_name, mode)
        for row in range(self.table_segments.rowCount()):
            text_item = self.table_segments.item(row, 1)
            duration_item = self.table_segments.item(row, 3)
            
            raw_text = text_item.text().strip() if text_item else ""
            text = TextProcessor.remove_punctuation(raw_text)
            dur_str = duration_item.text().strip().replace("s", "") if duration_item else "6"
            try:
                duration = int(dur_str)
            except ValueError:
                duration = 6
                
            if row < len(self.project_model.spanish_segments):
                self.project_model.spanish_segments[row]["text"] = text
                self.project_model.spanish_segments[row]["length"] = len(text)
                self.project_model.spanish_segments[row]["duration"] = duration
            else:
                self.project_model.spanish_segments.append({
                    "text": text,
                    "length": len(text),
                    "duration": duration,
                    "image_name": "",
                    "end_image_name": "",
                    "mode": "VIDEO_FRAMES"
                })
                
        # Truncate model segments to match table row count if needed
        if len(self.project_model.spanish_segments) > self.table_segments.rowCount():
            self.project_model.spanish_segments = self.project_model.spanish_segments[:self.table_segments.rowCount()]
        
        # 3. Save to disk
        if self.project_model.save():
            QMessageBox.information(self, "成功", "工程文案与配置保存成功！")
        else:
            QMessageBox.critical(self, "错误", "工程保存失败，请检查写入权限。")

    def open_project_folder(self):
        """Opens project folder in system file explorer."""
        if self.project_path and self.project_path.exists():
            QDesktopServices.openUrl(QUrl(self.project_path.as_uri()))

    def start_download(self):
        """Starts background download of Google Drive link by delegating to MainWindow."""
        url = self.txt_gdrive_url.toPlainText().strip()
        if not url:
            QMessageBox.warning(self, "错误", "谷歌云盘链接为空，无法下载。")
            return
            
        main_win = self.window()
        if hasattr(main_win, "active_downloads") and self.project_model.project_id in main_win.active_downloads:
            QMessageBox.warning(self, "提示", "该项目的下载任务已在后台运行中，请等待完成。")
            return
            
        if hasattr(main_win, "start_background_download"):
            self.btn_download.setEnabled(False)
            self.lbl_download_status.setText("下载状态: 初始化中...")
            main_win.start_background_download(self.project_model.project_id, url, self.project_path)
        else:
            # Fallback if window is not initialized
            downloads_dir = self.project_path / "downloads"
            self.btn_download.setEnabled(False)
            self.lbl_download_status.setText("下载状态: 初始化中...")
            if hasattr(self, "download_thread") and self.download_thread:
                try:
                    if self.download_thread.isRunning():
                        self.download_thread.stop()
                except Exception:
                    pass
                self.download_thread = None
            self.download_thread = DownloadThread(url, downloads_dir)
            self.download_thread.status_signal.connect(self.on_download_status_updated)
            self.download_thread.finished_signal.connect(self.on_download_finished)
            self.download_thread.finished_signal.connect(self.download_thread.deleteLater)
            self.download_thread.start()

    def on_download_status_updated(self, msg):
        self.lbl_download_status.setText(f"下载状态: {msg}")

    def on_download_finished(self, success, msg):
        self.btn_download.setEnabled(True)
        if success:
            self.lbl_download_status.setText("下载状态: 下载完成！")
            QMessageBox.information(self, "下载完成", msg)
        else:
            self.lbl_download_status.setText(f"下载状态: 下载失败 - {msg}")
            QMessageBox.critical(self, "下载失败", msg)
            
        # Refresh local files list
        self.refresh_media_list()
        
        # Update metadata.json list
        if self.project_model:
            self.project_model.update_media_files()
            if success:
                self.populate_segments_table()

    def refresh_media_list(self):
        """Populates list_media with files inside project_dir/downloads."""
        self.list_media.clear()
        if not self.project_path:
            return
            
        downloads_dir = self.project_path / "downloads"
        if downloads_dir.exists():
            from services.downloader import ensure_unique_stems_in_dir
            ensure_unique_stems_in_dir(downloads_dir)
            for item in downloads_dir.iterdir():
                if item.is_file():
                    # Display filename and file size in KB
                    size_kb = item.stat().st_size / 1024
                    list_item = QListWidgetItem(f"{item.name} ({size_kb:.1f} KB)")
                    list_item.setData(Qt.ItemDataRole.UserRole, item.name)
                    self.list_media.addItem(list_item)
                    
        # Refresh combo_prop_image dropdown in property panel
        if hasattr(self, "combo_prop_image"):
            self.refresh_prop_image_combo_items()

    def open_media_file(self, qmodelindex):
        """Double click handler to open the media file with default system player/viewer."""
        current_item = self.list_media.currentItem()
        if not current_item:
            return
        filename = current_item.data(Qt.ItemDataRole.UserRole)
        if not filename:
            return
        file_path = self.project_path / "downloads" / filename
        
        if file_path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(file_path.resolve())))

    def on_media_selection_changed(self, current, previous):
        """Displays a preview of the selected image on the right side."""
        if not current:
            self.lbl_preview.clear()
            self.lbl_preview.setText("选择左侧素材以预览...")
            return
            
        filename = current.data(Qt.ItemDataRole.UserRole)
        if not filename:
            self.lbl_preview.clear()
            self.lbl_preview.setText("无有效文件名")
            return
            
        file_path = self.project_path / "downloads" / filename
        
        if file_path.exists():
            pixmap = QPixmap()
            # 1. Use Pillow to load image (handles JPEG/PNG/WEBP/GIF with 100% reliability, bypassing Qt C++ plugins)
            try:
                from PIL import Image
                from PyQt6.QtGui import QImage
                
                pil_img = Image.open(file_path)
                # Convert to RGBA format for safe rendering in Qt
                pil_img_rgba = pil_img.convert("RGBA")
                width, height = pil_img_rgba.size
                
                # Convert PIL image bytes directly to QImage
                raw_data = pil_img_rgba.tobytes("raw", "RGBA")
                # QImage requires a reference to the bytes data to stay alive, or we copy it using .copy()
                qimg = QImage(raw_data, width, height, QImage.Format.Format_RGBA8888).copy()
                
                pixmap = QPixmap.fromImage(qimg)
            except Exception as e:
                print(f"Pillow load failed: {e}. Trying fallback direct loading...")
                # 2. Fallback to direct loading
                try:
                    with open(file_path, "rb") as f:
                        img_data = f.read()
                    pixmap = QPixmap()
                    pixmap.loadFromData(img_data)
                except Exception as fallback_err:
                    print(f"Fallback direct loading failed: {fallback_err}")
                    pixmap = QPixmap()
                
            if not pixmap.isNull():
                # Prevent negative or zero scaling size
                w = max(100, self.lbl_preview.width() - 12)
                h = max(100, self.lbl_preview.height() - 12)
                
                # Scale the image to fit the label, keeping aspect ratio
                scaled_pixmap = pixmap.scaled(
                    w, h,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                self.lbl_preview.setPixmap(scaled_pixmap)
            else:
                self.lbl_preview.clear()
                self.lbl_preview.setText("无法预览此文件格式")
        else:
            self.lbl_preview.clear()
            self.lbl_preview.setText("文件不存在")

    def refresh_template_comboboxes(self):
        """Loads prompt templates and motions lists into dropdown selectors."""
        if not self.template_manager:
            return
            
        self.combo_templates.blockSignals(True)
        self.combo_motions.blockSignals(True)
        
        self.combo_templates.clear()
        self.combo_motions.clear()
        
        self.combo_templates.addItem("-- 请选择提示词模板 --", "")
        self.combo_motions.addItem("-- 请选择运镜预设 --", "")
        
        for t in self.template_manager.templates:
            self.combo_templates.addItem(t["name"], t["id"])
        for m in self.template_manager.motions:
            self.combo_motions.addItem(m["name"], m["id"])
            
        if self.project_model:
            tpl_idx = self.combo_templates.findData(self.project_model.selected_template_id)
            if tpl_idx >= 0:
                self.combo_templates.setCurrentIndex(tpl_idx)
            else:
                self.combo_templates.setCurrentIndex(0)
                
            motion_idx = self.combo_motions.findData(self.project_model.selected_motion_id)
            if motion_idx >= 0:
                self.combo_motions.setCurrentIndex(motion_idx)
            else:
                self.combo_motions.setCurrentIndex(0)
                
        self.combo_templates.blockSignals(False)
        self.combo_motions.blockSignals(False)
        
        self.populate_segments_table()

    def on_template_changed(self):
        if not self.project_model:
            return
        tpl_id = self.combo_templates.currentData()
        self.project_model.selected_template_id = tpl_id if tpl_id else ""
        self.project_model.save()
        self.refresh_prop_template_motion_combos()
        self.populate_segments_table()

    def on_motion_changed(self):
        if not self.project_model:
            return
        motion_id = self.combo_motions.currentData()
        self.project_model.selected_motion_id = motion_id if motion_id else ""
        self.project_model.save()
        self.refresh_prop_template_motion_combos()
        self.populate_segments_table()

    def init_property_panel(self):
        panel_layout = QVBoxLayout(self.property_panel)
        panel_layout.setContentsMargins(10, 0, 10, 0)
        panel_layout.setSpacing(10)
        
        # Title and End Frame Toggle Row
        title_row = QHBoxLayout()
        lbl_title = QLabel("⚙️ 片段属性配置")
        lbl_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #5D4037;")
        title_row.addWidget(lbl_title)
        title_row.addStretch()
        
        self.chk_enable_end_frame = QCheckBox("启用尾帧")
        self.chk_enable_end_frame.setToolTip("开启后，支持为每句配置尾帧，并将尾帧自动联动为下一句的首帧。")
        self.chk_enable_end_frame.setStyleSheet("font-size: 12px; color: #5D4037; font-weight: bold;")
        self.chk_enable_end_frame.toggled.connect(self.on_enable_end_frame_toggled)
        title_row.addWidget(self.chk_enable_end_frame)
        panel_layout.addLayout(title_row)
        
        # Separator line
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        line.setStyleSheet("color: #D7CCC8;")
        panel_layout.addWidget(line)
        
        # Selected Segment Info
        self.lbl_prop_index = QLabel("当前句：无选择")
        self.lbl_prop_index.setStyleSheet("color: #8D6E63; font-weight: bold;")
        panel_layout.addWidget(self.lbl_prop_index)
        
        self.txt_prop_text = QTextEdit()
        self.txt_prop_text.setReadOnly(True)
        self.txt_prop_text.setMaximumHeight(80)
        self.txt_prop_text.setStyleSheet("""
            QTextEdit {
                background-color: #F5F5F5;
                color: #5D4037;
                border: 1px solid #E0D7D3;
                font-size: 12px;
            }
        """)
        panel_layout.addWidget(self.txt_prop_text)
        
        # 1. First Image selector
        self.lbl_prop_first_image = QLabel("📸 首帧图片素材:")
        panel_layout.addWidget(self.lbl_prop_first_image)
        self.combo_prop_image = QComboBox()
        self.combo_prop_image.setMaxVisibleItems(15)
        self.combo_prop_image.view().setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.combo_prop_image.setStyleSheet("""
            QComboBox {
                background-color: white;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QComboBox QAbstractItemView {
                border: 1px solid #D7CCC8;
                background-color: white;
                selection-background-color: #FFE0B2;
                selection-color: #5D4037;
                outline: none;
            }
        """)
        self.combo_prop_image.currentIndexChanged.connect(self.on_prop_image_changed)
        panel_layout.addWidget(self.combo_prop_image)
        
        # First Image preview
        self.lbl_prop_preview = QLabel("无首帧预览")
        self.lbl_prop_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_prop_preview.setMinimumHeight(120)
        self.lbl_prop_preview.setMaximumHeight(160)
        self.lbl_prop_preview.setStyleSheet("""
            QLabel {
                background-color: #EFEBE9;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                color: #8D6E63;
                font-size: 11px;
                font-weight: normal;
            }
        """)
        panel_layout.addWidget(self.lbl_prop_preview)
        
        # 2. End Image selector & preview (in togglable container)
        self.container_end_image = QWidget()
        end_img_layout = QVBoxLayout(self.container_end_image)
        end_img_layout.setContentsMargins(0, 0, 0, 0)
        end_img_layout.setSpacing(6)
        
        self.lbl_prop_end_image = QLabel("🎬 尾帧图片素材 (下一句首帧自动跟随):")
        end_img_layout.addWidget(self.lbl_prop_end_image)
        
        self.combo_prop_end_image = QComboBox()
        self.combo_prop_end_image.setMaxVisibleItems(15)
        self.combo_prop_end_image.view().setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.combo_prop_end_image.setStyleSheet("""
            QComboBox {
                background-color: white;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QComboBox QAbstractItemView {
                border: 1px solid #D7CCC8;
                background-color: white;
                selection-background-color: #FFE0B2;
                selection-color: #5D4037;
                outline: none;
            }
        """)
        self.combo_prop_end_image.currentIndexChanged.connect(self.on_prop_end_image_changed)
        end_img_layout.addWidget(self.combo_prop_end_image)
        
        self.lbl_prop_end_preview = QLabel("无尾帧预览")
        self.lbl_prop_end_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_prop_end_preview.setMinimumHeight(120)
        self.lbl_prop_end_preview.setMaximumHeight(160)
        self.lbl_prop_end_preview.setStyleSheet("""
            QLabel {
                background-color: #EFEBE9;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                color: #8D6E63;
                font-size: 11px;
                font-weight: normal;
            }
        """)
        end_img_layout.addWidget(self.lbl_prop_end_preview)
        
        panel_layout.addWidget(self.container_end_image)
        self.container_end_image.setVisible(self.enable_end_frame)
        
        # Segment-specific template selector
        panel_layout.addWidget(QLabel("📐 片段专属模板:"))
        self.combo_prop_template = QComboBox()
        self.combo_prop_template.setMaxVisibleItems(15)
        self.combo_prop_template.view().setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.combo_prop_template.setStyleSheet("""
            QComboBox {
                background-color: white;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QComboBox QAbstractItemView {
                border: 1px solid #D7CCC8;
                background-color: white;
                selection-background-color: #FFE0B2;
                selection-color: #5D4037;
                outline: none;
            }
        """)
        self.combo_prop_template.currentIndexChanged.connect(self.on_prop_template_changed)
        panel_layout.addWidget(self.combo_prop_template)
        
        # Segment-specific motion selector
        panel_layout.addWidget(QLabel("🎥 片段专属运镜:"))
        self.combo_prop_motion = QComboBox()
        self.combo_prop_motion.setMaxVisibleItems(15)
        self.combo_prop_motion.view().setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.combo_prop_motion.setStyleSheet("""
            QComboBox {
                background-color: white;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QComboBox QAbstractItemView {
                border: 1px solid #D7CCC8;
                background-color: white;
                selection-background-color: #FFE0B2;
                selection-color: #5D4037;
                outline: none;
            }
        """)
        self.combo_prop_motion.currentIndexChanged.connect(self.on_prop_motion_changed)
        panel_layout.addWidget(self.combo_prop_motion)

        # Mode selector
        panel_layout.addWidget(QLabel("⚙️ 生成模式:"))
        self.combo_prop_mode = QComboBox()
        self.combo_prop_mode.addItem("帧模式 (First Frame)", "VIDEO_FRAMES")
        self.combo_prop_mode.addItem("素材模式 (Reference)", "VIDEO_REFERENCES")
        self.combo_prop_mode.currentIndexChanged.connect(self.on_prop_mode_changed)
        panel_layout.addWidget(self.combo_prop_mode)
        
        panel_layout.addStretch()
        
        # Disable properties by default until a row is selected
        self.property_panel.setEnabled(False)

    def on_enable_end_frame_toggled(self, checked):
        """Toggles end frame capability for current project."""
        self.enable_end_frame = checked
        if self.project_model:
            self.project_model.enable_end_frame = checked
            self.project_model.save()
        if hasattr(self, "container_end_image"):
            self.container_end_image.setVisible(checked)
        # Refresh all row index labels in table to update 🎬 emojis
        for r in range(self.table_segments.rowCount()):
            self.refresh_table_row_index_label(r)

    def resolve_segment_image_and_data(self, idx, seg):
        """
        智能解析分句关联的图片文件名、绝对路径以及 Base64 Data URL：
        1. 优先检查 seg 中显式绑定的 image_name 是否真实存在于 downloads/；
        2. 按分句序号智能精准匹配 downloads/ 下的文件（如 01.png, 01.jpg, 1.png, 1.jpg, 01_*.png 等）；
        3. 若工程内仅有 1 张图片，所有分句自动共用该图片；
        4. 若工程内有多张图片，按文件名升序排序后，自动关联第 idx 张；
        5. 若图片数量少于分句数，循环取模取用或使用首张；
        6. 自动将图片文件读取并编码为 base64 data url (如 data:image/png;base64,xxxx)，确保浏览器能 100% 自动上传！
        """
        if not self.project_path:
            return "", "", ""

        downloads_dir = self.project_path / "downloads"
        if not downloads_dir.exists():
            return "", "", ""

        img_extensions = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
        try:
            all_imgs = [item for item in downloads_dir.iterdir() if item.is_file() and item.suffix.lower() in img_extensions]
            all_imgs.sort(key=lambda x: x.name)
        except Exception:
            return "", "", ""

        if not all_imgs:
            return "", "", ""

        chosen_img_obj = None

        # 1. 优先检查 seg 中的显式绑定
        explicit_name = seg.get("image_name", "").strip() if isinstance(seg, dict) else ""
        if explicit_name:
            cand = downloads_dir / explicit_name
            if cand.exists() and cand.is_file():
                chosen_img_obj = cand

        # 2. 按序号匹配 (1.jpg, 01.jpg, 1_*.jpg 等)
        if not chosen_img_obj:
            idx_str1 = f"{idx + 1}"
            idx_str2 = f"{idx + 1:02d}"
            for img in all_imgs:
                stem = img.stem
                if stem == idx_str1 or stem == idx_str2 or stem.startswith(f"{idx_str1}_") or stem.startswith(f"{idx_str2}_") or stem.startswith(f"{idx_str1}-") or stem.startswith(f"{idx_str2}-"):
                    chosen_img_obj = img
                    break

        # 3. 若只有 1 张图片，全工程共用
        if not chosen_img_obj and len(all_imgs) == 1:
            chosen_img_obj = all_imgs[0]

        # 4. 若有多张图片，按顺序对齐第 idx 张（若超出则取模或首张）
        if not chosen_img_obj:
            if idx < len(all_imgs):
                chosen_img_obj = all_imgs[idx]
            else:
                chosen_img_obj = all_imgs[idx % len(all_imgs)]

        if not chosen_img_obj or not chosen_img_obj.exists():
            return "", "", ""

        chosen_name = chosen_img_obj.name
        chosen_path = str(chosen_img_obj.resolve())

        # 5. 编码为 Base64 Data URL
        import base64
        import mimetypes
        mime_type, _ = mimetypes.guess_type(chosen_path)
        if not mime_type:
            mime_type = "image/png"

        data_url = ""
        try:
            with open(chosen_img_obj, "rb") as f:
                b64_str = base64.b64encode(f.read()).decode("utf-8")
                data_url = f"data:{mime_type};base64,{b64_str}"
        except Exception as e:
            logger.warning(f"读取图片 Base64 失败 [{chosen_name}]: {e}")

        # 同步回写进 seg 中
        if isinstance(seg, dict):
            seg["image_name"] = chosen_name

        return chosen_name, chosen_path, data_url

    def resolve_segment_end_image_and_data(self, idx, seg):
        """
        解析分句关联的尾帧图片文件名、绝对路径以及 Base64 Data URL：
        1. 仅当启用尾帧功能时生效；
        2. 检查 seg 中显式绑定的 end_image_name 是否真实存在于 downloads/；
        3. 若存在，自动读取并编码为 base64 data url；
        4. 若未开启或未指定，返回 ("", "", "")。
        """
        if not getattr(self, "enable_end_frame", False) or not self.project_path:
            return "", "", ""

        downloads_dir = self.project_path / "downloads"
        if not downloads_dir.exists():
            return "", "", ""

        end_name = seg.get("end_image_name", "").strip() if isinstance(seg, dict) else ""
        if not end_name:
            return "", "", ""

        cand = downloads_dir / end_name
        if not cand.exists() or not cand.is_file():
            return "", "", ""

        end_path = str(cand.resolve())

        import base64
        import mimetypes
        mime_type, _ = mimetypes.guess_type(end_path)
        if not mime_type:
            mime_type = "image/png"

        data_url = ""
        try:
            with open(cand, "rb") as f:
                b64_str = base64.b64encode(f.read()).decode("utf-8")
                data_url = f"data:{mime_type};base64,{b64_str}"
        except Exception as e:
            logger.warning(f"读取尾帧图片 Base64 失败 [{end_name}]: {e}")

        return end_name, end_path, data_url

    def get_project_single_image(self):
        """Returns the filename of the single image in downloads directory, or None if 0 or >1 images."""
        if not self.project_path:
            return None
        downloads_dir = self.project_path / "downloads"
        if not downloads_dir.exists():
            return None
        img_extensions = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
        try:
            images = [item.name for item in downloads_dir.iterdir() if item.is_file() and item.suffix.lower() in img_extensions]
            if len(images) == 1:
                return images[0]
        except Exception:
            pass
        return None

    def on_table_selection_changed(self, current, previous):
        if not self.project_model or current is None:
            self.current_prop_row = -1
            self.lbl_prop_index.setText("当前句：无选择")
            self.txt_prop_text.clear()
            self.combo_prop_image.blockSignals(True)
            self.combo_prop_image.setCurrentIndex(0)
            self.combo_prop_image.blockSignals(False)
            if hasattr(self, "combo_prop_end_image"):
                self.combo_prop_end_image.blockSignals(True)
                self.combo_prop_end_image.setCurrentIndex(0)
                self.combo_prop_end_image.blockSignals(False)
            if hasattr(self, "lbl_prop_end_preview"):
                self.lbl_prop_end_preview.clear()
                self.lbl_prop_end_preview.setText("无尾帧预览")
            self.combo_prop_template.blockSignals(True)
            self.combo_prop_template.setCurrentIndex(0)
            self.combo_prop_template.blockSignals(False)
            self.combo_prop_motion.blockSignals(True)
            self.combo_prop_motion.setCurrentIndex(0)
            self.combo_prop_motion.blockSignals(False)
            self.lbl_prop_preview.clear()
            self.lbl_prop_preview.setText("无首帧预览")
            self.combo_prop_mode.blockSignals(True)
            self.combo_prop_mode.setCurrentIndex(0)
            self.combo_prop_mode.blockSignals(False)
            self.property_panel.setEnabled(False)
            return
            
        row = current.row()
        if row < 0 or row >= len(self.project_model.spanish_segments):
            self.current_prop_row = -1
            self.property_panel.setEnabled(False)
            return
            
        self.current_prop_row = row
        self.property_panel.setEnabled(True)
        
        # Block signals to prevent infinite update loop
        self.combo_prop_image.blockSignals(True)
        if hasattr(self, "combo_prop_end_image"):
            self.combo_prop_end_image.blockSignals(True)
        self.combo_prop_template.blockSignals(True)
        self.combo_prop_motion.blockSignals(True)
        self.combo_prop_mode.blockSignals(True)
        
        # Populate selected segment data
        seg = self.project_model.spanish_segments[row]
        self.lbl_prop_index.setText(f"当前句：第 {row + 1} 句")
        self.txt_prop_text.setPlainText(seg.get("text", ""))
        
        # Refresh combo lists & placeholders
        self.refresh_prop_image_combo_items()
        self.refresh_prop_template_motion_combos()
        
        # Select current image (首帧)
        image_name = seg.get("image_name", "")
        img_idx = self.combo_prop_image.findData(image_name)
        if img_idx >= 0:
            self.combo_prop_image.setCurrentIndex(img_idx)
        else:
            self.combo_prop_image.setCurrentIndex(0)

        # Select current end image (尾帧)
        end_image_name = seg.get("end_image_name", "")
        if hasattr(self, "combo_prop_end_image"):
            end_img_idx = self.combo_prop_end_image.findData(end_image_name)
            if end_img_idx >= 0:
                self.combo_prop_end_image.setCurrentIndex(end_img_idx)
            else:
                self.combo_prop_end_image.setCurrentIndex(0)

        # Select current segment template
        seg_tpl_id = seg.get("template_id", "")
        tpl_idx = self.combo_prop_template.findData(seg_tpl_id)
        if tpl_idx >= 0:
            self.combo_prop_template.setCurrentIndex(tpl_idx)
        else:
            self.combo_prop_template.setCurrentIndex(0)
            
        # Select current segment motion
        seg_motion_id = seg.get("motion_id", "")
        motion_idx = self.combo_prop_motion.findData(seg_motion_id)
        if motion_idx >= 0:
            self.combo_prop_motion.setCurrentIndex(motion_idx)
        else:
            self.combo_prop_motion.setCurrentIndex(0)
            
        # Select current mode
        mode = seg.get("mode", "VIDEO_FRAMES")
        mode_idx = self.combo_prop_mode.findData(mode)
        if mode_idx >= 0:
            self.combo_prop_mode.setCurrentIndex(mode_idx)
        else:
            self.combo_prop_mode.setCurrentIndex(0)
            
        # Update preview
        self.update_prop_image_preview(image_name)
        if hasattr(self, "update_prop_end_image_preview"):
            self.update_prop_end_image_preview(end_image_name)
        
        self.combo_prop_image.blockSignals(False)
        if hasattr(self, "combo_prop_end_image"):
            self.combo_prop_end_image.blockSignals(False)
        self.combo_prop_template.blockSignals(False)
        self.combo_prop_motion.blockSignals(False)
        self.combo_prop_mode.blockSignals(False)

    def refresh_prop_image_combo_items(self):
        self.combo_prop_image.blockSignals(True)
        if hasattr(self, "combo_prop_end_image"):
            self.combo_prop_end_image.blockSignals(True)
            
        current_data = self.combo_prop_image.currentData()
        current_end_data = self.combo_prop_end_image.currentData() if hasattr(self, "combo_prop_end_image") else None
        
        self.combo_prop_image.clear()
        self.combo_prop_image.addItem("-- 无首帧 --", "")
        
        if hasattr(self, "combo_prop_end_image"):
            self.combo_prop_end_image.clear()
            self.combo_prop_end_image.addItem("-- 无尾帧 --", "")
        
        if self.project_path:
            downloads_dir = self.project_path / "downloads"
            if downloads_dir.exists():
                # Supported image extensions
                img_extensions = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
                for item in sorted(downloads_dir.iterdir()):
                    if item.is_file() and item.suffix.lower() in img_extensions:
                        # Add item with a small icon preview!
                        icon = self.get_small_image_icon(item)
                        self.combo_prop_image.addItem(icon, item.name, item.name)
                        if hasattr(self, "combo_prop_end_image"):
                            self.combo_prop_end_image.addItem(icon, item.name, item.name)
                        
        # Restore index if it was previously set
        if current_data:
            idx = self.combo_prop_image.findData(current_data)
            if idx >= 0:
                self.combo_prop_image.setCurrentIndex(idx)
        if current_end_data and hasattr(self, "combo_prop_end_image"):
            idx_end = self.combo_prop_end_image.findData(current_end_data)
            if idx_end >= 0:
                self.combo_prop_end_image.setCurrentIndex(idx_end)
                
        self.combo_prop_image.blockSignals(False)
        if hasattr(self, "combo_prop_end_image"):
            self.combo_prop_end_image.blockSignals(False)

    def get_small_image_icon(self, file_path):
        from PyQt6.QtGui import QIcon, QImage, QPixmap
        try:
            from PIL import Image
            # Use PIL to read image and scale it to a small thumbnail, e.g. 24x24 px
            pil_img = Image.open(file_path)
            pil_img.thumbnail((24, 24))
            pil_img_rgba = pil_img.convert("RGBA")
            width, height = pil_img_rgba.size
            raw_data = pil_img_rgba.tobytes("raw", "RGBA")
            qimg = QImage(raw_data, width, height, QImage.Format.Format_RGBA8888).copy()
            pixmap = QPixmap.fromImage(qimg)
            return QIcon(pixmap)
        except Exception:
            return QIcon()

    def update_prop_image_preview(self, image_name):
        if not image_name:
            self.lbl_prop_preview.clear()
            self.lbl_prop_preview.setText("无首帧")
            return
            
        file_path = self.project_path / "downloads" / image_name
        if not file_path.exists():
            self.lbl_prop_preview.clear()
            self.lbl_prop_preview.setText("图片不存在")
            return
            
        try:
            from PIL import Image
            from PyQt6.QtGui import QImage, QPixmap
            pil_img = Image.open(file_path)
            pil_img.thumbnail((220, 150))
            pil_img_rgba = pil_img.convert("RGBA")
            width, height = pil_img_rgba.size
            raw_data = pil_img_rgba.tobytes("raw", "RGBA")
            qimg = QImage(raw_data, width, height, QImage.Format.Format_RGBA8888).copy()
            pixmap = QPixmap.fromImage(qimg)
            self.lbl_prop_preview.setPixmap(pixmap)
        except Exception as e:
            print(f"Error loading preview: {e}")
            self.lbl_prop_preview.clear()
            self.lbl_prop_preview.setText("预览失败")

    def update_prop_end_image_preview(self, image_name):
        if not hasattr(self, "lbl_prop_end_preview"):
            return
        if not image_name:
            self.lbl_prop_end_preview.clear()
            self.lbl_prop_end_preview.setText("无尾帧")
            return
            
        file_path = self.project_path / "downloads" / image_name
        if not file_path.exists():
            self.lbl_prop_end_preview.clear()
            self.lbl_prop_end_preview.setText("图片不存在")
            return
            
        try:
            from PIL import Image
            from PyQt6.QtGui import QImage, QPixmap
            pil_img = Image.open(file_path)
            pil_img.thumbnail((220, 150))
            pil_img_rgba = pil_img.convert("RGBA")
            width, height = pil_img_rgba.size
            raw_data = pil_img_rgba.tobytes("raw", "RGBA")
            qimg = QImage(raw_data, width, height, QImage.Format.Format_RGBA8888).copy()
            pixmap = QPixmap.fromImage(qimg)
            self.lbl_prop_end_preview.setPixmap(pixmap)
        except Exception as e:
            print(f"Error loading end preview: {e}")
            self.lbl_prop_end_preview.clear()
            self.lbl_prop_end_preview.setText("预览失败")

    def on_prop_image_changed(self):
        row = getattr(self, "current_prop_row", -1)
        if row < 0 or not self.project_model or row >= len(self.project_model.spanish_segments):
            return
            
        image_name = self.combo_prop_image.currentData()
        self.project_model.spanish_segments[row]["image_name"] = image_name if image_name else ""
        
        # Update large preview
        self.update_prop_image_preview(image_name)
        
        # Refresh the index cell text to display the camera emoji if selected
        self.refresh_table_row_index_label(row)

    def on_prop_end_image_changed(self):
        row = getattr(self, "current_prop_row", -1)
        if row < 0 or not self.project_model or row >= len(self.project_model.spanish_segments):
            return
            
        end_image_name = self.combo_prop_end_image.currentData() if hasattr(self, "combo_prop_end_image") else ""
        self.project_model.spanish_segments[row]["end_image_name"] = end_image_name if end_image_name else ""
        
        # Update large preview
        self.update_prop_end_image_preview(end_image_name)
        
        # 联动逻辑：若当前启用了尾帧，且当前句设置了有效的尾帧图片，
        # 则自动将下一句（第 row + 2 句）的首帧设置为该尾帧图片！
        if getattr(self, "enable_end_frame", False) and end_image_name:
            next_row = row + 1
            if next_row < len(self.project_model.spanish_segments):
                self.project_model.spanish_segments[next_row]["image_name"] = end_image_name
                self.refresh_table_row_index_label(next_row)
                
        # 刷新当前行图标与保存
        self.refresh_table_row_index_label(row)
        self.project_model.save()

    def on_prop_mode_changed(self):
        row = getattr(self, "current_prop_row", -1)
        if row < 0 or not self.project_model or row >= len(self.project_model.spanish_segments):
            return
            
        mode = self.combo_prop_mode.currentData()
        self.project_model.spanish_segments[row]["mode"] = mode if mode else "VIDEO_FRAMES"

    def refresh_table_row_index_label(self, row):
        if not self.project_model or row < 0 or row >= len(self.project_model.spanish_segments):
            return
        seg = self.project_model.spanish_segments[row]
        has_image = bool(seg.get("image_name"))
        has_end_image = bool(seg.get("end_image_name")) if getattr(self, "enable_end_frame", False) else False
        has_custom = bool(seg.get("template_id")) or bool(seg.get("motion_id"))
        index_label = str(row + 1)
        if has_image:
            index_label += " 📷"
        if has_end_image:
            index_label += " 🎬"
        if has_custom:
            index_label += " ⚙️"
        
        self.table_segments.blockSignals(True)
        item = self.table_segments.item(row, 0)
        if item:
            item.setText(index_label)
        self.table_segments.blockSignals(False)

    def get_effective_template_and_motion(self, row):
        """Returns (tpl, motion) dicts for specified row, resolving segment overrides or global fallbacks."""
        if not self.project_model or not self.template_manager:
            return None, None
        if row < 0 or row >= len(self.project_model.spanish_segments):
            return None, None
            
        seg = self.project_model.spanish_segments[row]
        
        # 1. Template resolution
        tpl_id = seg.get("template_id", "")
        if not tpl_id:
            tpl_id = self.combo_templates.currentData()
        tpl = self.template_manager.get_template(tpl_id)
        
        # 2. Motion resolution
        motion_id = seg.get("motion_id", "")
        if not motion_id:
            motion_id = self.combo_motions.currentData()
        motion = self.template_manager.get_motion(motion_id)
        
        return tpl, motion

    def refresh_prop_template_motion_combos(self):
        """Populates the property panel template and motion dropdowns with dynamic fallback label."""
        if not hasattr(self, "combo_prop_template") or not self.template_manager:
            return
            
        self.combo_prop_template.blockSignals(True)
        self.combo_prop_motion.blockSignals(True)
        
        current_tpl = self.combo_prop_template.currentData()
        current_motion = self.combo_prop_motion.currentData()
        
        self.combo_prop_template.clear()
        self.combo_prop_motion.clear()
        
        # Get current global names for default item text
        global_tpl_id = self.combo_templates.currentData()
        global_tpl = self.template_manager.get_template(global_tpl_id)
        global_tpl_name = global_tpl["name"] if global_tpl else "未选择"
        
        global_motion_id = self.combo_motions.currentData()
        global_motion = self.template_manager.get_motion(global_motion_id)
        global_motion_name = global_motion["name"] if global_motion else "未选择"
        
        self.combo_prop_template.addItem(f"-- 遵循统一设置 ({global_tpl_name}) --", "")
        self.combo_prop_motion.addItem(f"-- 遵循统一设置 ({global_motion_name}) --", "")
        
        for t in self.template_manager.templates:
            self.combo_prop_template.addItem(t["name"], t["id"])
        for m in self.template_manager.motions:
            self.combo_prop_motion.addItem(m["name"], m["id"])
            
        if current_tpl:
            idx = self.combo_prop_template.findData(current_tpl)
            if idx >= 0:
                self.combo_prop_template.setCurrentIndex(idx)
        if current_motion:
            idx = self.combo_prop_motion.findData(current_motion)
            if idx >= 0:
                self.combo_prop_motion.setCurrentIndex(idx)
                
        self.combo_prop_template.blockSignals(False)
        self.combo_prop_motion.blockSignals(False)

    def on_prop_template_changed(self):
        row = getattr(self, "current_prop_row", -1)
        if row < 0 or not self.project_model or row >= len(self.project_model.spanish_segments):
            return
            
        tpl_id = self.combo_prop_template.currentData()
        self.project_model.spanish_segments[row]["template_id"] = tpl_id if tpl_id else ""
        self.update_segment_row_prompt(row)
        self.project_model.save()

    def on_prop_motion_changed(self):
        row = getattr(self, "current_prop_row", -1)
        if row < 0 or not self.project_model or row >= len(self.project_model.spanish_segments):
            return
            
        motion_id = self.combo_prop_motion.currentData()
        self.project_model.spanish_segments[row]["motion_id"] = motion_id if motion_id else ""
        self.update_segment_row_prompt(row)
        self.project_model.save()

    def update_segment_row_prompt(self, row):
        """Re-computes prompt and updates cell items for a specific segment row."""
        if not self.project_model or row < 0 or row >= self.table_segments.rowCount():
            return
            
        if row >= len(self.project_model.spanish_segments):
            return
            
        seg = self.project_model.spanish_segments[row]
        text_item = self.table_segments.item(row, 1)
        raw_text = text_item.text().strip() if text_item else seg.get("text", "")
        text = TextProcessor.remove_punctuation(raw_text)
        
        tpl, motion = self.get_effective_template_and_motion(row)
        template_content = tpl["content"] if tpl else "{spanish_text}"
        motion_content = motion["content"] if motion else ""
        
        final_prompt = template_content.replace("{spanish_text}", text)
        final_prompt = final_prompt.replace("{camera_motion}", motion_content)
        final_prompt = re.sub(r' +', ' ', final_prompt).strip()
        
        self.table_segments.blockSignals(True)
        
        # Update index & icons
        self.refresh_table_row_index_label(row)
        
        # Update prompt cell
        prompt_item = QTableWidgetItem(final_prompt)
        prompt_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        self.table_segments.setItem(row, 4, prompt_item)
        
        # Re-apply row color if copied
        if hasattr(self, 'copied_rows') and row in self.copied_rows:
            self.change_row_color(row, copied=True)
            
        self.table_segments.blockSignals(False)

    def reset_all_segments_to_unified(self):
        """Clears all custom template and motion overrides for segments, resetting them to global."""
        if not self.project_model or not self.project_model.spanish_segments:
            return
            
        reply = QMessageBox.question(
            self,
            "确认重置",
            "确定要清空所有片段的独立模板与运镜设置，全员恢复为使用顶部的统一设置吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            for seg in self.project_model.spanish_segments:
                seg["template_id"] = ""
                seg["motion_id"] = ""
            self.project_model.save()
            self.refresh_prop_template_motion_combos()
            self.populate_segments_table()
            QMessageBox.information(self, "成功", "已成功重置所有片段为统一设置！")

    def export_batch_json(self):
        """Generates task list JSON and opens batch copy dialog partitioned by points budget <= 50."""
        if not self.project_model:
            QMessageBox.warning(self, "提示", "请先打开一个工程项目。")
            return
            
        segments = self.project_model.spanish_segments
        if not segments:
            QMessageBox.warning(self, "提示", "当前项目没有西文分句，无法生成任务。")
            return
            
        # 1. Check prompt template selection
        tpl_id = self.combo_templates.currentData()
        if not tpl_id:
            QMessageBox.warning(self, "提示", "导出失败：请先选择提示词模板！")
            return
            
        # 2. Check image material association for all segments
        missing_image_rows = []
        for idx, seg in enumerate(segments):
            if not seg.get("image_name"):
                missing_image_rows.append(idx + 1)
                
        if missing_image_rows:
            if len(missing_image_rows) == len(segments):
                QMessageBox.warning(self, "提示", "导出失败：句段尚未关联图片素材，请先选择关联图片素材！")
            else:
                rows_str = "、".join([f"第 {r} 句" for r in missing_image_rows[:5]])
                if len(missing_image_rows) > 5:
                    rows_str += f" 等 {len(missing_image_rows)} 句"
                QMessageBox.warning(self, "提示", f"导出失败：{rows_str} 尚未关联图片素材，请先选择关联图片素材！")
            return
            
        all_tasks = []
        skipped_copied_count = 0
        
        videos_dir = self.project_path / "downloads" / "videos" if self.project_path else Path("downloads/videos")
        for idx, seg in enumerate(segments):
            # 严格依据本地磁盘是否存在已完成的 mp4 视频文件作为跳过标准
            download_name = f"{idx+1:02d}.mp4"
            download_path_obj = (videos_dir / download_name).resolve()
            
            if download_path_obj.exists() and download_path_obj.stat().st_size > 0:
                seg["copied"] = True
                seg["completed"] = True
                if hasattr(self, 'copied_rows'):
                    self.copied_rows.add(idx)
                skipped_copied_count += 1
                continue
            else:
                seg["copied"] = False
                seg["completed"] = False
                if hasattr(self, 'copied_rows'):
                    self.copied_rows.discard(idx)
                
            raw_text = seg.get("text", "")
            text = TextProcessor.remove_punctuation(raw_text)
            seg["text"] = text
            
            # Generate final prompt resolving segment override or global fallback
            tpl, motion = self.get_effective_template_and_motion(idx)
            template_content = tpl["content"] if tpl else "{spanish_text}"
            motion_content = motion["content"] if motion else ""
            
            final_prompt = template_content.replace("{spanish_text}", text)
            final_prompt = final_prompt.replace("{camera_motion}", motion_content)
            final_prompt = re.sub(r' +', ' ', final_prompt).strip()
            
            image_name = seg.get("image_name", "")
            mode = seg.get("mode", "VIDEO_FRAMES")
            duration = seg.get("duration", 6)
            
            local_image_path = ""
            if image_name:
                local_image_path = str((self.project_path / "downloads" / image_name).resolve())
                
            # Formulate output download_path under 'downloads/videos' folder
            videos_dir = self.project_path / "downloads" / "videos"
            download_name = f"{idx+1:02d}.mp4"
            download_path = str((videos_dir / download_name).resolve())
            
            end_image_name, end_local_image_path, _ = self.resolve_segment_end_image_and_data(idx, seg)

            task_dict = {
                "prompt": final_prompt,
                "mode": mode,
                "image_name": image_name,
                "local_image_path": local_image_path,
                "duration": duration,
                "download_path": download_path,
                "_raw_duration": duration,
                "_original_index": idx,
                "_text_len": len(text)
            }
            if getattr(self, "enable_end_frame", False) and end_image_name:
                task_dict["end_image_name"] = end_image_name
                task_dict["end_local_image_path"] = end_local_image_path

            all_tasks.append(task_dict)

        if not all_tasks:
            if skipped_copied_count > 0:
                QMessageBox.information(
                    self, "提示", 
                    f"所有 {skipped_copied_count} 个分句均已手动复制/生成过（已变绿标结）。\n"
                    "已自动排除这些片段，没有需要新导出的任务！\n\n"
                    "💡 如需重新导出，请在表格中双击对应句子的【秒数】列取消已完成标绿即可。"
                )
            else:
                QMessageBox.warning(self, "提示", "当前项目没有可导出的有效分句。")
            return
            
        # Partition tasks using First Fit Decreasing (FFD) to maximize points utilization per batch
        batches = []
        max_batch_points = self.config_manager.max_batch_points if self.config_manager else 50
        
        def get_task_points_val(dur):
            if self.config_manager:
                return self.config_manager.get_points_for_duration(dur)
            points_map = {10: 15, 8: 12, 6: 10, 4: 7}
            return points_map.get(dur, 7)

        def get_task_points(task):
            return get_task_points_val(task.get("duration", task.get("_raw_duration", 6)))
            
        # Sort tasks descending by base points
        sorted_tasks = sorted(all_tasks, key=get_task_points, reverse=True)
        
        for task in sorted_tasks:
            pts = get_task_points(task)
            # Find the first batch that can fit this task
            placed = False
            for batch in batches:
                # Calculate current points in this batch
                batch_points = sum(get_task_points(t) for t in batch)
                if batch_points + pts <= max_batch_points:
                    batch.append(task)
                    placed = True
                    break
            if not placed:
                # Create a new batch
                batches.append([task])


        # Sort tasks within each batch by their original chronological index for clear display
        for batch in batches:
            batch.sort(key=lambda t: t["_original_index"])
            
        # Open the batch copy dialog
        dialog = BatchExportDialog(self, batches, self.config_manager, skipped_count=skipped_copied_count)
        dialog.exec()

    def open_settings_dialog(self):
        """Opens rules and points settings dialog."""
        from views.settings_dialog import SettingsDialog
        if not self.config_manager:
            main_win = self.window()
            if hasattr(main_win, "config_manager"):
                self.config_manager = main_win.config_manager
                
        if self.config_manager:
            dialog = SettingsDialog(self.config_manager, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.populate_segments_table()

    def check_video_completeness(self):
        """Scans disk for generated video files and displays completeness inspection dialog."""
        if not self.project_model:
            QMessageBox.warning(self, "提示", "请先打开一个工程项目。")
            return
            
        from services.video_checker import VideoChecker
        from views.video_check_dialog import VideoCheckDialog
        
        base_storage_path = None
        main_win = self.window()
        if hasattr(main_win, "storage_manager") and main_win.storage_manager:
            base_storage_path = main_win.storage_manager.get_base_path()
        if not base_storage_path and self.project_path:
            base_storage_path = Path(self.project_path).parent
            
        report = VideoChecker.check_project_videos(self.project_model, self.project_path, base_storage_path=base_storage_path)
        dialog = VideoCheckDialog(report, self.project_model, self.project_path, base_storage_path=base_storage_path, parent=self)
        dialog.exec()

    def import_execution_report(self):
        """Reads status report from clipboard and relocates downloaded videos to their target paths."""
        if not self.project_model:
            QMessageBox.warning(self, "提示", "请先打开一个工程项目。")
            return
            
        clipboard = QGuiApplication.clipboard()
        report_text = clipboard.text().strip()
        if not report_text:
            QMessageBox.warning(self, "提示", "剪贴板为空，请先从浏览器插件复制运行报告。")
            return
            
        import json
        import re
        
        # Try to extract JSON list or object block from clipboard text
        match = re.search(r'(\[.*\]|\{.*\})', report_text, re.DOTALL)
        json_candidate = match.group(1) if match else report_text
        
        try:
            report_data = json.loads(json_candidate)
            if isinstance(report_data, dict):
                report_data = [report_data]
            elif not isinstance(report_data, list):
                raise ValueError("解析的数据既不是 JSON 数组也不是 JSON 对象")
        except Exception as e:
            preview = report_text[:80] + "..." if len(report_text) > 80 else report_text
            QMessageBox.critical(
                self, "解析失败", 
                f"解析剪贴板 JSON 失败: {e}\n\n"
                f"当前剪贴板文本预览：\n{preview}\n\n"
                f"请确保您已点击 Chrome 插件的“复制报告”按钮，或剪贴板中是合法的 JSON 格式报告。"
            )
            return
            
        from pathlib import Path
        import shutil
        
        success_count = 0
        fail_count = 0
        not_found_paths = []
        
        chrome_downloads = Path.home() / "Downloads"
        
        for item in report_data:
            target_path_str = item.get("download_path")
            status = item.get("status")
            
            if not target_path_str or status != "success":
                continue
                
            # 安全边界校验：确保目标路径在工程目录或当前基础存储路径下
            if self.project_path:
                try:
                    resolved_target = Path(target_path_str).resolve()
                    base_storage = self.project_path.parent.resolve()
                    if not (resolved_target.is_relative_to(self.project_path.resolve()) or resolved_target.is_relative_to(base_storage)):
                        continue
                except Exception:
                    continue
                
            target_path = Path(target_path_str)
            filename = target_path.name
            
            possible_sources = [
                chrome_downloads / "Flow" / self.project_model.project_id / filename,
                chrome_downloads / "Flow" / f"{self.project_model.project_id}-flow" / filename,
                chrome_downloads / "Flow" / filename,
                chrome_downloads / filename,
            ]
            
            source_file = None
            for p in possible_sources:
                if p.exists() and p.is_file():
                    source_file = p
                    break
                    
            if not source_file:
                flow_dir = chrome_downloads / "Flow"
                if flow_dir.exists():
                    found_files = list(flow_dir.glob(f"**/{filename}"))
                    if found_files:
                        source_file = found_files[0]
                        
            if not source_file:
                found_files = list(chrome_downloads.glob(f"**/{filename}"))
                if found_files:
                    source_file = found_files[0]
                    
            if source_file:
                try:
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(source_file), str(target_path))
                    success_count += 1
                except Exception as err:
                    print(f"Error moving file {source_file} to {target_path}: {err}")
                    fail_count += 1
            else:
                not_found_paths.append(filename)
                
        self.refresh_media_list()
        
        if self.project_model:
            self.project_model.update_media_files()
            main_win = self.window()
            if hasattr(main_win, "reload_projects_list"):
                main_win.reload_projects_list()
            
        msg = f"已成功移入并归档 {success_count} 个视频文件！\n"
        if fail_count > 0:
            msg += f"移动失败 {fail_count} 个文件。\n"
        if not_found_paths:
            msg += f"\n未在下载目录中找到以下 {len(not_found_paths)} 个视频（请确认浏览器下载已完成）：\n"
            msg += "\n".join(f"- {name}" for name in not_found_paths[:5])
            if len(not_found_paths) > 5:
                msg += f"\n... 以及其他 {len(not_found_paths) - 5} 个文件"
                
        if success_count > 0:
            QMessageBox.information(self, "归档结果", msg)
        else:
            QMessageBox.warning(self, "未找到文件", msg)

    def on_plugin_report_received(self, report_data):
        """Processes execution report received via WebSocket from a browser plugin."""
        if not self.project_model or not self.project_path:
            return
            
        safe_proj_root = Path(self.project_path).resolve()
        data = report_data.get("data", [])
        segments = self.project_model.spanish_segments
        chrome_downloads = Path.home() / "Downloads"
        import base64
        import shutil

        updated_count = 0
        for item in data:
            idx = item.get("index")
            status = item.get("status", "success")
            download_url = item.get("download_url")
            target_path_str = item.get("download_path")
            base64_data = item.get("base64Data") or item.get("base64_data")

            # 兼容通过 prompt 反查 index
            if (idx is None or not isinstance(idx, int) or idx < 0 or idx >= len(segments)) and item.get("prompt"):
                for s_idx, seg in enumerate(segments):
                    if item.get("prompt") in seg.get("text", ""):
                        idx = s_idx
                        break

            # 兼容 1-indexed 索引 (例如 1..len(segments))
            if idx is not None and isinstance(idx, int):
                if idx >= len(segments) and idx - 1 < len(segments):
                    idx = idx - 1

            if idx is not None and isinstance(idx, int) and 0 <= idx < len(segments):
                if hasattr(self, 'dispatched_indices') and idx in self.dispatched_indices:
                    self.dispatched_indices.discard(idx)

            if status == "success" and idx is not None and isinstance(idx, int) and 0 <= idx < len(segments):
                segments[idx]["copied"] = True
                segments[idx]["completed"] = True
                segments[idx]["status"] = "success"
                self.copied_rows.add(idx)
                updated_count += 1
                
                # 校验并规范化 target_path_str 安全边界 (严格保证在工程目录内部)
                videos_dir = (safe_proj_root / "downloads" / "videos").resolve()
                videos_dir.mkdir(parents=True, exist_ok=True)
                fallback_path_str = str((videos_dir / f"{idx + 1:02d}.mp4").resolve())

                if target_path_str:
                    try:
                        resolved_target = Path(target_path_str).resolve()
                        if not resolved_target.is_relative_to(safe_proj_root):
                            target_path_str = fallback_path_str
                    except Exception:
                        target_path_str = fallback_path_str
                else:
                    target_path_str = fallback_path_str

                download_success = False
                target_filename = item.get("target_filename")
                project_name = item.get("project_name")
                
                # 安全过滤：提取纯文件名与工程名，防止目录穿越
                clean_target_filename = Path(str(target_filename)).name if target_filename else None
                clean_project_name = Path(str(project_name)).name if project_name else None
                resolved_chrome_downloads = chrome_downloads.resolve()
                
                # 1. 优先扫描 Chrome Downloads 目录并自动移动/复制至当前工程目录
                possible_sources = []
                if clean_project_name and clean_target_filename:
                    possible_sources.append(chrome_downloads / "Flow" / clean_project_name / clean_target_filename)
                if clean_target_filename:
                    possible_sources.append(chrome_downloads / "Flow" / clean_target_filename)
                
                if self.project_model:
                    p_id = Path(str(self.project_model.project_id)).name
                    filename = Path(str(target_path_str)).name
                    possible_sources.extend([
                        chrome_downloads / "Flow" / p_id / filename,
                        chrome_downloads / "Flow" / f"{p_id}-flow" / filename,
                        chrome_downloads / "Flow" / filename,
                        chrome_downloads / filename,
                    ])

                source_file = None
                for p in possible_sources:
                    try:
                        resolved_p = p.resolve()
                        if resolved_p.is_relative_to(resolved_chrome_downloads) and resolved_p.exists() and resolved_p.is_file() and resolved_p.stat().st_size > 1024:
                            source_file = resolved_p
                            break
                    except Exception:
                        continue
                
                # 通配扫描最近在 Downloads/Flow 目录中生成的 mp4 文件
                if not source_file:
                    flow_dir = chrome_downloads / "Flow"
                    if flow_dir.exists():
                        recent_mp4s = list(flow_dir.glob("**/*.mp4"))
                        recent_mp4s.sort(key=lambda f: f.stat().st_mtime, reverse=True)
                        if recent_mp4s:
                            # 取最新的一个 mp4 文件
                            source_file = recent_mp4s[0]

                if source_file and target_path_str:
                    try:
                        target_path = Path(target_path_str).resolve()
                        if target_path.is_relative_to(safe_proj_root):
                            target_path.parent.mkdir(parents=True, exist_ok=True)
                            shutil.move(str(source_file), str(target_path))
                            download_success = True
                            logger.info(f"✅ [Chrome 下载扫描成功] 成功将下载文件 {source_file} 归位移动至: {target_path}")
                    except Exception as move_err:
                        logger.warning(f"移动 Chrome 下载文件异常: {move_err}")

                # 2. 次选方案：解码 Base64 视频字节流直接写入
                if not download_success and base64_data and target_path_str:
                    try:
                        target_path = Path(target_path_str).resolve()
                        if target_path.is_relative_to(safe_proj_root):
                            target_path.parent.mkdir(parents=True, exist_ok=True)
                            video_bytes = base64.b64decode(base64_data)
                            if len(video_bytes) > 1024:
                                with open(target_path, "wb") as f:
                                    f.write(video_bytes)
                                download_success = True
                                logger.info(f"✅ Base64 视频字节流成功写入: {target_path}")
                    except Exception as b64_err:
                        logger.warning(f"解码 Base64 视频失败: {b64_err}")

                # 3. 备用方案：HTTP 直连流下载 (严格校验协议、域名解析防 DNS Rebinding / 私网 / 回环 SSRF，并安全处理重定向与超时)
                if not download_success and download_url and target_path_str:
                    dl_url_str = str(download_url).strip()
                    if dl_url_str.startswith(("http://", "https://")):
                        try:
                            from urllib.parse import urlparse, urljoin
                            import socket
                            import ipaddress
                            import requests

                            def is_safe_external_url(url_val):
                                p = urlparse(url_val)
                                if p.scheme not in ("http", "https"):
                                    return False
                                host = (p.hostname or "").strip().lower()
                                if not host or host in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):  # nosec B104 - host rejection check
                                    return False
                                if host.endswith(".local") or host.endswith(".internal"):
                                    return False
                                try:
                                    addrs = socket.getaddrinfo(host, None)
                                    if not addrs:
                                        return False
                                    for addr in addrs:
                                        ip_obj = ipaddress.ip_address(addr[4][0])
                                        if (ip_obj.is_private or ip_obj.is_loopback or 
                                            ip_obj.is_link_local or ip_obj.is_reserved or 
                                            ip_obj.is_multicast or ip_obj.is_unspecified):
                                            return False
                                    return True
                                except Exception:
                                    return False

                            curr_url = dl_url_str
                            session = requests.Session()
                            headers = {
                                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                            }
                            resp = None
                            for _ in range(5):
                                if not is_safe_external_url(curr_url):
                                    logger.warning(f"🚨 [Security] 拒绝向私网/回环地址发起直连下载或重定向: {curr_url}")
                                    resp = None
                                    break
                                resp = session.get(curr_url, headers=headers, allow_redirects=False, stream=True, timeout=(15, 60))
                                if resp.is_redirect or resp.status_code in (301, 302, 303, 307, 308):
                                    loc = resp.headers.get("Location")
                                    if not loc:
                                        break
                                    curr_url = urljoin(curr_url, loc)
                                else:
                                    break

                            if resp and resp.status_code == 200:
                                target_path = Path(target_path_str).resolve()
                                if target_path.is_relative_to(safe_proj_root):
                                    target_path.parent.mkdir(parents=True, exist_ok=True)
                                    part_path = target_path.with_name(f"{target_path.name}.part")
                                    try:
                                        with open(part_path, "wb") as f:
                                            for chunk in resp.iter_content(chunk_size=16384):
                                                f.write(chunk)
                                        if target_path.exists():
                                            target_path.unlink()
                                        shutil.move(str(part_path), str(target_path))
                                        download_success = True
                                        logger.info(f"✅ HTTP 直连下载成功: {target_path}")
                                    finally:
                                        if part_path.exists():
                                            part_path.unlink(missing_ok=True)
                        except Exception as dl_err:
                            logger.warning(f"HTTP 直连下载异常: {dl_err}")

                # 4. 延迟 1.5 秒与 4 秒再次扫描 Chrome 下载目录 (解决 Chrome 写入未完成问题)
                if not download_success and target_path_str:
                    def try_delayed_copy(tp_str=target_path_str):
                        tp = Path(tp_str).resolve()
                        if not tp.is_relative_to(safe_proj_root):
                            return
                        flow_dir = chrome_downloads / "Flow"
                        if flow_dir.exists():
                            recent_mp4s = list(flow_dir.glob("**/*.mp4"))
                            recent_mp4s.sort(key=lambda f: f.stat().st_mtime, reverse=True)
                            if recent_mp4s:
                                try:
                                    tp.parent.mkdir(parents=True, exist_ok=True)
                                    shutil.copy2(recent_mp4s[0], tp)
                                    logger.info(f"✅ 延迟扫描归档成功复制 {recent_mp4s[0]} 至: {tp}")
                                    if hasattr(self, 'populate_segments_table'):
                                        self.populate_segments_table()
                                except Exception as e:
                                    logger.warning(f"延迟复制视频失败: {e}")

                    QTimer.singleShot(1500, try_delayed_copy)
                    QTimer.singleShot(4000, try_delayed_copy)

        if updated_count > 0:
            self.project_model.save()
            self.populate_segments_table()
            
        if self.is_auto_polling_active:
            QTimer.singleShot(300, self.run_polling_dispatcher_cycle)

    def pack_batch_for_capacity(self, capacity_points, max_tasks=None):
        """
        Packs a task batch from current project's uncompleted segments to fit capacity_points,
        optionally limiting to max_tasks for optimal load-balancing across multiple online workers.
        """
        if not self.project_model or not self.project_model.spanish_segments:
            return []

        segments = self.project_model.spanish_segments
        all_unprocessed_tasks = []
        for idx, seg in enumerate(segments):
            # 排除已经被分配给其他正在运行 Worker 的任务
            if hasattr(self, 'dispatched_indices') and idx in self.dispatched_indices:
                continue

            # 超过 3 次重试失败的顽固片段，先临时跳过，防止阻塞整个工程与流水线
            if hasattr(self, 'failed_skip_indices') and idx in self.failed_skip_indices:
                continue

            videos_dir = self.project_path / "downloads" / "videos" if self.project_path else Path("downloads/videos")
            download_name = f"{idx+1:02d}.mp4"
            download_path_obj = (videos_dir / download_name).resolve()
            download_path = str(download_path_obj)

            # 核心判重与断点续跑：以本地硬盘是否真实存在该序号的非空 mp4 视频文件为唯一判重标准！
            if download_path_obj.exists() and download_path_obj.stat().st_size > 0:
                seg["copied"] = True
                seg["completed"] = True
                if hasattr(self, 'copied_rows'):
                    self.copied_rows.add(idx)
                if hasattr(self, 'segment_retry_counts'):
                    self.segment_retry_counts.pop(idx, None)
                if hasattr(self, 'failed_skip_indices'):
                    self.failed_skip_indices.discard(idx)
                continue
            else:
                seg["copied"] = False
                seg["completed"] = False
                if hasattr(self, 'copied_rows'):
                    self.copied_rows.discard(idx)

            raw_text = seg.get("text", "")
            text = TextProcessor.remove_punctuation(raw_text)
            
            tpl, motion = self.get_effective_template_and_motion(idx)
            template_content = tpl["content"] if tpl else "{spanish_text}"
            motion_content = motion["content"] if motion else ""
            
            final_prompt = template_content.replace("{spanish_text}", text)
            final_prompt = final_prompt.replace("{camera_motion}", motion_content)
            final_prompt = re.sub(r' +', ' ', final_prompt).strip()
            
            image_name, local_image_path, image_data_url = self.resolve_segment_image_and_data(idx, seg)
            end_image_name, end_local_image_path, end_image_data_url = self.resolve_segment_end_image_and_data(idx, seg)
            mode = seg.get("mode", "VIDEO_FRAMES")
            duration = seg.get("duration", 6)
                
            videos_dir = self.project_path / "downloads" / "videos" if self.project_path else Path("downloads/videos")
            download_name = f"{idx+1:02d}.mp4"
            download_path = str((videos_dir / download_name).resolve())
            
            task_dict = {
                "index": idx,
                "prompt": final_prompt,
                "mode": mode,
                "image_name": image_name,
                "local_image_path": local_image_path,
                "image_data_url": image_data_url,
                "imageDataUrl": image_data_url,
                "duration": duration,
                "download_path": download_path,
                "_raw_duration": duration,
                "_original_index": idx,
                "_text_len": len(text)
            }
            if getattr(self, "enable_end_frame", False) and end_image_name:
                task_dict["end_image_name"] = end_image_name
                task_dict["end_local_image_path"] = end_local_image_path
                task_dict["end_image_data_url"] = end_image_data_url
                task_dict["endImageDataUrl"] = end_image_data_url

            all_unprocessed_tasks.append(task_dict)

        if not all_unprocessed_tasks or capacity_points < 7:
            return []

        def get_task_points_val(dur):
            if self.config_manager:
                return self.config_manager.get_points_for_duration(dur)
            points_map = {10: 15, 8: 12, 6: 10, 4: 7}
            return points_map.get(dur, 7)

        def get_task_points(task):
            return get_task_points_val(task.get("duration", task.get("_raw_duration", 6)))

        # Sort tasks descending by points
        sorted_tasks = sorted(all_unprocessed_tasks, key=get_task_points, reverse=True)

        batch = []
        cur_pts = 0
        for task in sorted_tasks:
            if max_tasks is not None and len(batch) >= max_tasks:
                break
            pts = get_task_points(task)
            if cur_pts + pts <= capacity_points:
                batch.append(task)
                cur_pts += pts

        if not batch:
            return []

        batch.sort(key=lambda t: t["_original_index"])
        
        cleaned_batch = []
        for item in batch:
            cleaned_item = {k: v for k, v in item.items() if not k.startswith("_")}
            cleaned_batch.append(cleaned_item)
            
        return cleaned_batch

    def start_auto_polling_dispatcher(self):
        """Starts the auto-polling task dispatcher for the current project."""
        if not self.plugin_server:
            QMessageBox.warning(self, "提示", "WebSocket 插件服务端未启动。")
            return

        tpl_id = self.combo_templates.currentData() if hasattr(self, "combo_templates") else None
        if not tpl_id:
            QMessageBox.warning(self, "提示", "⚠️ 请先在上方为当前工程选择【统一提示词模板】后再启动自动分发！")
            return

        clients = self.plugin_server.get_online_clients()
        if not clients:
            QMessageBox.warning(self, "提示", "⚠️ 当前没有在线的浏览器 Worker。\n\n请在 Chrome 浏览器中打开 Google Flow 网页。")
            return

        # 启动时彻底清空历史锁定索引、跳过记录与重试计数，确保每次启动所有未完成句子都能全量正常生成
        self.dispatched_indices = set()
        self.failed_skip_indices = set()
        self.segment_retry_counts = {}
        for socket, info in self.plugin_server.clients.items():
            if info.get("remaining_points", 0) >= 7:
                info["status"] = "idle"
            else:
                info["status"] = "low_points"
            info["current_batch"] = None

        usable_clients = [c for c in clients if c.get("remaining_points", 0) >= 7]
        if not usable_clients:
            total_pts = sum(c.get("remaining_points", 0) for c in clients)
            QMessageBox.warning(
                self, "积分不足提示",
                f"⚠️ 当前在线的 {len(clients)} 个浏览器 Worker 积分均不足 7 点（当前总积分剩余 {total_pts} 点，不足以支付一个视频）。\n\n"
                "请点击【🔄 刷新点数】重新探测，或更换有积分的 Google 账号。"
            )
            return
            
        self.is_auto_polling_active = True
        if not hasattr(self, "polling_timer") or not self.polling_timer:
            self.polling_timer = QTimer(self)
            self.polling_timer.timeout.connect(self.run_polling_dispatcher_cycle)
            
        self.run_polling_dispatcher_cycle()
        self.polling_timer.start(4000) # Poll every 4 seconds

    def stop_auto_polling_dispatcher(self):
        """Stops the auto-polling task dispatcher."""
        self.is_auto_polling_active = False
        if hasattr(self, "polling_timer") and self.polling_timer:
            self.polling_timer.stop()

    def run_polling_dispatcher_cycle(self):
        """Runs one cycle of the auto-polling dispatcher for this project."""
        if not self.is_auto_polling_active:
            return

        if not self.project_model or not self.project_model.spanish_segments:
            self.stop_auto_polling_dispatcher()
            return

        segments = self.project_model.spanish_segments
        videos_dir = self.project_path / "downloads" / "videos" if self.project_path else Path("downloads/videos")

        clients = self.plugin_server.get_online_clients()
        idle_clients = [c for c in clients if c.get("status") == "idle" and c.get("remaining_points", 0) >= 7]

        # 1. 动态释放任务锁定：若没有 busy Worker 在跑，彻底释放 dispatched_indices 供下一次重试！
        busy_workers = [c for c in clients if c.get("status") == "busy"]
        if not busy_workers and hasattr(self, 'dispatched_indices'):
            self.dispatched_indices.clear()

        def check_seg_done(i):
            p = (videos_dir / f"{i+1:02d}.mp4").resolve()
            return p.exists() and p.stat().st_size > 0

        # 2. 检查所有未完成的句子：若重试次数已达 3 次，立即加入 failed_skip_indices
        if not hasattr(self, 'failed_skip_indices'):
            self.failed_skip_indices = set()
        if not hasattr(self, 'segment_retry_counts'):
            self.segment_retry_counts = {}

        for idx, _ in enumerate(segments):
            if not check_seg_done(idx):
                if self.segment_retry_counts.get(idx, 0) >= 3:
                    self.failed_skip_indices.add(idx)

        uncompleted_count = sum(
            1 for idx, _ in enumerate(segments)
            if not (check_seg_done(idx) or idx in self.failed_skip_indices)
        )

        if uncompleted_count == 0:
            self.stop_auto_polling_dispatcher()
            skip_count = len(self.failed_skip_indices)
            if skip_count > 0:
                logger.info(f"🎉 当前工程已完成所有可生成视频（有 {skip_count} 句重试 3 次未出片已自动先跳过）！")
            else:
                logger.info("🎉 当前工程所有视频已全部在本地磁盘生成就绪！")
            if self.active_batch_dialog:
                self.active_batch_dialog.update_polling_ui()
            return

        if not idle_clients:
            return

        # 智能全并行负载均衡：计算每个 Worker 应分担的任务上限，确保所有在线浏览器全部动起来！
        remaining_tasks_count = sum(
            1 for idx, _ in enumerate(segments)
            if not (check_seg_done(idx) or (hasattr(self, 'dispatched_indices') and idx in self.dispatched_indices) or idx in self.failed_skip_indices)
        )
        
        tasks_per_worker = max(1, (remaining_tasks_count + len(idle_clients) - 1) // len(idle_clients)) if remaining_tasks_count > 0 else 5
        logger.info(f"🔄 调度周期: 剩余待分发任务数={remaining_tasks_count}, 空闲有分Worker数={len(idle_clients)}, 单Worker配额={tasks_per_worker}")

        for client in idle_clients:
            pts = client.get("remaining_points", 0)
            if pts < 7:
                continue
            batch_tasks = self.pack_batch_for_capacity(pts, max_tasks=tasks_per_worker)
            if batch_tasks:
                task_indices = [t["index"] for t in batch_tasks if "index" in t]
                for idx in task_indices:
                    self.dispatched_indices.add(idx)
                    # 记录并累加重试计数
                    self.segment_retry_counts[idx] = self.segment_retry_counts.get(idx, 0) + 1
                    
                    # 若重试达 3 次且本地仍无文件，加入跳过集合
                    if self.segment_retry_counts[idx] >= 3:
                        self.failed_skip_indices.add(idx)
                        logger.warning(f"⚠️ [智能熔断] 第 {idx+1} 句已累计重试 3 次未成功出片，自动先跳过以保障流水线顺畅推进！")

                batch_id = f"{self.project_model.project_id}_{int(QDateTime.currentMSecsSinceEpoch())}_{client['client_id']}"
                logger.info(f"🚀 向 Worker [{client['client_id']}] 派发任务 ({len(batch_tasks)}条, 序号: {task_indices})")
                self.plugin_server.send_tasks_to_client(client["client_id"], batch_id, batch_tasks)
                if self.active_batch_dialog and self.active_batch_dialog.isVisible():
                    self.active_batch_dialog.refresh_workers_list()


class BatchExportDialog(QDialog):
    def __init__(self, parent, batches, config_manager=None, skipped_count=0):
        super().__init__(parent)
        self.project_widget = parent if hasattr(parent, "start_auto_polling_dispatcher") else None
        if self.project_widget:
            self.project_widget.active_batch_dialog = self

        self.cm = config_manager
        self.skipped_count = skipped_count
        max_pts = self.cm.max_batch_points if self.cm else 50
        self.setWindowTitle(f"分批生成与多浏览器调度 (最高{max_pts}积分/批)")
        self.resize(780, 580)
        self.batches = batches  # List of lists of dicts
        self.copied_batches = set()
        self.init_ui()
        
    def closeEvent(self, event):
        if self.project_widget:
            self.project_widget.active_batch_dialog = None
        super().closeEvent(event)

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(12)
        
        # Summary Label
        total_segments = sum(len(b) for b in self.batches)
        total_points = sum(self.get_batch_points(b) for b in self.batches)
        total_end_frames = sum(sum(1 for t in b if t.get("end_image_name")) for b in self.batches)
        max_pts = self.cm.max_batch_points if self.cm else 50
        
        skipped_text = f" <span style='color: #10B981;'>(已自动排除 {self.skipped_count} 个已生成的变绿片段)</span>" if self.skipped_count > 0 else ""
        end_stat_text = f" | 🎬 包含 <b>{total_end_frames}</b> 个配置尾帧的分句" if total_end_frames > 0 else ""
        
        lbl_summary = QLabel(
            f"📊 <b>统计信息</b>：共 <b>{total_segments}</b> 个待生成视频片段{skipped_text}{end_stat_text}，"
            f"总需 <b>{total_points}</b> 积分。<br/>"
            f"每批次上限为 <b>{max_pts}</b> 积分，已拆为 <b>{len(self.batches)}</b> 个批次。"
        )
        lbl_summary.setStyleSheet("font-size: 13px; color: #5D4037;")
        layout.addWidget(lbl_summary)

        # Quick actions bar for plugin table integration
        quick_bar = QHBoxLayout()
        quick_bar.setSpacing(8)
        
        lbl_quick_hint = QLabel("💡 插件表格对接：")
        lbl_quick_hint.setStyleSheet("font-size: 12px; color: #78350F; font-weight: bold;")
        quick_bar.addWidget(lbl_quick_hint)
        
        btn_copy_all_end = QPushButton(f"🎬 复制全部待生成尾帧列 (共 {total_segments} 行)")
        btn_copy_all_end.setToolTip(
            f"将所有待生成的 {total_segments} 个分句尾帧按顺序整理为多行文本。\n"
            "在插件表格第1行的【尾帧图片名】单元格按 Ctrl+V 即可整列全部填满！"
        )
        btn_copy_all_end.setStyleSheet("""
            QPushButton {
                background-color: #D97706;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #B45309;
            }
        """)
        btn_copy_all_end.clicked.connect(lambda: self.copy_all_end_frames(btn_copy_all_end))
        quick_bar.addWidget(btn_copy_all_end)

        btn_copy_all_tsv = QPushButton(f"📊 复制全部表格数据 (TSV格式)")
        btn_copy_all_tsv.setToolTip(
            "按 [序号 \\t 首帧图名 \\t 尾帧图名 \\t 分镜名] 复制全部待生成数据。\n"
            "适用于支持多列批量粘贴的场景或 Excel 表格整理。"
        )
        btn_copy_all_tsv.setStyleSheet("""
            QPushButton {
                background-color: #0284C7;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #0369A1;
            }
        """)
        btn_copy_all_tsv.clicked.connect(lambda: self.copy_all_tsv(btn_copy_all_tsv))
        quick_bar.addWidget(btn_copy_all_tsv)

        quick_bar.addStretch()
        layout.addLayout(quick_bar)
        
        # Scrollable area of batches
        self.list_batches = QListWidget()
        self.list_batches.setStyleSheet("""
            QListWidget {
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                background-color: #FAFAFA;
            }
        """)
        
        for idx, batch in enumerate(self.batches):
            item = QListWidgetItem(self.list_batches)
            
            widget = QWidget()
            widget_layout = QHBoxLayout(widget)
            widget_layout.setContentsMargins(12, 10, 12, 10)
            
            points = self.get_batch_points(batch)
            indices_str = ", ".join(str(t["_original_index"] + 1) for t in batch)
            batch_end_count = sum(1 for t in batch if t.get("end_image_name"))
            end_badge = f" | 🎬 尾帧: <b>{batch_end_count}</b> 个" if batch_end_count > 0 else ""
            
            info_text = (
                f"<b>第 {idx + 1} 批</b> (分镜序号: {indices_str})<br/>"
                f"📎 包含 {len(batch)} 个分句{end_badge} | ⚡ 消耗 <b>{points}</b> 积分"
            )
            lbl_info = QLabel(info_text)
            lbl_info.setStyleSheet("font-size: 12px; color: #5D4037;")
            widget_layout.addWidget(lbl_info, stretch=1)
            
            # Action buttons for this batch
            btns_layout = QHBoxLayout()
            btns_layout.setSpacing(6)
            
            btn_copy = QPushButton("📋 复制任务 JSON")
            btn_copy.setToolTip("复制本批次完整的 JSON 任务数据（包含提示词、时长、模式等），供插件导入")
            btn_copy.setStyleSheet("""
                QPushButton {
                    background-color: #8B5CF6;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 6px 12px;
                    font-size: 11px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #7C3AED;
                }
            """)
            btn_copy.clicked.connect(self.make_copy_callback(idx, btn_copy))
            btns_layout.addWidget(btn_copy)
            
            btn_copy_end = QPushButton("🎬 复制尾帧列")
            btn_copy_end.setToolTip(
                f"按本批分镜顺序将 {len(batch)} 行尾帧图片名复制为多行文本。\n"
                "在插件表格第1行【尾帧图片名】按 Ctrl+V 即可整列填满！"
            )
            btn_copy_end.setStyleSheet("""
                QPushButton {
                    background-color: #F59E0B;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 6px 10px;
                    font-size: 11px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #D97706;
                }
            """)
            btn_copy_end.clicked.connect(self.make_copy_end_callback(idx, btn_copy_end))
            btns_layout.addWidget(btn_copy_end)

            btn_copy_tsv = QPushButton("📊 表格TSV")
            btn_copy_tsv.setToolTip(f"按 [序号 \\t 首帧图名 \\t 尾帧图名 \\t 分镜名] 复制本批 {len(batch)} 行制表符数据")
            btn_copy_tsv.setStyleSheet("""
                QPushButton {
                    background-color: #0284C7;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 6px 10px;
                    font-size: 11px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #0369A1;
                }
            """)
            btn_copy_tsv.clicked.connect(self.make_copy_tsv_callback(idx, btn_copy_tsv))
            btns_layout.addWidget(btn_copy_tsv)
            
            widget_layout.addLayout(btns_layout)
            widget.setLayout(widget_layout)
            item.setSizeHint(widget.sizeHint())
            self.list_batches.setItemWidget(item, widget)
            
        layout.addWidget(self.list_batches)
        
        # Close Button
        btn_close = QPushButton("关闭")
        btn_close.setStyleSheet("background-color: #E0A96D; color: white; padding: 7px; font-weight: bold; border-radius: 4px;")
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)

    def refresh_workers_list(self):
        """No-op stub for backward compatibility."""
        pass

    def update_polling_ui(self):
        """No-op stub for backward compatibility."""
        pass

    def get_batch_points(self, batch):
        if self.cm:
            return sum(self.cm.get_points_for_duration(item.get("duration", item.get("_raw_duration", 6))) for item in batch)
        points_map = {10: 15, 8: 12, 6: 10, 4: 7}
        total = 0
        for item in batch:
            dur = item.get("duration", item.get("_raw_duration", 6))
            total += points_map.get(dur, 7)
        return total
        
    def make_copy_callback(self, batch_idx, button):
        return lambda: self.copy_batch(batch_idx, button)

    def make_copy_end_callback(self, batch_idx, button):
        return lambda: self.copy_end_frames_column(self.batches[batch_idx], button, desc=f"第 {batch_idx + 1} 批")

    def make_copy_tsv_callback(self, batch_idx, button):
        return lambda: self.copy_tsv_table(self.batches[batch_idx], button, desc=f"第 {batch_idx + 1} 批")

    def copy_batch(self, batch_idx, button):
        import json
        batch_data = self.batches[batch_idx]
        
        cleaned_batch = []
        for item in batch_data:
            c_item = {k: v for k, v in item.items() if not k.startswith("_")}
            cleaned_batch.append(c_item)
            
        try:
            json_str = json.dumps(cleaned_batch, indent=2, ensure_ascii=False)
            from PyQt6.QtGui import QGuiApplication
            clipboard = QGuiApplication.clipboard()
            clipboard.setText(json_str)
            
            button.setText("✓ 已复制")
            button.setStyleSheet("""
                QPushButton {
                    background-color: #10B981;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 6px 12px;
                    font-size: 11px;
                    font-weight: bold;
                }
            """)
            self.copied_batches.add(batch_idx)
        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "错误", f"复制批次失败: {e}")

    def copy_end_frames_column(self, batch_data, button, desc="本批"):
        """Copies newline-delimited end frame image names strictly aligned with batch tasks."""
        end_names = [item.get("end_image_name", "").strip() for item in batch_data]
        text_to_copy = "\n".join(end_names)
        
        try:
            from PyQt6.QtGui import QGuiApplication, QCursor
            from PyQt6.QtWidgets import QToolTip, QMessageBox
            clipboard = QGuiApplication.clipboard()
            clipboard.setText(text_to_copy)
            
            button.setText("✓ 已复制尾帧列")
            button.setStyleSheet("""
                QPushButton {
                    background-color: #059669;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 6px 10px;
                    font-size: 11px;
                    font-weight: bold;
                }
            """)
            has_end = sum(1 for n in end_names if n)
            msg = f"✓ 已复制{desc} {len(end_names)} 行尾帧名（含 {has_end} 个已设置尾帧）！\n请切换到插件端，在表格【尾帧图片名】首行单元格按 Ctrl+V 即可整列粘贴。"
            QToolTip.showText(QCursor.pos(), msg, button)
        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "错误", f"复制尾帧列失败: {e}")

    def copy_tsv_table(self, batch_data, button, desc="本批"):
        """Copies TSV formatted rows matching the plugin table structure."""
        tsv_lines = []
        for idx, item in enumerate(batch_data):
            orig_idx = item.get("_original_index", idx) + 1
            first_img = item.get("image_name", "").strip()
            end_img = item.get("end_image_name", "").strip()
            dl_path = item.get("download_path", "")
            dl_name = Path(dl_path).name if dl_path else f"{orig_idx:02d}.mp4"
            
            # Format matching plugin: 序号 \t 素材图/首帧-图片名 \t 尾帧图片名 \t 分镜片段名称
            line = f"{orig_idx}\t{first_img}\t{end_img}\t{dl_name}"
            tsv_lines.append(line)
            
        tsv_text = "\n".join(tsv_lines)
        try:
            from PyQt6.QtGui import QGuiApplication, QCursor
            from PyQt6.QtWidgets import QToolTip, QMessageBox
            clipboard = QGuiApplication.clipboard()
            clipboard.setText(tsv_text)
            
            button.setText("✓ 已复制TSV")
            button.setStyleSheet("""
                QPushButton {
                    background-color: #0284C7;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 6px 10px;
                    font-size: 11px;
                    font-weight: bold;
                }
            """)
            msg = f"✓ 已复制{desc} {len(tsv_lines)} 行 TSV 表格数据！\n格式：[序号 \\t 首帧图名 \\t 尾帧图名 \\t 分镜名]\n支持在 Excel 或插件表格中批量粘贴。"
            QToolTip.showText(QCursor.pos(), msg, button)
        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "错误", f"复制TSV表格失败: {e}")

    def copy_all_end_frames(self, button):
        all_tasks = [task for batch in self.batches for task in batch]
        self.copy_end_frames_column(all_tasks, button, desc="全部")

    def copy_all_tsv(self, button):
        all_tasks = [task for batch in self.batches for task in batch]
        self.copy_tsv_table(all_tasks, button, desc="全部")

