# -*- coding: utf-8 -*-
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QTableWidget, QTableWidgetItem, QLabel, QMessageBox, 
                             QHeaderView, QTextEdit)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication
from bs4 import BeautifulSoup
import re
import csv
import io

class ImportDialog(QDialog):
    """Dialog for importing project rows from clipboard."""
    
    def __init__(self, storage_manager, parent=None):
        super().__init__(parent)
        self.storage_manager = storage_manager
        self.imported_rows = []
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("新建导入 (Import Projects)")
        self.resize(900, 600)
        
        # Apply stylesheet matching the warm theme
        self.setStyleSheet("""
            QDialog {
                background-color: #FAF6F0;
                color: #5D4037;
                font-family: "Segoe UI", sans-serif;
            }
            QLabel {
                font-size: 14px;
                color: #5D4037;
                font-weight: bold;
            }
            QPushButton {
                background-color: #E0A96D;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #D2904C;
            }
            QPushButton:pressed {
                background-color: #B87635;
            }
            QPushButton#btn_cancel {
                background-color: #D7CCC8;
                color: #5D4037;
            }
            QPushButton#btn_cancel:hover {
                background-color: #BCAAA4;
            }
            QTableWidget {
                background-color: white;
                border: 1px solid #D7CCC8;
                gridline-color: #EFEBE9;
                selection-background-color: #FFE0B2;
                selection-color: #5D4037;
                border-radius: 4px;
            }
            QHeaderView::section {
                background-color: #D7CCC8;
                color: #5D4037;
                padding: 6px;
                font-weight: bold;
                border: 1px solid #CFD8DC;
            }
        """)

        layout = QVBoxLayout(self)
        
        # Instructions
        self.lbl_info = QLabel("请在 Excel/Google Sheets 中复制要导入的行（支持每行 7 格或 8 格数据），然后点击下方按钮读取剪贴板：")
        layout.addWidget(self.lbl_info)
        
        # Clipboard action button
        self.btn_read_clipboard = QPushButton("📋 从剪贴板读取数据")
        self.btn_read_clipboard.clicked.connect(self.read_from_clipboard)
        layout.addWidget(self.btn_read_clipboard)
        
        # Preview Table
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "序号", "1: 名称前缀", "4: 中文文案", "5: 西班牙语文案", "6: 谷歌链接", "7: 备注/后缀"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)
        
        # Action Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setObjectName("btn_cancel")
        self.btn_cancel.clicked.connect(self.reject)
        
        self.btn_confirm = QPushButton("确认导入")
        self.btn_confirm.setEnabled(False)
        self.btn_confirm.clicked.connect(self.confirm_import)
        
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_confirm)
        layout.addLayout(btn_layout)

    def read_from_clipboard(self):
        clipboard = QGuiApplication.clipboard()
        mime_data = clipboard.mimeData()
        
        parsed_rows = []
        
        # Try reading HTML first to preserve hyperlinked URLs in cells
        if mime_data.hasHtml():
            html_text = mime_data.html()
            parsed_rows = self.parse_html_table(html_text)
            
        # Fallback to plain text TSV if HTML failed or returned no results
        if not parsed_rows and mime_data.hasText():
            plain_text = mime_data.text()
            parsed_rows = self.parse_tsv_text(plain_text)
            
        if not parsed_rows:
            QMessageBox.warning(self, "提示", "未能从剪贴板读取到有效的 7 列数据，请在表格中复制后重试。")
            return
            
        self.imported_rows = parsed_rows
        self.populate_table()
        self.btn_confirm.setEnabled(True)
        QMessageBox.information(self, "成功", f"成功解析出 {len(parsed_rows)} 行项目数据！")

    def parse_html_table(self, html_content):
        """Parses HTML table and extracts cell text and all cell links."""
        soup = BeautifulSoup(html_content, 'html.parser')
        rows = []
        
        tr_tags = soup.find_all('tr')
        for tr in tr_tags:
            td_tags = tr.find_all(['td', 'th'])
            if not td_tags:
                continue
                
            row_data = []
            for td in td_tags:
                # Use newline as separator to preserve Excel line breaks and prevent word sticking
                text = td.get_text(separator='\n').strip()
                
                # Extract all <a> href links
                links = []
                for a in td.find_all('a'):
                    if a.get('href'):
                        links.append(a.get('href').strip())
                
                # Also regex search for plain text http/https URLs in the cell
                url_pattern = re.compile(r'https?://[^\s\u4e00-\u9fa5]+')
                text_urls = url_pattern.findall(text)
                for u in text_urls:
                    cleaned_u = u.rstrip('.,;)"\'”」')
                    if cleaned_u not in links:
                        links.append(cleaned_u)
                    
                row_data.append({
                    "text": text,
                    "links": links
                })
                
            # Filter rows with at least 7 columns
            num_cols = len(row_data)
            if num_cols >= 7:
                take_cols = 8 if num_cols >= 8 else 7
                rows.append(row_data[:take_cols])
                
        return rows

    def parse_tsv_text(self, text_content):
        """Parses tab-separated text (TSV) from clipboard and extracts links."""
        rows = []
        reader = csv.reader(io.StringIO(text_content.strip()), delimiter='\t')
        for cols in reader:
            if not cols:
                continue
            num_cols = len(cols)
            if num_cols >= 7:
                take_cols = 8 if num_cols >= 8 else 7
                row_data = []
                for col in cols[:take_cols]:
                    val = col.strip()
                    url_pattern = re.compile(r'https?://[^\s\u4e00-\u9fa5]+')
                    links = [u.rstrip('.,;)"\'”」') for u in url_pattern.findall(val)]
                    row_data.append({
                        "text": val,
                        "links": links
                    })
                rows.append(row_data)
                
        return rows

    def populate_table(self):
        """Fills QTableWidget with parsed clipboard rows."""
        self.table.setRowCount(len(self.imported_rows))
        
        # Calculate next starting index based on existing projects
        existing = self.storage_manager.list_projects()
        next_idx = 1
        if existing:
            try:
                next_idx = max(int(p["index_str"]) for p in existing) + 1
            except ValueError:
                next_idx = len(existing) + 1
                
        for row_idx, row in enumerate(self.imported_rows):
            proj_idx = next_idx + row_idx
            
            # Row index display
            self.table.setItem(row_idx, 0, QTableWidgetItem(f"{proj_idx:02d}"))
            
            # Col 1: Name prefix
            self.table.setItem(row_idx, 1, QTableWidgetItem(row[0]["text"]))
            
            # Col 4: Chinese copy
            self.table.setItem(row_idx, 2, QTableWidgetItem(row[3]["text"]))
            
            # Col 5: Spanish copy
            self.table.setItem(row_idx, 3, QTableWidgetItem(row[4]["text"]))
            
            # Col 6: Google Drive URL (join multiple links with newline)
            if len(row) >= 8:
                cell_links = row[7]["links"]
                cell_text = row[7]["text"]
            else:
                cell_links = row[5]["links"]
                cell_text = row[5]["text"]
                
            if cell_links:
                drive_url = "\n".join(cell_links)
            else:
                drive_url = cell_text
            self.table.setItem(row_idx, 4, QTableWidgetItem(drive_url))
            
            # Col 7: Notes/suffix
            self.table.setItem(row_idx, 5, QTableWidgetItem(row[6]["text"]))

    def confirm_import(self):
        """Creates project directories and stores metadata.json."""
        if not self.storage_manager.get_base_path():
            QMessageBox.warning(self, "错误", "请先设置存储总路径！")
            self.reject()
            return
            
        success_count = 0
        from models.project_model import ProjectModel
        from services.text_processor import TextProcessor
        
        for row_idx in range(self.table.rowCount()):
            try:
                idx_str = self.table.item(row_idx, 0).text()
                idx_val = int(idx_str)
                col1 = self.table.item(row_idx, 1).text()
                col4 = self.table.item(row_idx, 2).text()
                col5 = self.table.item(row_idx, 3).text()
                col6 = self.table.item(row_idx, 4).text()
                col7 = self.table.item(row_idx, 5).text()
                
                # 1. Create project folder
                proj_dir, proj_id = self.storage_manager.create_project_dir(idx_val, col1, col7)
                
                # 2. Write metadata.json
                proj = ProjectModel(proj_dir)
                proj.index = idx_val
                proj.col1_name = col1
                proj.col7_notes = col7
                proj.google_drive_url = col6
                proj.chinese_text = col4
                proj.spanish_text = col5
                # Auto clean and segment Spanish text on import using config_manager rules if available
                config_mgr = getattr(self.parent(), "config_manager", None)
                proj.spanish_segments = TextProcessor.segment_spanish_text(col5, config_mgr)
                proj.save()
                
                # 3. Trigger automatic background download via parent MainWindow
                if col6 and hasattr(self.parent(), "start_background_download"):
                    self.parent().start_background_download(proj_id, col6, proj_dir)
                
                success_count += 1
            except Exception as e:
                print(f"Error importing row {row_idx}: {e}")
                
        msg = f"成功导入并创建了 {success_count} 个工程项目！"
        if success_count > 0:
            msg += "\n\n💡 提示：包含云盘链接的项目已在后台自动开始下载素材，无需重复点击下载。"
        QMessageBox.information(self, "成功", msg)
        self.accept()
