# -*- coding: utf-8 -*-
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QSpinBox, QTableWidget, QTableWidgetItem, 
                             QHeaderView, QMessageBox, QGroupBox, QAbstractItemView, 
                             QLineEdit, QComboBox, QTextEdit, QScrollArea, QWidget)
from PyQt6.QtCore import Qt

class SettingsDialog(QDialog):
    """Dialog for configuring app-wide rules (batch points, duration rules, points rules)."""
    
    def __init__(self, config_manager, parent=None):
        super().__init__(parent)
        self.cm = config_manager
        if self.cm:
            self.cm.load()
        self.init_ui()
        self.load_data()

    def init_ui(self):
        self.setWindowTitle("⚙️ 系统规则与积分设置 (Rules & Points Settings)")
        self.resize(680, 750)
        
        self.setStyleSheet("""
            QDialog {
                background-color: #FAF6F0;
                color: #5D4037;
                font-family: "Segoe UI", sans-serif;
            }
            QGroupBox {
                font-weight: bold;
                font-size: 13px;
                border: 1px solid #D7CCC8;
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 15px;
                background-color: white;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 5px;
                color: #5D4037;
            }
            QLabel {
                font-size: 13px;
                color: #5D4037;
            }
            QSpinBox {
                background-color: white;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 13px;
            }
            QTableWidget {
                background-color: white;
                border: 1px solid #EFEBE9;
                border-radius: 4px;
                font-size: 12px;
            }
            QHeaderView::section {
                background-color: #EFEBE9;
                color: #5D4037;
                font-weight: bold;
                padding: 4px;
                border: 1px solid #D7CCC8;
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
            QPushButton#btn_reset {
                background-color: #B0BEC5;
                color: #37474F;
            }
            QPushButton#btn_reset:hover {
                background-color: #90A4AE;
            }
        """)
        
        # Use a scroll area so the dialog doesn't overflow on small screens
        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("QScrollArea { border: none; background-color: #FAF6F0; }")
        scroll_content = QWidget()
        main_layout = QVBoxLayout(scroll_content)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(12)
        
        # Section 1: Batch Points Budget & Forced Split Marker
        group_points = QGroupBox("1. 单批次最高积分上限与强制断句标记 (Batch Settings)")
        pts_layout = QHBoxLayout(group_points)
        pts_layout.setContentsMargins(12, 12, 12, 12)
        
        pts_layout.addWidget(QLabel("每批次导出上限:"))
        self.spin_max_points = QSpinBox()
        self.spin_max_points.setRange(1, 1000)
        self.spin_max_points.setSuffix(" 积分")
        pts_layout.addWidget(self.spin_max_points)
        
        pts_layout.addSpacing(15)
        
        pts_layout.addWidget(QLabel("强制断句标记:"))
        self.txt_marker = QLineEdit()
        self.txt_marker.setFixedWidth(70)
        self.txt_marker.setPlaceholderText("///")
        pts_layout.addWidget(self.txt_marker)
        
        lbl_hint = QLabel("(* 出现此标记处强制切断)")
        lbl_hint.setStyleSheet("color: #8D6E63; font-style: italic; font-size: 11px;")
        pts_layout.addWidget(lbl_hint, stretch=1)
        
        main_layout.addWidget(group_points)
        
        # Section 2: Character count -> Duration rules
        group_char_dur = QGroupBox("2. 字符数与时长对应规则 (Char Count -> Seconds)")
        char_layout = QVBoxLayout(group_char_dur)
        char_layout.setContentsMargins(12, 12, 12, 12)
        
        self.table_char_dur = QTableWidget()
        self.table_char_dur.setColumnCount(2)
        self.table_char_dur.setHorizontalHeaderLabels(["字符上限 (≤ 字符数)", "对应时长 (秒)"])
        self.table_char_dur.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table_char_dur.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        char_layout.addWidget(self.table_char_dur)
        
        btn_char_layout = QHBoxLayout()
        btn_add_char = QPushButton("＋ 添加行")
        btn_add_char.clicked.connect(self.add_char_row)
        btn_del_char = QPushButton("－ 删除行")
        btn_del_char.clicked.connect(self.del_char_row)
        btn_char_layout.addWidget(btn_add_char)
        btn_char_layout.addWidget(btn_del_char)
        btn_char_layout.addStretch()
        char_layout.addLayout(btn_char_layout)
        
        main_layout.addWidget(group_char_dur)
        
        # Section 3: Duration -> Points cost rules
        group_dur_pts = QGroupBox("3. 时长与积分消耗对应规则 (Seconds -> Points Cost)")
        dur_pts_layout = QVBoxLayout(group_dur_pts)
        dur_pts_layout.setContentsMargins(12, 12, 12, 12)
        
        self.table_dur_pts = QTableWidget()
        self.table_dur_pts.setColumnCount(2)
        self.table_dur_pts.setHorizontalHeaderLabels(["时长 (秒)", "消耗积分"])
        self.table_dur_pts.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table_dur_pts.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        dur_pts_layout.addWidget(self.table_dur_pts)
        
        btn_pts_layout = QHBoxLayout()
        btn_add_pts = QPushButton("＋ 添加行")
        btn_add_pts.clicked.connect(self.add_pts_row)
        btn_del_pts = QPushButton("－ 删除行")
        btn_del_pts.clicked.connect(self.del_pts_row)
        btn_pts_layout.addWidget(btn_add_pts)
        btn_pts_layout.addWidget(btn_del_pts)
        btn_pts_layout.addStretch()
        dur_pts_layout.addLayout(btn_pts_layout)
        
        main_layout.addWidget(group_dur_pts)
        
        # Section 4: Speech Extraction API Keys & Language
        group_api = QGroupBox("4. 语音提取 API 密钥与语言设置 (Speech API Keys & Language)")
        api_layout = QVBoxLayout(group_api)
        api_layout.setContentsMargins(12, 12, 12, 12)
        api_layout.setSpacing(8)
        
        # Language selector
        lang_layout = QHBoxLayout()
        lang_layout.addWidget(QLabel("🌐 识别语言:"))
        self.combo_language = QComboBox()
        from models.config_manager import ConfigManager
        for code, label in ConfigManager.SUPPORTED_LANGUAGES:
            self.combo_language.addItem(label, code)
        lang_layout.addWidget(self.combo_language, stretch=1)
        
        lbl_lang_hint = QLabel("(* 用于语音转文字时指定目标语言)")
        lbl_lang_hint.setStyleSheet("color: #8D6E63; font-style: italic; font-size: 11px;")
        lang_layout.addWidget(lbl_lang_hint)
        api_layout.addLayout(lang_layout)
        
        # Gladia API Keys
        api_layout.addWidget(QLabel("🔑 Gladia API Keys (每行一个，自动轮询):"))
        self.txt_gladia_keys = QTextEdit()
        self.txt_gladia_keys.setMaximumHeight(72)
        self.txt_gladia_keys.setPlaceholderText("粘贴 Gladia API Key，每行一个...\n例: gla_xxxxxxxxxxxxxxxxxxxx\ngla_yyyyyyyyyyyyyyyyyyyy")
        self.txt_gladia_keys.setStyleSheet("""
            QTextEdit {
                background-color: white;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                font-family: Consolas, monospace;
                font-size: 12px;
                color: #5D4037;
                padding: 4px;
            }
        """)
        api_layout.addWidget(self.txt_gladia_keys)
        
        # ElevenLabs API Keys
        api_layout.addWidget(QLabel("🔑 ElevenLabs API Keys (每行一个，自动轮询):"))
        self.txt_elevenlabs_keys = QTextEdit()
        self.txt_elevenlabs_keys.setMaximumHeight(72)
        self.txt_elevenlabs_keys.setPlaceholderText("粘贴 ElevenLabs API Key，每行一个...\n例: sk_xxxxxxxxxxxxxxxxxxxx\nsk_yyyyyyyyyyyyyyyyyyyy")
        self.txt_elevenlabs_keys.setStyleSheet("""
            QTextEdit {
                background-color: white;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                font-family: Consolas, monospace;
                font-size: 12px;
                color: #5D4037;
                padding: 4px;
            }
        """)
        api_layout.addWidget(self.txt_elevenlabs_keys)
        
        lbl_api_hint = QLabel("💡 提示: 支持多个 Key 轮询，当一个 Key 用量超限时自动切换下一个")
        lbl_api_hint.setStyleSheet("color: #0284C7; font-style: italic; font-size: 11px; font-weight: normal;")
        api_layout.addWidget(lbl_api_hint)
        
        main_layout.addWidget(group_api)
        
        # Bottom Buttons
        bottom_layout = QHBoxLayout()
        btn_reset = QPushButton("🔄 恢复默认设置")
        btn_reset.setObjectName("btn_reset")
        btn_reset.clicked.connect(self.reset_defaults)
        bottom_layout.addWidget(btn_reset)
        
        bottom_layout.addStretch()
        
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        bottom_layout.addWidget(btn_cancel)
        
        btn_save = QPushButton("💾 保存设置")
        btn_save.setStyleSheet("background-color: #10B981; color: white; font-weight: bold;")
        btn_save.clicked.connect(self.save_settings)
        bottom_layout.addWidget(btn_save)
        
        main_layout.addLayout(bottom_layout)
        
        # Finalize scroll area
        scroll_content.setLayout(main_layout)
        scroll_area.setWidget(scroll_content)
        
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.addWidget(scroll_area)

    def load_data(self):
        self.spin_max_points.setValue(self.cm.max_batch_points)
        self.txt_marker.setText(getattr(self.cm, "forced_split_marker", "///"))
        
        # Load char -> duration rules
        self.table_char_dur.setRowCount(0)
        for r in self.cm.char_duration_rules:
            row = self.table_char_dur.rowCount()
            self.table_char_dur.insertRow(row)
            self.table_char_dur.setItem(row, 0, QTableWidgetItem(str(r["max_chars"])))
            self.table_char_dur.setItem(row, 1, QTableWidgetItem(str(r["duration"])))
            
        # Load duration -> points rules
        self.table_dur_pts.setRowCount(0)
        for r in self.cm.duration_points_rules:
            row = self.table_dur_pts.rowCount()
            self.table_dur_pts.insertRow(row)
            self.table_dur_pts.setItem(row, 0, QTableWidgetItem(str(r["duration"])))
            self.table_dur_pts.setItem(row, 1, QTableWidgetItem(str(r["points"])))
        
        # Load API keys
        self.txt_gladia_keys.setPlainText("\n".join(self.cm.gladia_api_keys))
        self.txt_elevenlabs_keys.setPlainText("\n".join(self.cm.elevenlabs_api_keys))
        
        # Load language selection
        lang_code = getattr(self.cm, "speech_language", "es")
        idx = self.combo_language.findData(lang_code)
        if idx >= 0:
            self.combo_language.setCurrentIndex(idx)
        else:
            self.combo_language.setCurrentIndex(0)  # Default to Spanish

    def add_char_row(self):
        row = self.table_char_dur.rowCount()
        self.table_char_dur.insertRow(row)
        self.table_char_dur.setItem(row, 0, QTableWidgetItem("200"))
        self.table_char_dur.setItem(row, 1, QTableWidgetItem("12"))

    def del_char_row(self):
        r = self.table_char_dur.currentRow()
        if r >= 0:
            self.table_char_dur.removeRow(r)

    def add_pts_row(self):
        row = self.table_dur_pts.rowCount()
        self.table_dur_pts.insertRow(row)
        self.table_dur_pts.setItem(row, 0, QTableWidgetItem("12"))
        self.table_dur_pts.setItem(row, 1, QTableWidgetItem("18"))

    def del_pts_row(self):
        r = self.table_dur_pts.currentRow()
        if r >= 0:
            self.table_dur_pts.removeRow(r)

    def reset_defaults(self):
        res = QMessageBox.question(self, "确认", "确定要恢复系统默认的积分与时长规则吗？", 
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if res == QMessageBox.StandardButton.Yes:
            self.cm.reset_to_defaults()
            self.load_data()

    def save_settings(self):
        # Commit any in-progress cell editor in tables
        self.table_char_dur.clearFocus()
        self.table_dur_pts.clearFocus()
        self.setFocus()
        
        # Read max batch points & forced split marker
        self.cm.max_batch_points = self.spin_max_points.value()
        self.cm.forced_split_marker = self.txt_marker.text().strip() or "///"
        
        # Read char -> duration rules
        new_char_rules = []
        for r in range(self.table_char_dur.rowCount()):
            c_item = self.table_char_dur.item(r, 0)
            d_item = self.table_char_dur.item(r, 1)
            try:
                max_c = int(c_item.text().strip()) if c_item else 0
                dur = int(d_item.text().strip()) if d_item else 0
                if max_c > 0 and dur > 0:
                    new_char_rules.append({"max_chars": max_c, "duration": dur})
            except ValueError:
                pass
                
        if not new_char_rules:
            QMessageBox.warning(self, "警告", "字符数与时长规则不能为空！")
            return
            
        new_char_rules.sort(key=lambda x: x["max_chars"])
        self.cm.char_duration_rules = new_char_rules
        
        # Read duration -> points rules
        new_pts_rules = []
        for r in range(self.table_dur_pts.rowCount()):
            d_item = self.table_dur_pts.item(r, 0)
            p_item = self.table_dur_pts.item(r, 1)
            try:
                dur = int(d_item.text().strip()) if d_item else 0
                pts = int(p_item.text().strip()) if p_item else 0
                if dur > 0 and pts > 0:
                    new_pts_rules.append({"duration": dur, "points": pts})
            except ValueError:
                pass
                
        if not new_pts_rules:
            QMessageBox.warning(self, "警告", "时长与积分对应规则不能为空！")
            return
            
        self.cm.duration_points_rules = new_pts_rules
        
        # Read API keys (filter empty lines)
        gladia_text = self.txt_gladia_keys.toPlainText().strip()
        self.cm.gladia_api_keys = [k.strip() for k in gladia_text.split("\n") if k.strip()]
        
        elevenlabs_text = self.txt_elevenlabs_keys.toPlainText().strip()
        self.cm.elevenlabs_api_keys = [k.strip() for k in elevenlabs_text.split("\n") if k.strip()]
        
        # Read language
        self.cm.speech_language = self.combo_language.currentData() or "es"
        
        if self.cm.save():
            QMessageBox.information(self, "成功", "设置保存成功！已按新规则生效。")
            self.accept()
        else:
            QMessageBox.critical(self, "错误", "保存配置文件失败。")
