# -*- coding: utf-8 -*-
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QListWidget, QListWidgetItem, QLabel, QLineEdit, 
                             QTextEdit, QTabWidget, QWidget, QMessageBox, QSplitter,
                             QFileDialog)
from PyQt6.QtCore import Qt
import uuid

class TemplateConfigDialog(QDialog):
    """Dialog for managing prompt templates and camera motion presets."""
    
    def __init__(self, template_manager, parent=None):
        super().__init__(parent)
        self.tm = template_manager
        self.init_ui()
        self.load_data()

    def init_ui(self):
        self.setWindowTitle("模板与运镜配置 (Templates & Motions Config)")
        self.resize(850, 550)
        
        # Apply stylesheet matching the warm theme
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
            QLineEdit, QTextEdit {
                background-color: white;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                padding: 6px;
                color: #3E2723;
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
            QPushButton#btn_delete {
                background-color: #E57373;
            }
            QPushButton#btn_delete:hover {
                background-color: #EF5350;
            }
            QPushButton#btn_reset {
                background-color: #B0BEC5;
                color: #37474F;
            }
            QPushButton#btn_reset:hover {
                background-color: #90A4AE;
            }
            QListWidget {
                background-color: white;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                color: #5D4037;
            }
            QListWidget::item {
                padding: 8px;
                border-bottom: 1px solid #EFEBE9;
            }
            QListWidget::item:selected {
                background-color: #FFE0B2;
                color: #5D4037;
                font-weight: bold;
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

        layout = QVBoxLayout(self)
        
        self.tabs = QTabWidget()
        
        # 1. Setup Prompt Templates Tab
        self.init_templates_tab()
        
        # 2. Setup Camera Motions Tab
        self.init_motions_tab()
        self.init_batch_templates_tab()
        
        layout.addWidget(self.tabs)
        
        # Bottom Action Buttons
        btn_bottom_layout = QHBoxLayout()
        
        self.btn_export = QPushButton("📤 导出配置")
        self.btn_export.clicked.connect(self.export_config)
        self.btn_export.setStyleSheet("background-color: #8D6E63; color: white;")
        
        self.btn_import = QPushButton("📥 导入配置")
        self.btn_import.clicked.connect(self.import_config)
        self.btn_import.setStyleSheet("background-color: #8D6E63; color: white;")
        
        btn_bottom_layout.addWidget(self.btn_export)
        btn_bottom_layout.addWidget(self.btn_import)
        
        btn_bottom_layout.addStretch()
        
        self.btn_close = QPushButton("关闭")
        self.btn_close.clicked.connect(self.accept)
        btn_bottom_layout.addWidget(self.btn_close)
        
        layout.addLayout(btn_bottom_layout)

    def init_templates_tab(self):
        tab = QWidget()
        layout = QHBoxLayout(tab)
        
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Left sidebar: List & New/Delete Buttons
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        left_layout.addWidget(QLabel("已保存的提示词模板:"))
        self.list_templates = QListWidget()
        self.list_templates.currentRowChanged.connect(self.on_template_selected)
        left_layout.addWidget(self.list_templates)
        
        btn_left_layout = QHBoxLayout()
        self.btn_new_tpl = QPushButton("＋ 新建")
        self.btn_new_tpl.clicked.connect(self.new_template)
        
        self.btn_delete_tpl = QPushButton("🗑️ 删除")
        self.btn_delete_tpl.setObjectName("btn_delete")
        self.btn_delete_tpl.clicked.connect(self.delete_template)
        
        self.btn_reset_tpl = QPushButton("🔄 重置默认")
        self.btn_reset_tpl.setObjectName("btn_reset")
        self.btn_reset_tpl.clicked.connect(self.reset_templates)
        
        btn_left_layout.addWidget(self.btn_new_tpl)
        btn_left_layout.addWidget(self.btn_delete_tpl)
        btn_left_layout.addWidget(self.btn_reset_tpl)
        left_layout.addLayout(btn_left_layout)
        
        left_widget.setLayout(left_layout)
        splitter.addWidget(left_widget)
        
        # Right edit panel
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        right_layout.addWidget(QLabel("模板名称:"))
        self.txt_tpl_name = QLineEdit()
        right_layout.addWidget(self.txt_tpl_name)
        
        right_layout.addWidget(QLabel("模板内容 (必须包含 {spanish_text} 和 {camera_motion} 占位符):"))
        self.txt_tpl_content = QTextEdit()
        right_layout.addWidget(self.txt_tpl_content)
        
        save_layout = QHBoxLayout()
        save_layout.addStretch()
        self.btn_save_tpl = QPushButton("💾 保存模板")
        self.btn_save_tpl.clicked.connect(self.save_template)
        save_layout.addWidget(self.btn_save_tpl)
        right_layout.addLayout(save_layout)
        
        right_widget.setLayout(right_layout)
        splitter.addWidget(right_widget)
        
        splitter.setSizes([300, 550])
        layout.addWidget(splitter)
        self.tabs.addTab(tab, "📝 提示词模板")

    def init_motions_tab(self):
        tab = QWidget()
        layout = QHBoxLayout(tab)
        
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Left sidebar
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        left_layout.addWidget(QLabel("已保存的运镜预设:"))
        self.list_motions = QListWidget()
        self.list_motions.currentRowChanged.connect(self.on_motion_selected)
        left_layout.addWidget(self.list_motions)
        
        btn_left_layout = QHBoxLayout()
        self.btn_new_motion = QPushButton("＋ 新建")
        self.btn_new_motion.clicked.connect(self.new_motion)
        
        self.btn_delete_motion = QPushButton("🗑️ 删除")
        self.btn_delete_motion.setObjectName("btn_delete")
        self.btn_delete_motion.clicked.connect(self.delete_motion)
        
        self.btn_reset_motion = QPushButton("🔄 重置默认")
        self.btn_reset_motion.setObjectName("btn_reset")
        self.btn_reset_motion.clicked.connect(self.reset_motions)
        
        btn_left_layout.addWidget(self.btn_new_motion)
        btn_left_layout.addWidget(self.btn_delete_motion)
        btn_left_layout.addWidget(self.btn_reset_motion)
        left_layout.addLayout(btn_left_layout)
        
        left_widget.setLayout(left_layout)
        splitter.addWidget(left_widget)
        
        # Right edit panel
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        right_layout.addWidget(QLabel("运镜预设名称:"))
        self.txt_motion_name = QLineEdit()
        right_layout.addWidget(self.txt_motion_name)
        
        right_layout.addWidget(QLabel("运镜描述内容:"))
        self.txt_motion_content = QTextEdit()
        right_layout.addWidget(self.txt_motion_content)
        
        save_layout = QHBoxLayout()
        save_layout.addStretch()
        self.btn_save_motion = QPushButton("💾 保存预设")
        self.btn_save_motion.clicked.connect(self.save_motion)
        save_layout.addWidget(self.btn_save_motion)
        right_layout.addLayout(save_layout)
        
        right_widget.setLayout(right_layout)
        splitter.addWidget(right_widget)
        
        splitter.setSizes([300, 550])
        layout.addWidget(splitter)
        self.tabs.addTab(tab, "🎥 运镜预设")

    def load_data(self):
        if hasattr(self, "list_batch"):
            self.list_batch.clear()
            for t in self.tm.batch_templates:
                self.list_batch.addItem(t.get("name", "未命名批量模板"))
        """Loads items from template manager into widgets."""
        # Load templates
        self.list_templates.clear()
        for t in self.tm.templates:
            item = QListWidgetItem(t["name"])
            item.setData(Qt.ItemDataRole.UserRole, t["id"])
            self.list_templates.addItem(item)
            
        # Load motions
        self.list_motions.clear()
        for m in self.tm.motions:
            item = QListWidgetItem(m["name"])
            item.setData(Qt.ItemDataRole.UserRole, m["id"])
            self.list_motions.addItem(item)

        # Select first items by default
        if self.list_templates.count() > 0:
            self.list_templates.setCurrentRow(0)
        if self.list_motions.count() > 0:
            self.list_motions.setCurrentRow(0)

    # --- Template Handlers ---
    def on_template_selected(self, row):
        if row < 0:
            self.txt_tpl_name.clear()
            self.txt_tpl_content.clear()
            return
            
        item = self.list_templates.item(row)
        tpl_id = item.data(Qt.ItemDataRole.UserRole)
        tpl = self.tm.get_template(tpl_id)
        if tpl:
            self.txt_tpl_name.setText(tpl["name"])
            self.txt_tpl_content.setText(tpl["content"])

    def new_template(self):
        new_id = f"tpl_{uuid.uuid4().hex[:8]}"
        new_tpl = {
            "id": new_id,
            "name": "未命名提示词模板",
            "content": "这里是您的提示词模板，包含占位符 {spanish_text} 和 {camera_motion}。"
        }
        self.tm.templates.append(new_tpl)
        
        # Add to list
        item = QListWidgetItem(new_tpl["name"])
        item.setData(Qt.ItemDataRole.UserRole, new_id)
        self.list_templates.addItem(item)
        self.list_templates.setCurrentItem(item)
        self.txt_tpl_name.setFocus()

    def delete_template(self):
        row = self.list_templates.currentRow()
        if row < 0:
            return
            
        item = self.list_templates.item(row)
        tpl_id = item.data(Qt.ItemDataRole.UserRole)
        
        reply = QMessageBox.question(self, "确认删除", "确定要删除该提示词模板吗？",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.tm.templates = [t for t in self.tm.templates if t["id"] != tpl_id]
            self.tm.save_templates()
            self.list_templates.takeItem(row)

    def save_template(self):
        row = self.list_templates.currentRow()
        if row < 0:
            return
            
        name = self.txt_tpl_name.text().strip()
        content = self.txt_tpl_content.toPlainText().strip()
        
        if not name:
            QMessageBox.warning(self, "错误", "模板名称不能为空。")
            return
            
        if "{spanish_text}" not in content:
            QMessageBox.warning(self, "警告", "提示词模板内容必须包含 {spanish_text} 占位符。")
            return

        item = self.list_templates.item(row)
        tpl_id = item.data(Qt.ItemDataRole.UserRole)
        
        # Update model
        for t in self.tm.templates:
            if t["id"] == tpl_id:
                t["name"] = name
                t["content"] = content
                break
                
        # Save to file
        if self.tm.save_templates():
            # Update list display name
            item.setText(name)
            QMessageBox.information(self, "成功", "提示词模板保存成功！")
        else:
            QMessageBox.critical(self, "错误", "模板保存失败。")

    # --- Motion Handlers ---
    def on_motion_selected(self, row):
        if row < 0:
            self.txt_motion_name.clear()
            self.txt_motion_content.clear()
            return
            
        item = self.list_motions.item(row)
        motion_id = item.data(Qt.ItemDataRole.UserRole)
        motion = self.tm.get_motion(motion_id)
        if motion:
            self.txt_motion_name.setText(motion["name"])
            self.txt_motion_content.setText(motion["content"])

    def new_motion(self):
        new_id = f"motion_{uuid.uuid4().hex[:8]}"
        new_mot = {
            "id": new_id,
            "name": "未命名运镜预设",
            "content": "运镜细节描述文本"
        }
        self.tm.motions.append(new_mot)
        
        item = QListWidgetItem(new_mot["name"])
        item.setData(Qt.ItemDataRole.UserRole, new_id)
        self.list_motions.addItem(item)
        self.list_motions.setCurrentItem(item)
        self.txt_motion_name.setFocus()

    def delete_motion(self):
        row = self.list_motions.currentRow()
        if row < 0:
            return
            
        item = self.list_motions.item(row)
        motion_id = item.data(Qt.ItemDataRole.UserRole)
        
        reply = QMessageBox.question(self, "确认删除", "确定要删除该运镜预设吗？",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.tm.motions = [m for m in self.tm.motions if m["id"] != motion_id]
            self.tm.save_motions()
            self.list_motions.takeItem(row)

    def save_motion(self):
        row = self.list_motions.currentRow()
        if row < 0:
            return
            
        name = self.txt_motion_name.text().strip()
        content = self.txt_motion_content.toPlainText().strip()
        
        if not name:
            QMessageBox.warning(self, "错误", "预设名称不能为空。")
            return

        item = self.list_motions.item(row)
        motion_id = item.data(Qt.ItemDataRole.UserRole)
        
        for m in self.tm.motions:
            if m["id"] == motion_id:
                m["name"] = name
                m["content"] = content
                break
                
        if self.tm.save_motions():
            item.setText(name)
            QMessageBox.information(self, "成功", "运镜预设保存成功！")
        else:
            QMessageBox.critical(self, "错误", "运镜保存失败。")

    def reset_templates(self):
        """Resets all prompt templates to defaults after confirmation."""
        reply = QMessageBox.question(
            self, "确认重置",
            "确定要将所有提示词模板重置为默认值吗？这将会覆盖您当前所有的模板修改并删除自定义模板！",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.tm.init_default_templates()
            self.load_data()
            QMessageBox.information(self, "重置成功", "已恢复默认提示词模板！")

    def reset_motions(self):
        """Resets all camera motions to defaults after confirmation."""
        reply = QMessageBox.question(
            self, "确认重置",
            "确定要将所有运镜预设重置为默认值吗？这将会覆盖您当前所有的预设修改并删除自定义预设！",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.tm.init_default_motions()
            self.load_data()
            QMessageBox.information(self, "重置成功", "已恢复默认运镜预设！")

    def export_config(self):
        """Exports both templates and motions to a selected JSON file."""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出模板与运镜配置", "flow_templates_config.json", "JSON Files (*.json)"
        )
        if file_path:
            success, msg = self.tm.export_all(file_path)
            if success:
                QMessageBox.information(self, "导出成功", "模板与运镜配置已成功导出！")
            else:
                QMessageBox.critical(self, "导出失败", msg)

    def import_config(self):
        """Imports both templates and motions from a selected JSON file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "导入模板与运镜配置", "", "JSON Files (*.json)"
        )
        if file_path:
            reply = QMessageBox.question(
                self, "确认导入",
                "导入配置将会覆盖当前的模板和运镜设置，是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                success, msg = self.tm.import_all(file_path)
                if success:
                    self.load_data()  # Refresh UI
                    QMessageBox.information(self, "导入成功", "模板与运镜配置已成功导入！")
                else:
                    QMessageBox.critical(self, "导入失败", msg)

    def init_batch_templates_tab(self):
        tab = QWidget()
        layout = QHBoxLayout(tab)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("已保存的批量模板:"))
        self.list_batch = QListWidget()
        self.list_batch.currentRowChanged.connect(self.on_batch_selected)
        left_layout.addWidget(self.list_batch)
        
        btn_left_layout = QHBoxLayout()
        self.btn_new_batch = QPushButton("＋ 新建")
        self.btn_new_batch.clicked.connect(self.new_batch_template)
        self.btn_delete_batch = QPushButton("🗑️ 删除")
        self.btn_delete_batch.setObjectName("btn_delete")
        self.btn_delete_batch.clicked.connect(self.delete_batch_template)
        
        btn_left_layout.addWidget(self.btn_new_batch)
        btn_left_layout.addWidget(self.btn_delete_batch)
        left_layout.addLayout(btn_left_layout)
        splitter.addWidget(left_widget)
        
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(QLabel("批量模板名称:"))
        self.txt_batch_name = QLineEdit()
        right_layout.addWidget(self.txt_batch_name)
        right_layout.addWidget(QLabel("模板内容:"))
        self.txt_batch_content = QTextEdit()
        right_layout.addWidget(self.txt_batch_content)
        
        save_layout = QHBoxLayout()
        save_layout.addStretch()
        self.btn_save_batch = QPushButton("💾 保存批量模板")
        self.btn_save_batch.clicked.connect(self.save_batch_template)
        save_layout.addWidget(self.btn_save_batch)
        right_layout.addLayout(save_layout)
        
        splitter.addWidget(right_widget)
        splitter.setSizes([300, 550])
        layout.addWidget(splitter)
        self.tabs.addTab(tab, "🚀 批量模板")

    def on_batch_selected(self, row):
        if row < 0 or row >= len(self.tm.batch_templates):
            self.txt_batch_name.clear()
            self.txt_batch_content.clear()
            return
        tpl = self.tm.batch_templates[row]
        self.txt_batch_name.setText(tpl.get("name", ""))
        self.txt_batch_content.setPlainText(tpl.get("content", ""))

    def new_batch_template(self):
        import uuid
        new_tpl = {
            "id": "bt-" + uuid.uuid4().hex[:8],
            "name": "新建批量模板",
            "content": "在此输入批量生成提示词..."
        }
        self.tm.batch_templates.append(new_tpl)
        self.tm.save_batch_templates()
        self.load_data()
        self.list_batch.setCurrentRow(len(self.tm.batch_templates) - 1)

    def delete_batch_template(self):
        row = self.list_batch.currentRow()
        if row < 0 or row >= len(self.tm.batch_templates):
            return
        reply = QMessageBox.question(self, "确认删除", "是否确定删除该批量模板？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.tm.batch_templates.pop(row)
            self.tm.save_batch_templates()
            self.load_data()

    def save_batch_template(self):
        row = self.list_batch.currentRow()
        if row < 0 or row >= len(self.tm.batch_templates):
            QMessageBox.warning(self, "未选择", "请先在左侧选择要保存的批量模板。")
            return
        
        name = self.txt_batch_name.text().strip()
        if not name:
            QMessageBox.warning(self, "名称为空", "批量模板名称不能为空。")
            return
            
        self.tm.batch_templates[row]["name"] = name
        self.tm.batch_templates[row]["content"] = self.txt_batch_content.toPlainText()
        self.tm.save_batch_templates()
        
        self.load_data()
        self.list_batch.setCurrentRow(row)
        QMessageBox.information(self, "成功", "批量模板已保存！")
