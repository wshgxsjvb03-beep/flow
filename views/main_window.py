# -*- coding: utf-8 -*-
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QLineEdit, QPushButton, QListWidget, 
                             QListWidgetItem, QSplitter, QFileDialog, QMessageBox,
                             QInputDialog, QMenu, QToolTip, QDialog, QSpinBox,
                             QProgressBar, QFrame)
from PyQt6.QtCore import Qt, QSize, QTimer
from PyQt6.QtGui import QGuiApplication, QCursor, QColor
from models.storage_manager import StorageManager
from views.import_dialog import ImportDialog
from views.project_detail_widget import ProjectDetailWidget
from services.pipeline_scheduler import PipelineScheduler
from pathlib import Path

class RenameProjectDialog(QDialog):
    """Dialog for modifying all parts of a project (Index, Project Name, and Notes)."""
    
    def __init__(self, index, col1_name, col7_notes, parent=None):
        super().__init__(parent)
        self.setWindowTitle("✏️ 重命名项目 (Rename Project)")
        self.resize(420, 260)
        self.index_val = index
        self.col1_val = col1_name
        self.col7_val = col7_notes
        self.init_ui()
        
    def init_ui(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #FAF6F0;
                color: #5D4037;
                font-family: "Segoe UI", sans-serif;
            }
            QLabel {
                font-size: 13px;
                color: #5D4037;
                font-weight: bold;
            }
            QLineEdit, QSpinBox {
                background-color: white;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                padding: 6px 10px;
                font-size: 13px;
                color: #5D4037;
            }
            QLineEdit:focus, QSpinBox:focus {
                border: 1px solid #E0A96D;
            }
            QPushButton {
                background-color: #E0A96D;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 14px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #D2904C;
            }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        
        # Index field
        idx_layout = QHBoxLayout()
        idx_layout.addWidget(QLabel("项目序号 (Index):"))
        self.spin_index = QSpinBox()
        self.spin_index.setRange(1, 9999)
        self.spin_index.setValue(int(self.index_val) if self.index_val else 1)
        idx_layout.addWidget(self.spin_index, stretch=1)
        layout.addLayout(idx_layout)
        
        # Name field
        layout.addWidget(QLabel("项目名称 (Project Name):"))
        self.txt_name = QLineEdit()
        self.txt_name.setText(self.col1_val)
        layout.addWidget(self.txt_name)
        
        # Notes field
        layout.addWidget(QLabel("项目备注/后缀 (Notes):"))
        self.txt_notes = QLineEdit()
        self.txt_notes.setText(self.col7_val)
        layout.addWidget(self.txt_notes)
        
        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)
        
        btn_save = QPushButton("💾 确认修改")
        btn_save.setStyleSheet("background-color: #10B981; color: white; font-weight: bold;")
        btn_save.clicked.connect(self.accept)
        btn_layout.addWidget(btn_save)
        
        layout.addLayout(btn_layout)

    def get_values(self):
        return self.spin_index.value(), self.txt_name.text().strip(), self.txt_notes.text().strip()

class MainWindow(QMainWindow):
    """Main window of the Project Manager application."""
    
    def __init__(self, workspace_dir):
        super().__init__()
        self.workspace_dir = Path(workspace_dir)
        self.storage_manager = StorageManager(self.workspace_dir)
        self.active_downloads = {}
        
        # Initialize TemplateManager & ConfigManager
        from models.template_manager import TemplateManager
        from models.config_manager import ConfigManager
        from services.plugin_server import PluginServer
        self.template_manager = TemplateManager(self.workspace_dir)
        self.config_manager = ConfigManager(self.workspace_dir)
        
        # Initialize PluginServer
        self.plugin_server = PluginServer(port=self.config_manager.plugin_server_port, parent=self)
        if self.config_manager.enable_plugin_server:
            self.plugin_server.start()
        
        self.init_ui()
        # Bind template, config manager & plugin server to detail panel
        self.detail_widget.set_template_manager(self.template_manager)
        self.detail_widget.set_config_manager(self.config_manager)
        self.detail_widget.set_plugin_server(self.plugin_server)
        
        self.plugin_server.client_connected_signal.connect(self.update_plugin_status_ui)
        self.plugin_server.client_disconnected_signal.connect(self.update_plugin_status_ui)
        self.plugin_server.client_updated_signal.connect(self.update_plugin_status_ui)
        self.plugin_server.alarm_detected_signal.connect(self.on_plugin_alarm_detected)
        self.update_plugin_status_ui()

        # Initialize Global Multi-Project Pipeline Scheduler
        self.pipeline_scheduler = PipelineScheduler(main_window=self, parent=self)
        self.pipeline_scheduler.pipeline_started_signal.connect(self.on_pipeline_started)
        self.pipeline_scheduler.pipeline_stopped_signal.connect(self.on_pipeline_stopped)
        self.pipeline_scheduler.pipeline_finished_signal.connect(self.on_pipeline_finished)
        self.pipeline_scheduler.project_switched_signal.connect(self.on_pipeline_project_switched)
        self.pipeline_scheduler.project_completed_signal.connect(self.on_pipeline_project_completed)
        self.pipeline_scheduler.points_exhausted_signal.connect(self.on_pipeline_points_exhausted)
        self.pipeline_scheduler.progress_updated_signal.connect(self.on_pipeline_progress_updated)
        
        self.load_initial_state()

    def init_ui(self):
        self.setWindowTitle("项目管理器 (Project Manager)")
        self.resize(1200, 800)
        self.setMinimumSize(1000, 600)
        
        # Warm and premium style theme
        self.setStyleSheet("""
            QMainWindow {
                background-color: #F5EBE6;
                font-family: "Segoe UI", "PingFang SC", sans-serif;
            }
            QWidget#central_widget {
                background-color: #F5EBE6;
            }
            QLabel {
                font-size: 13px;
                color: #5D4037;
                font-weight: bold;
            }
            QLineEdit {
                background-color: white;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                padding: 6px;
                color: #5D4037;
                font-size: 13px;
            }
            QPushButton {
                background-color: #E0A96D;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 14px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #D2904C;
            }
            QPushButton:pressed {
                background-color: #B87635;
            }
            QPushButton#btn_import {
                background-color: #E0A96D;
                font-size: 14px;
                padding: 8px 18px;
            }
            QPushButton#btn_import:hover {
                background-color: #D2904C;
            }
            QPushButton#btn_template_config {
                background-color: #D7CCC8;
                color: #5D4037;
                font-size: 13px;
                padding: 6px 14px;
            }
            QPushButton#btn_template_config:hover {
                background-color: #BCAAA4;
            }
            QListWidget {
                background-color: white;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                color: #5D4037;
                font-size: 13px;
                padding: 4px;
            }
            QListWidget::item {
                padding: 8px;
                border-bottom: 1px solid #EFEBE9;
                border-radius: 4px;
            }
            QListWidget::item:hover {
                background-color: #F5F5F5;
                color: #5D4037;
            }
            QListWidget::item:selected {
                background-color: #FFE0B2;
                color: #5D4037;
                font-weight: bold;
            }
        """)

        central_widget = QWidget()
        central_widget.setObjectName("central_widget")
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(12)
        
        # 1. Top Bar (Storage path & Import)
        top_layout = QHBoxLayout()
        top_layout.setSpacing(8)
        
        top_layout.addWidget(QLabel("存储路径 (Storage Path):"))
        
        self.txt_base_path = QLineEdit()
        self.txt_base_path.setReadOnly(True)
        self.txt_base_path.setPlaceholderText("请选择项目数据存放的总目录...")
        top_layout.addWidget(self.txt_base_path, stretch=1)
        
        self.btn_select_path = QPushButton("选择路径")
        self.btn_select_path.clicked.connect(self.select_base_path)
        top_layout.addWidget(self.btn_select_path)
        
        top_layout.addSpacing(20)
        
        self.btn_import = QPushButton("＋ 新建导入 (Import)")
        self.btn_import.setObjectName("btn_import")
        self.btn_import.clicked.connect(self.open_import_dialog)
        top_layout.addWidget(self.btn_import)
        
        top_layout.addSpacing(8)
        
        self.btn_template_config = QPushButton("⚙️ 模板配置")
        self.btn_template_config.setObjectName("btn_template_config")
        self.btn_template_config.clicked.connect(self.open_template_config_dialog)
        top_layout.addWidget(self.btn_template_config)
        
        top_layout.addSpacing(8)
        
        self.btn_rules_config = QPushButton("⚙️ 规则设置")
        self.btn_rules_config.setObjectName("btn_rules_config")
        self.btn_rules_config.clicked.connect(self.open_settings_dialog)
        top_layout.addWidget(self.btn_rules_config)
        
        top_layout.addSpacing(8)
        
        self.btn_batch_check_video = QPushButton("🔍 批量检查视频")
        self.btn_batch_check_video.setObjectName("btn_batch_check_video")
        self.btn_batch_check_video.setStyleSheet("background-color: #0284C7; color: white; font-weight: bold;")
        self.btn_batch_check_video.clicked.connect(self.open_batch_video_check_dialog)
        top_layout.addWidget(self.btn_batch_check_video)
        
        top_layout.addSpacing(8)
        
        self.btn_refresh_points = QPushButton("🔄 刷新点数")
        self.btn_refresh_points.setObjectName("btn_refresh_points")
        self.btn_refresh_points.setStyleSheet("""
            QPushButton#btn_refresh_points {
                background-color: #059669;
                color: white;
                font-size: 12px;
                font-weight: bold;
                padding: 4px 10px;
                border-radius: 4px;
            }
            QPushButton#btn_refresh_points:hover {
                background-color: #047857;
            }
        """)
        self.btn_refresh_points.setToolTip("向所有已连接的浏览器插件发送指令，模拟点击头像以获取最新真实点数")
        self.btn_refresh_points.clicked.connect(self.manual_refresh_plugin_points)
        top_layout.addWidget(self.btn_refresh_points)
        
        main_layout.addLayout(top_layout)
        
        # 2. Main Area (Splitter: Sidebar and Details)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Left Panel (Sidebar Container)
        sidebar_widget = QWidget()
        sidebar_layout = QVBoxLayout(sidebar_widget)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(6)
        
        # Pipeline Header & Actions Box (带实时生成监控看板)
        pipeline_box = QFrame()
        pipeline_box.setStyleSheet("background-color: #EDE0D4; border-radius: 6px; padding: 6px;")
        p_box_layout = QVBoxLayout(pipeline_box)
        p_box_layout.setContentsMargins(6, 6, 6, 6)
        p_box_layout.setSpacing(6)

        hdr_row = QHBoxLayout()
        hdr_row.addWidget(QLabel("<b>项目列表 (Projects)</b>"))
        hdr_row.addStretch()
        
        self.btn_select_all_proj = QPushButton("☑️ 全选")
        self.btn_select_all_proj.setStyleSheet("font-size: 11px; padding: 2px 6px;")
        self.btn_select_all_proj.clicked.connect(self.select_all_projects_for_pipeline)
        hdr_row.addWidget(self.btn_select_all_proj)

        self.btn_clear_all_proj = QPushButton("⏹️ 清空")
        self.btn_clear_all_proj.setStyleSheet("font-size: 11px; padding: 2px 6px;")
        self.btn_clear_all_proj.clicked.connect(self.deselect_all_projects_for_pipeline)
        hdr_row.addWidget(self.btn_clear_all_proj)
        p_box_layout.addLayout(hdr_row)

        self.btn_toggle_pipeline = QPushButton("🚀 启动全局无人值守流水线")
        self.btn_toggle_pipeline.setObjectName("btn_toggle_pipeline")
        self.btn_toggle_pipeline.setStyleSheet("""
            QPushButton#btn_toggle_pipeline {
                background-color: #059669;
                color: white;
                font-size: 12px;
                font-weight: bold;
                padding: 7px;
                border-radius: 4px;
            }
            QPushButton#btn_toggle_pipeline:hover {
                background-color: #047857;
            }
        """)
        self.btn_toggle_pipeline.clicked.connect(self.toggle_global_pipeline)
        p_box_layout.addWidget(self.btn_toggle_pipeline)

        # 实时生成监控看板 (HUD)
        self.pipeline_hud = QFrame()
        self.pipeline_hud.setStyleSheet("""
            QFrame {
                background-color: #FFFFFF;
                border: 1px solid #D7CCC8;
                border-radius: 6px;
                padding: 6px;
            }
            QProgressBar {
                border: 1px solid #E2E8F0;
                border-radius: 4px;
                text-align: center;
                font-size: 10px;
                font-weight: bold;
                color: #1E293B;
                background-color: #F1F5F9;
                height: 14px;
            }
            QProgressBar::chunk {
                background-color: #10B981;
                border-radius: 3px;
            }
        """)
        hud_layout = QVBoxLayout(self.pipeline_hud)
        hud_layout.setContentsMargins(6, 6, 6, 6)
        hud_layout.setSpacing(4)

        # 状态标题
        self.lbl_pipeline_status = QLabel("就绪：勾选项目后点击启动")
        self.lbl_pipeline_status.setStyleSheet("font-size: 11px; color: #4B5563; font-weight: bold; padding: 1px;")
        hud_layout.addWidget(self.lbl_pipeline_status)

        # 项目级进度条
        self.lbl_proj_pbar_title = QLabel("📦 工程总进度: 0 / 0")
        self.lbl_proj_pbar_title.setStyleSheet("font-size: 10px; color: #64748B; font-weight: normal;")
        hud_layout.addWidget(self.lbl_proj_pbar_title)

        self.pbar_projects = QProgressBar()
        self.pbar_projects.setRange(0, 100)
        self.pbar_projects.setValue(0)
        hud_layout.addWidget(self.pbar_projects)

        # 视频片段级进度条
        self.lbl_video_pbar_title = QLabel("🎬 当前工程视频: 0 / 0")
        self.lbl_video_pbar_title.setStyleSheet("font-size: 10px; color: #64748B; font-weight: normal;")
        hud_layout.addWidget(self.lbl_video_pbar_title)

        self.pbar_videos = QProgressBar()
        self.pbar_videos.setRange(0, 100)
        self.pbar_videos.setValue(0)
        self.pbar_videos.setStyleSheet("""
            QProgressBar::chunk {
                background-color: #8B5CF6;
            }
        """)
        hud_layout.addWidget(self.pbar_videos)

        # 详细数据指标
        self.lbl_pipeline_detail = QLabel("⚡ 在线 Worker: 0 | 剩余积分: 0")
        self.lbl_pipeline_detail.setStyleSheet("font-size: 10px; color: #475569; padding-top: 2px;")
        hud_layout.addWidget(self.lbl_pipeline_detail)

        p_box_layout.addWidget(self.pipeline_hud)

        sidebar_layout.addWidget(pipeline_box)

        self.list_projects = QListWidget()
        self.list_projects.itemClicked.connect(self.on_project_clicked)
        self.list_projects.itemDoubleClicked.connect(self.on_project_double_clicked)
        self.list_projects.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_projects.customContextMenuRequested.connect(self.show_project_context_menu)
        sidebar_layout.addWidget(self.list_projects)
        
        # Add delete button under the list
        self.btn_delete_project = QPushButton("🗑️ 删除选中项目")
        self.btn_delete_project.setObjectName("btn_delete_project")
        self.btn_delete_project.setStyleSheet("""
            QPushButton#btn_delete_project {
                background-color: #E57373;
                color: white;
            }
            QPushButton#btn_delete_project:hover {
                background-color: #EF5350;
            }
            QPushButton#btn_delete_project:pressed {
                background-color: #E53935;
            }
        """)
        self.btn_delete_project.clicked.connect(self.delete_selected_project)
        sidebar_layout.addWidget(self.btn_delete_project)
        
        sidebar_widget.setLayout(sidebar_layout)
        splitter.addWidget(sidebar_widget)
        
        # Right Panel (Detail Widget)
        self.detail_widget = ProjectDetailWidget()
        splitter.addWidget(self.detail_widget)
        
        # Set splitter proportions (approx 25% sidebar, 75% details)
        splitter.setSizes([300, 900])
        main_layout.addWidget(splitter, stretch=1)

    def load_initial_state(self):
        """Displays saved base path if it exists and loads projects list."""
        base_path = self.storage_manager.get_base_path()
        if base_path:
            self.txt_base_path.setText(str(base_path))
            self.reload_projects_list()
        else:
            self.txt_base_path.setText("")
            QMessageBox.information(self, "欢迎", "首次使用，请先点击 ［选择路径］ 设置数据存放的总目录！")

    def select_base_path(self):
        """Opens a folder selection dialog to set the base path."""
        dir_path = QFileDialog.getExistingDirectory(self, "选择总存储路径", str(self.workspace_dir))
        if dir_path:
            if self.storage_manager.set_base_path(dir_path):
                self.txt_base_path.setText(dir_path)
                self.reload_projects_list()
                QMessageBox.information(self, "成功", "总存储路径设置成功！")
            else:
                QMessageBox.critical(self, "错误", "无法使用该存储路径，请检查权限。")

    def reload_projects_list(self):
        """Fetches current projects and populates sidebar list widget with video completeness status colors."""
        self.list_projects.clear()
        
        projects = self.storage_manager.list_projects()
        base_path = self.storage_manager.get_base_path()
        from models.project_model import ProjectModel
        from services.video_checker import VideoChecker
        
        for p in projects:
            # Format list item label: {index} {col1} - {col7}
            label = f"●  {p['index_str']}   {p['col1']}"
            if p['col7']:
                label += f" - {p['col7']}"
                
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setData(Qt.ItemDataRole.UserRole, p['path'])
            item.setData(Qt.ItemDataRole.UserRole + 1, p)
            
            try:
                proj_model = ProjectModel(p['path'])
                report = VideoChecker.check_project_videos(proj_model, p['path'], base_storage_path=base_path)
                
                missing = report.get("missing_count", 0)
                pending = report.get("pending_count", 0)
                already = report.get("already_count", 0)
                rate = report.get("completion_rate", 0.0)
                
                # 规则：
                # 1. 缺少视频就显示红色
                # 2. 成功归位并且没有缺少视频就显示黄色
                # 3. 没有归位就显示默认颜色
                if missing > 0:
                    item.setForeground(QColor("#DC2626"))  # 红色
                    item.setToolTip(f"❌ 缺失 {missing} 个视频片段")
                elif rate >= 100.0 and pending == 0 and already > 0:
                    item.setForeground(QColor("#D97706"))  # 黄色
                    item.setToolTip("✅ 视频已全部归位且无缺失")
                elif pending > 0:
                    item.setForeground(QColor("#5D4037"))  # 默认褐色
                    item.setToolTip(f"⚠️ 包含 {pending} 个未归位视频")
                else:
                    item.setForeground(QColor("#5D4037"))  # 默认褐色
            except Exception as e:
                print(f"Error checking project status for item {p['id']}: {e}")
                item.setForeground(QColor("#5D4037"))
                
            self.list_projects.addItem(item)

    def open_import_dialog(self):
        """Opens the clipboard import dialog."""
        if not self.storage_manager.get_base_path():
            QMessageBox.warning(self, "错误", "请先设置总存储路径后再导入项目！")
            return
            
        dialog = ImportDialog(self.storage_manager, self)
        if dialog.exec() == ImportDialog.DialogCode.Accepted:
            self.reload_projects_list()

    def open_settings_dialog(self):
        """Opens rules & points settings dialog."""
        from views.settings_dialog import SettingsDialog
        dialog = SettingsDialog(self.config_manager, self)
        if dialog.exec() == SettingsDialog.DialogCode.Accepted:
            if hasattr(self, "detail_widget"):
                self.detail_widget.set_config_manager(self.config_manager)
                self.detail_widget.populate_segments_table()

    def on_project_clicked(self, item):
        """Triggers detail load when sidebar item is clicked."""
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            self.detail_widget.set_project(path)

    def on_project_double_clicked(self, item):
        """Copies the entire full project name (including index prefix and notes) to clipboard."""
        if not item:
            return
            
        import re
        full_name = item.text().replace("●", "").strip()
        full_name = re.sub(r' +', ' ', full_name)
        
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(full_name)
        QToolTip.showText(QCursor.pos(), f"已复制完整项目名称:\n{full_name}", self)

    def show_project_context_menu(self, pos):
        """Displays context menu for renaming, copying full name, or deleting project."""
        item = self.list_projects.itemAt(pos)
        if not item:
            return
            
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: white;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 20px 6px 10px;
                font-size: 13px;
                color: #5D4037;
            }
            QMenu::item:selected {
                background-color: #FFE0B2;
                border-radius: 3px;
            }
        """)
        
        act_rename = menu.addAction("✏️ 重命名项目 (Rename)")
        act_copy_name = menu.addAction("📋 复制完整项目名称 (Copy Full Name)")
        menu.addSeparator()
        act_delete = menu.addAction("🗑️ 删除项目 (Delete)")
        
        action = menu.exec(self.list_projects.mapToGlobal(pos))
        if action == act_rename:
            self.rename_project(item)
        elif action == act_copy_name:
            self.on_project_double_clicked(item)
        elif action == act_delete:
            self.delete_selected_project()

    def rename_project(self, item):
        """Opens dialog to rename all parts (Index, Name, Notes) of a project and updates storage and metadata."""
        project_path_str = item.data(Qt.ItemDataRole.UserRole)
        if not project_path_str:
            return
            
        path = Path(project_path_str)
        if not path.exists():
            return
            
        from models.project_model import ProjectModel
        try:
            model = ProjectModel(path)
            old_index = model.index
            old_name = model.col1_name
            old_notes = model.col7_notes
        except Exception as e:
            QMessageBox.critical(self, "错误", f"读取项目信息失败: {e}")
            return

        dialog = RenameProjectDialog(old_index, old_name, old_notes, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_index, new_name, new_notes = dialog.get_values()
            
            if not new_name:
                QMessageBox.warning(self, "警告", "项目名称不能为空！")
                return
                
            try:
                # Update model
                model.index = new_index
                model.col1_name = new_name
                model.col7_notes = new_notes
                model.save()
                
                # Format new folder name on disk
                invalid_chars = '<>:"/\\|?*'
                c1 = "".join(c for c in new_name if c not in invalid_chars).strip()[:50]
                c7 = "".join(c for c in new_notes if c not in invalid_chars).strip()[:50]
                
                new_dir_name = f"{new_index:02d}_{c1}_{c7}-flow"
                new_dir_path = path.parent / new_dir_name
                
                target_path = path
                if new_dir_path != path and not new_dir_path.exists():
                    try:
                        path.rename(new_dir_path)
                        target_path = new_dir_path
                        model.project_dir = new_dir_path
                        model.project_id = new_dir_name
                        model.save()
                    except Exception as e:
                        print(f"Directory rename failed, metadata updated: {e}")
                        
                # Reload project list
                self.reload_projects_list()
                
                # If detail_widget is currently displaying this project, update it
                if hasattr(self, "detail_widget"):
                    current_active = self.detail_widget.project_path
                    if current_active and (Path(current_active) == path or Path(current_active) == target_path):
                        self.detail_widget.set_project(target_path)
                        
                QMessageBox.information(self, "成功", "项目基本信息修改成功！")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"修改项目失败: {e}")

    def start_background_download(self, project_id, url, project_dir):
        """Starts an asynchronous background download of Google Drive link for a project."""
        if not url:
            return
            
        if project_id in self.active_downloads:
            return
            
        from services.downloader import DownloadThread
        downloads_dir = Path(project_dir) / "downloads"
        
        thread = DownloadThread(url, downloads_dir)
        self.active_downloads[project_id] = thread
        
        thread.status_signal.connect(
            lambda msg, pid=project_id: self.on_background_download_status(msg, pid)
        )
        thread.finished_signal.connect(
            lambda success, msg, pid=project_id: self.on_background_download_finished(success, msg, pid)
        )
        thread.finished.connect(thread.deleteLater)
        
        thread.start()

    def on_background_download_status(self, msg, project_id):
        """Dispatches status updates to detail widget if showing this project."""
        if self.detail_widget.project_model and self.detail_widget.project_model.project_id == project_id:
            self.detail_widget.on_download_status_updated(msg)

    def on_background_download_finished(self, success, msg, project_id):
        """Cleans up thread and updates project metadata and detail view."""
        self.active_downloads.pop(project_id, None)
        
        # Scan and update metadata files in project directory
        proj_path = self.storage_manager.resolve_path(project_id)
        if proj_path.exists():
            from models.project_model import ProjectModel
            try:
                proj = ProjectModel(proj_path)
                proj.update_media_files()
            except Exception as e:
                print(f"Error updating project files: {e}")
                
        # Notify detail widget if current project matches
        if self.detail_widget.project_model and self.detail_widget.project_model.project_id == project_id:
            self.detail_widget.on_download_finished(success, msg)

    def delete_selected_project(self):
        """Permanently deletes the selected project folder and files."""
        current_item = self.list_projects.currentItem()
        if not current_item:
            QMessageBox.warning(self, "提示", "请先在列表中选择要删除的项目！")
            return
            
        project_path_str = current_item.data(Qt.ItemDataRole.UserRole)
        project_path = Path(project_path_str)
        project_id = project_path.name
        
        # Confirmation Dialog
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要永久删除项目【{project_id}】吗？\n\n这将会永久删除该项目的文件夹及所有已下载的素材资源，此操作无法撤销！",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            # 1. Stop any active download thread first
            if project_id in self.active_downloads:
                thread = self.active_downloads.pop(project_id)
                if thread and thread.isRunning():
                    thread.stop()
            
            # 2. Delete the directory recursively
            import shutil
            try:
                if project_path.exists() and project_path.is_dir():
                    shutil.rmtree(project_path)
                
                # Delete corresponding subtitle file in "字幕" folder
                subtitles_dir = project_path.parent / "字幕"
                subtitle_file_path = subtitles_dir / f"{project_id}.txt"
                if subtitle_file_path.exists():
                    subtitle_file_path.unlink()
                
                # 3. If the deleted project is currently displayed, reset the detail view
                if self.detail_widget.project_model and self.detail_widget.project_model.project_id == project_id:
                    self.detail_widget.reset_to_no_selection()
                    
                # 4. Reload the sidebar
                self.reload_projects_list()
                QMessageBox.information(self, "成功", f"项目【{project_id}】已成功删除！")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"删除项目文件夹失败: {str(e)}")

    def open_template_config_dialog(self):
        """Opens the templates and motions configuration dialog."""
        from views.template_config_dialog import TemplateConfigDialog
        dialog = TemplateConfigDialog(self.template_manager, self)
        if dialog.exec() == TemplateConfigDialog.DialogCode.Accepted:
            # Refresh project details dropdowns if a project is loaded
            if self.detail_widget.project_model:
                self.detail_widget.refresh_template_comboboxes()

    def open_batch_video_check_dialog(self):
        """Opens batch video completeness dialog for all projects in storage_manager."""
        projects = self.storage_manager.list_projects()
        if not projects:
            QMessageBox.warning(self, "提示", "当前存储路径下没有找到任何项目！")
            return
            
        base_storage_path = self.storage_manager.get_base_path()
        from views.video_check_dialog import BatchVideoCheckDialog
        dialog = BatchVideoCheckDialog(projects, base_storage_path, self)
        dialog.exec()

    def update_plugin_status_ui(self, info=None):
        """Updates the plugin connection status."""
        if hasattr(self, "lbl_plugin_status"):
            if not hasattr(self, "plugin_server") or not self.plugin_server:
                self.lbl_plugin_status.setText("🔌 插件未连接")
                self.lbl_plugin_status.setStyleSheet("color: #64748B; font-size: 12px; font-weight: bold; padding: 4px 8px; border: 1px solid #CBD5E1; border-radius: 4px; background-color: #F8FAFC;")
                return
                
            clients = self.plugin_server.get_online_clients()
            count = len(clients)
            if count == 0:
                self.lbl_plugin_status.setText("🔴 插件未连接 (ws://127.0.0.1:18188)")
                self.lbl_plugin_status.setStyleSheet("color: #DC2626; font-size: 12px; font-weight: bold; padding: 4px 8px; border: 1px solid #FCA5A5; border-radius: 4px; background-color: #FEF2F2;")
            else:
                pts_summary = ", ".join(f"{(c.get('email') or c.get('client_id', '')).split('@')[0]}:{c.get('remaining_points', 0)}分" for c in clients[:3])
                if len(clients) > 3:
                    pts_summary += "..."
                text = f"🟢 插件在线: {count} 个 ({pts_summary})"
                self.lbl_plugin_status.setText(text)
                self.lbl_plugin_status.setStyleSheet("color: #059669; font-size: 12px; font-weight: bold; padding: 4px 8px; border: 1px solid #A7F3D0; border-radius: 4px; background-color: #ECFDF5;")

    def manual_refresh_plugin_points(self):
        """Broadcasts get_points RPC request to all connected browsers to probe points."""
        if not hasattr(self, "plugin_server") or not self.plugin_server:
            QMessageBox.warning(self, "提示", "插件服务未启动。")
            return

        clients = self.plugin_server.get_online_clients()
        if not clients:
            QMessageBox.information(self, "提示", "当前没有在线的浏览器插件。请先打开 Google Flow 网页。")
            return

        sent_count = self.plugin_server.query_all_clients_points()
        if hasattr(self, "lbl_plugin_status"):
            self.lbl_plugin_status.setText("⏳ 正在探测各浏览器最新点数...")
            self.lbl_plugin_status.setStyleSheet("color: #D97706; font-size: 12px; font-weight: bold; padding: 4px 8px; border: 1px solid #FCD34D; border-radius: 4px; background-color: #FEF3C7;")
            QTimer.singleShot(2500, self.update_plugin_status_ui)
        else:
            self.statusBar().showMessage(f"已向 {sent_count} 个浏览器发送探测点数指令...", 3000)

    def on_plugin_alarm_detected(self, alarm_info):
        """Handles safety / unusual activity limit notification from Google Flow plugin."""
        client_id = alarm_info.get("client_id", "")
        msg = alarm_info.get("message", "检测到 Google 安全限制（异常活动）")
        if hasattr(self, "lbl_plugin_status"):
            self.lbl_plugin_status.setText(f"🚨 {client_id} 安全风控挂起")
            self.lbl_plugin_status.setStyleSheet("color: #DC2626; font-size: 12px; font-weight: bold; padding: 4px 8px; border: 1px solid #DC2626; border-radius: 4px; background-color: #FEE2E2;")
        QMessageBox.warning(
            self, "Google 安全限制警报",
            f"收到浏览器 Worker 【{client_id}】的告警：\n\n{msg}\n\n"
            "建议：请切到该浏览器窗口查看并手动消除网页安全验证，或等待插件自动刷新重试。"
        )

    def select_all_projects_for_pipeline(self):
        """Checks all project items in sidebar list."""
        for i in range(self.list_projects.count()):
            item = self.list_projects.item(i)
            item.setCheckState(Qt.CheckState.Checked)

    def deselect_all_projects_for_pipeline(self):
        """Unchecks all project items in sidebar list."""
        for i in range(self.list_projects.count()):
            item = self.list_projects.item(i)
            item.setCheckState(Qt.CheckState.Unchecked)

    def toggle_global_pipeline(self):
        """Starts or stops the multi-project automated pipeline."""
        if self.pipeline_scheduler.is_running:
            self.pipeline_scheduler.stop()
            return

        # Gather checked projects from sidebar list
        checked_projects = []
        for i in range(self.list_projects.count()):
            item = self.list_projects.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                p_data = item.data(Qt.ItemDataRole.UserRole + 1)
                if p_data:
                    checked_projects.append(p_data)

        if not checked_projects:
            QMessageBox.warning(self, "提示", "请先在项目列表中勾选至少一个要生成的项目！")
            return

        clients = self.plugin_server.get_online_clients() if self.plugin_server else []
        if not clients:
            QMessageBox.warning(self, "提示", "当前没有在线的浏览器 Worker。请先打开 Google Flow 网页。")
            return

        self.pipeline_scheduler.set_queue(checked_projects)
        self.pipeline_scheduler.start()

    def on_pipeline_started(self, total_count):
        """UI updates when global pipeline starts."""
        self.btn_toggle_pipeline.setText("⏸️ 暂停全局流水线")
        self.btn_toggle_pipeline.setStyleSheet("""
            QPushButton#btn_toggle_pipeline {
                background-color: #DC2626;
                color: white;
                font-size: 12px;
                font-weight: bold;
                padding: 7px;
                border-radius: 4px;
            }
            QPushButton#btn_toggle_pipeline:hover {
                background-color: #B91C1C;
            }
        """)
        self.lbl_pipeline_status.setText(f"🚀 流水线启动，共排队 {total_count} 个工程")
        self.lbl_pipeline_status.setStyleSheet("font-size: 11px; color: #059669; font-weight: bold; padding: 1px;")
        self.pbar_projects.setMaximum(max(1, total_count))
        self.pbar_projects.setValue(0)
        self.lbl_proj_pbar_title.setText(f"📦 全局工程: 0 / {total_count}")

    def on_pipeline_stopped(self):
        """UI updates when global pipeline stops."""
        self.btn_toggle_pipeline.setText("🚀 启动全局无人值守流水线")
        self.btn_toggle_pipeline.setStyleSheet("""
            QPushButton#btn_toggle_pipeline {
                background-color: #059669;
                color: white;
                font-size: 12px;
                font-weight: bold;
                padding: 7px;
                border-radius: 4px;
            }
            QPushButton#btn_toggle_pipeline:hover {
                background-color: #047857;
            }
        """)
        self.lbl_pipeline_status.setText("⏸️ 流水线已暂停")
        self.lbl_pipeline_status.setStyleSheet("font-size: 11px; color: #DC2626; font-weight: bold; padding: 1px;")
        self.setWindowTitle("项目管理器 (Project Manager)")

    def on_pipeline_project_switched(self, proj_name, current_idx, total_count):
        """UI updates when pipeline advances to next project."""
        self.lbl_pipeline_status.setText(f"⚡ 正在生成 [{current_idx}/{total_count}]: {proj_name}")
        self.lbl_pipeline_status.setStyleSheet("font-size: 11px; color: #2563EB; font-weight: bold; padding: 1px;")
        self.lbl_proj_pbar_title.setText(f"📦 全局工程: 第 {current_idx}/{total_count} 个")
        self.pbar_projects.setValue(current_idx - 1)

    def on_pipeline_progress_updated(self, proj_name, cur_proj_idx, total_projs, completed_vids, total_vids, pool_pts):
        """Real-time UI update callback when video progress changes."""
        # 1. Update project-level progress bar
        proj_pct = int(cur_proj_idx / max(1, total_projs) * 100)
        self.lbl_proj_pbar_title.setText(f"📦 全局工程: 第 {cur_proj_idx}/{total_projs} 个 ({proj_pct}%)")
        self.pbar_projects.setMaximum(max(1, total_projs))
        self.pbar_projects.setValue(cur_proj_idx)

        # 2. Update video-level progress bar
        vid_pct = int(completed_vids / max(1, total_vids) * 100) if total_vids > 0 else 0
        self.lbl_video_pbar_title.setText(f"🎬 当前工程视频: 第 {completed_vids}/{total_vids} 个 ({vid_pct}%)")
        self.pbar_videos.setMaximum(max(1, total_vids))
        self.pbar_videos.setValue(completed_vids)

        # 3. Update main status label
        self.lbl_pipeline_status.setText(f"⚡ 正在生成 [{cur_proj_idx}/{total_projs}]: {proj_name}")
        self.lbl_pipeline_status.setStyleSheet("font-size: 11px; color: #2563EB; font-weight: bold; padding: 1px;")

        # 4. Update online workers & points info
        workers_count = len(self.plugin_server.get_online_clients()) if self.plugin_server else 0
        self.lbl_pipeline_detail.setText(f"🌐 Worker: {workers_count} 在线 | ⚡ 剩余积分: {pool_pts} pts")

        # 5. Update window title
        self.setWindowTitle(f"项目管理器 - [全局生成 {cur_proj_idx}/{total_projs} 工程 | 视频 {completed_vids}/{total_vids}]")

    def on_pipeline_project_completed(self, proj_name, project_idx):
        """UI updates when a project in queue is 100% finished."""
        self.reload_projects_list()

    def on_pipeline_finished(self, completed_count, total_count):
        """UI notification when entire queue completes."""
        self.on_pipeline_stopped()
        self.reload_projects_list()
        self.pbar_projects.setValue(total_count)
        self.pbar_videos.setValue(self.pbar_videos.maximum())
        self.lbl_proj_pbar_title.setText(f"📦 全局工程: {completed_count}/{total_count} 全部完成 (100%)")
        self.lbl_video_pbar_title.setText("🎬 所有视频已全部就绪 (100%)")
        self.lbl_pipeline_status.setText(f"🎉 全部完成！共成功跑完 {completed_count}/{total_count} 个工程")
        self.lbl_pipeline_status.setStyleSheet("font-size: 11px; color: #059669; font-weight: bold; padding: 1px;")
        QMessageBox.information(self, "流水线全部完成", f"🎉 恭喜！排队的 {completed_count} 个工程已全部 100% 生成并自动标绿归档！")

    def on_pipeline_points_exhausted(self, total_pts):
        """UI notification when all workers run out of credits."""
        self.on_pipeline_stopped()
        QMessageBox.warning(
            self, "浏览器点数已榨干",
            f"⚠️ 所有在线浏览器的可用点数已全部消耗完毕 (总点数剩余 {total_pts} 点，不足以支付下一个片段)。\n\n"
            "全局流水线已安全挂起并自动保存所有已完成的工程。"
        )

    def select_project_by_info(self, proj_info):
        """Selects and opens project in UI given its info dict."""
        target_path = proj_info.get("path") if isinstance(proj_info, dict) else str(proj_info)
        for i in range(self.list_projects.count()):
            item = self.list_projects.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == target_path:
                self.list_projects.setCurrentItem(item)
                self.detail_widget.set_project(target_path)
                break

    def closeEvent(self, event):
        """Clean up background tasks, plugin server, and media players before quitting."""
        if hasattr(self, "plugin_server") and self.plugin_server:
            try:
                self.plugin_server.stop()
            except Exception:
                pass
                
        if hasattr(self, "active_downloads"):
            for project_id, thread in list(self.active_downloads.items()):
                if thread and thread.isRunning():
                    thread.stop()
            self.active_downloads.clear()
            
        if hasattr(self, "detail_widget") and self.detail_widget:
            if hasattr(self.detail_widget, "cleanup"):
                self.detail_widget.cleanup()
                
        super().closeEvent(event)


