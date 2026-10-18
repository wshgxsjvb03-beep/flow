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

        self.load_initial_state()

    def init_ui(self):
        from version import __version__
        self.setWindowTitle(f"Flow v{__version__}")
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
        
        self.btn_batch_rename_images = QPushButton("🔄 命名所有图片")
        self.btn_batch_rename_images.setObjectName("btn_batch_rename_images")
        self.btn_batch_rename_images.setStyleSheet("background-color: #6366F1; color: white; font-weight: bold;")
        self.btn_batch_rename_images.setToolTip("为所有项目里的图片按照规则（前7位字符+序号）自动重命名")
        self.btn_batch_rename_images.clicked.connect(self.batch_rename_all_images)
        top_layout.addWidget(self.btn_batch_rename_images)
        
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

        from PyQt6.QtWidgets import QTabWidget
        self.main_tab_widget = QTabWidget()
        self.main_tab_widget.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #D7CCC8; border-radius: 4px; background-color: #F5EBE6; }
            QTabBar::tab {
                background-color: #EDE0D4; color: #5D4037; font-size: 13px; font-weight: bold;
                padding: 8px 20px; border: 1px solid #D7CCC8; border-bottom: none;
                border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px;
            }
            QTabBar::tab:selected { background-color: #F5EBE6; border-bottom: 2px solid #E0A96D; }
            QTabBar::tab:hover { background-color: #FFE0B2; }
        """)
        self.main_tab_widget.addTab(splitter, "📋 项目管理")

        from views.batch_generate_tab import BatchGenerateTabWidget
        self.batch_generate_tab = BatchGenerateTabWidget(self.plugin_server, self)
        self.main_tab_widget.addTab(self.batch_generate_tab, "🚀 批量生成")

        from views.hosted_mode_widget import HostedModeWidget
        self.hosted_mode = HostedModeWidget(self.plugin_server, self)
        self.main_tab_widget.addTab(self.hosted_mode, "🤖 全局托管")
        self.account_monitor = None
        main_layout.addWidget(self.main_tab_widget, stretch=1)

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
                proj.rename_images()
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
                base = self.storage_manager.base_path.resolve() if self.storage_manager.base_path else None
                resolved_target = project_path.resolve()
                if not base or not resolved_target.is_relative_to(base) or resolved_target == base:
                    QMessageBox.critical(self, "错误", "安全拦截：目标路径不在有效工程根目录内，已中止删除！")
                    return

                if resolved_target.exists() and resolved_target.is_dir():
                    shutil.rmtree(resolved_target)
                
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

    def select_project_by_info(self, proj_info):
        """Selects and opens project in UI given its info dict."""
        target_path = proj_info.get("path") if isinstance(proj_info, dict) else str(proj_info)
        for i in range(self.list_projects.count()):
            item = self.list_projects.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == target_path:
                self.list_projects.setCurrentItem(item)
                self.detail_widget.set_project(target_path)
                break

    def batch_rename_all_images(self):
        """Iterates through all projects and auto-renames their images based on the global sequential rule."""
        projects = self.storage_manager.list_projects()
        if not projects:
            QMessageBox.information(self, "提示", "当前没有项目。")
            return
            
        # Sort projects by their natural index so numbering flows correctly
        try:
            projects.sort(key=lambda p: int(p.get("index_str", "0")))
        except Exception:
            projects.sort(key=lambda p: p.get("id", ""))
            
        reply = QMessageBox.question(
            self, "确认批量重命名",
            "是否要为所有项目自动重命名里面的图片？\n\n(规则：将所有项目视为一个整体，依次命名为 1.jpg, 2.jpg...)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            from models.project_model import ProjectModel
            total_renamed = 0
            current_idx = 1
            for p in projects:
                proj_path = self.storage_manager.resolve_path(p["id"])
                try:
                    proj = ProjectModel(proj_path)
                    renamed, current_idx = proj.rename_images(start_idx=current_idx, return_next_idx=True)
                    total_renamed += renamed
                except Exception as e:
                    print(f"Failed to rename project {p['id']}: {e}")
                    
            # Refresh current project detail if needed
            current_item = self.list_projects.currentItem()
            if current_item:
                self.on_project_clicked(current_item)
            QMessageBox.information(self, "完成", f"批量重命名完成，共重命名了 {total_renamed} 张图片！")

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


