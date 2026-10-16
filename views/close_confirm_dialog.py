# -*- coding: utf-8 -*-
"""关闭低积分浏览器确认对话框：
- 采用可滚动的复选列表，彻底解决浏览器数量多时弹窗被屏幕截断、无法点击确认按钮的问题
- 支持全选、全不选、一键排除已分配任务的浏览器
- 底部固定「确定关闭 (N 个)」与「取消」按钮
"""

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                             QListWidget, QListWidgetItem, QFrame, QAbstractItemView)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor


class CloseConfirmDialog(QDialog):
    def __init__(self, parent=None, title="确认关闭低积分浏览器",
                 header_text="", items=None, extra_warning=None):
        """
        items: list of dict:
            {
                "client": c,
                "label": "user@gmail.com",
                "points": 5,
                "is_busy": True/False,
            }
        """
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(560, 480)
        self.setMinimumSize(480, 360)
        self.setMaximumHeight(580)
        self.setModal(True)

        self.items_data = items or []
        self._checkbox_items = []

        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lay.setContentsMargins(18, 16, 18, 16)

        # ── 1. 顶部标题与说明 ──
        if not header_text:
            header_text = f"将关闭以下 {len(self.items_data)} 个低积分浏览器："
        self.lbl_header = QLabel(header_text)
        self.lbl_header.setStyleSheet("font-size: 14px; font-weight: bold; color: #1F2937;")
        lay.addWidget(self.lbl_header)

        busy_count = sum(1 for x in self.items_data if x.get("is_busy"))
        if busy_count > 0:
            warn_frame = QFrame()
            warn_frame.setStyleSheet(
                "QFrame { background: #FEF2F2; border: 1px solid #FCA5A5; border-radius: 6px; padding: 6px 10px; }"
            )
            wlay = QHBoxLayout(warn_frame)
            wlay.setContentsMargins(4, 4, 4, 4)
            lbl_busy_warn = QLabel(f"⚠️ 注意：其中有 <b>{busy_count}</b> 个浏览器已分配任务！关闭可能导致这些任务中断。")
            lbl_busy_warn.setStyleSheet("color: #991B1B; font-size: 12px;")
            lbl_busy_warn.setWordWrap(True)
            wlay.addWidget(lbl_busy_warn)
            lay.addWidget(warn_frame)

        if extra_warning:
            lbl_extra = QLabel(extra_warning)
            lbl_extra.setStyleSheet("color: #4B5563; font-size: 12px;")
            lbl_extra.setWordWrap(True)
            lay.addWidget(lbl_extra)

        # ── 2. 快捷选择工具栏 ──
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self.btn_all = QPushButton("全选")
        self.btn_all.setFixedHeight(26)
        self.btn_all.setStyleSheet("padding: 2px 10px; font-size: 12px;")

        self.btn_none = QPushButton("全不选")
        self.btn_none.setFixedHeight(26)
        self.btn_none.setStyleSheet("padding: 2px 10px; font-size: 12px;")

        toolbar.addWidget(self.btn_all)
        toolbar.addWidget(self.btn_none)

        if busy_count > 0:
            self.btn_exclude_busy = QPushButton("排除已分配任务")
            self.btn_exclude_busy.setFixedHeight(26)
            self.btn_exclude_busy.setStyleSheet(
                "QPushButton { padding: 2px 10px; font-size: 12px; color: #9A3412; background: #FFEDD5; border: 1px solid #FDBA74; border-radius: 3px; }"
                "QPushButton:hover { background: #FED7AA; }"
            )
            toolbar.addWidget(self.btn_exclude_busy)
            self.btn_exclude_busy.clicked.connect(self._exclude_busy)

        toolbar.addStretch()

        self.lbl_selected_count = QLabel("")
        self.lbl_selected_count.setStyleSheet("font-size: 12px; color: #4B5563; font-weight: bold;")
        toolbar.addWidget(self.lbl_selected_count)

        lay.addLayout(toolbar)

        # ── 3. 核心滚动列表 ──
        self.list_widget = QListWidget()
        self.list_widget.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list_widget.setStyleSheet(
            "QListWidget { border: 1px solid #D1D5DB; border-radius: 6px; background: white; padding: 4px; }"
            "QListWidget::item { padding: 5px 6px; border-bottom: 1px solid #F3F4F6; }"
            "QListWidget::item:hover { background: #F9FAFB; }"
        )

        for item_info in self.items_data:
            label_text = item_info.get("label", "")
            pts = item_info.get("points", 0)
            is_busy = item_info.get("is_busy", False)

            if is_busy:
                text = f"  {label_text}：{pts} 积分   ⚠️ 已分配任务"
            else:
                text = f"  {label_text}：{pts} 积分"

            list_item = QListWidgetItem(text)
            list_item.setFlags(list_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            list_item.setCheckState(Qt.CheckState.Checked)
            list_item.setData(Qt.ItemDataRole.UserRole, item_info)

            if is_busy:
                font = list_item.font()
                font.setBold(True)
                list_item.setFont(font)
                list_item.setForeground(QColor("#DC2626"))
            else:
                list_item.setForeground(QColor("#1F2937"))

            self.list_widget.addItem(list_item)
            self._checkbox_items.append(list_item)

        lay.addWidget(self.list_widget, 1)

        # ── 4. 底部按钮栏 ──
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(10)

        tip_lbl = QLabel("可单独取消勾选保留浏览器")
        tip_lbl.setStyleSheet("font-size: 11px; color: #9CA3AF;")
        bottom_row.addWidget(tip_lbl)
        bottom_row.addStretch()

        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setFixedHeight(34)
        self.btn_cancel.setStyleSheet(
            "QPushButton { padding: 6px 16px; font-size: 13px; border: 1px solid #D1D5DB; border-radius: 4px; background: white; color: #374151; }"
            "QPushButton:hover { background: #F3F4F6; }"
        )
        self.btn_cancel.clicked.connect(self.reject)
        bottom_row.addWidget(self.btn_cancel)

        self.btn_confirm = QPushButton("确定关闭")
        self.btn_confirm.setFixedHeight(34)
        self.btn_confirm.setStyleSheet(
            "QPushButton { background: #DC2626; color: white; font-weight: bold; font-size: 13px; padding: 6px 20px; border-radius: 4px; border: none; }"
            "QPushButton:hover { background: #B91C1C; }"
            "QPushButton:disabled { background: #9CA3AF; color: #E5E7EB; }"
        )
        self.btn_confirm.clicked.connect(self.accept)
        bottom_row.addWidget(self.btn_confirm)

        lay.addLayout(bottom_row)

        # 信号绑定
        self.btn_all.clicked.connect(self._select_all)
        self.btn_none.clicked.connect(self._select_none)
        self.list_widget.itemChanged.connect(self._update_counts)

        self._update_counts()

    def _select_all(self):
        self.list_widget.blockSignals(True)
        for it in self._checkbox_items:
            it.setCheckState(Qt.CheckState.Checked)
        self.list_widget.blockSignals(False)
        self._update_counts()

    def _select_none(self):
        self.list_widget.blockSignals(True)
        for it in self._checkbox_items:
            it.setCheckState(Qt.CheckState.Unchecked)
        self.list_widget.blockSignals(False)
        self._update_counts()

    def _exclude_busy(self):
        self.list_widget.blockSignals(True)
        for it in self._checkbox_items:
            info = it.data(Qt.ItemDataRole.UserRole)
            if info and info.get("is_busy"):
                it.setCheckState(Qt.CheckState.Unchecked)
            else:
                it.setCheckState(Qt.CheckState.Checked)
        self.list_widget.blockSignals(False)
        self._update_counts()

    def _update_counts(self):
        selected_count = sum(1 for it in self._checkbox_items if it.checkState() == Qt.CheckState.Checked)
        total_count = len(self._checkbox_items)
        self.lbl_selected_count.setText(f"已选中: {selected_count} / {total_count}")
        if selected_count > 0:
            self.btn_confirm.setEnabled(True)
            self.btn_confirm.setText(f"确定关闭 ({selected_count} 个)")
        else:
            self.btn_confirm.setEnabled(False)
            self.btn_confirm.setText("确定关闭 (0 个)")

    def get_selected_clients(self):
        """返回所有勾选项目的原始 client 字典列表"""
        selected = []
        for it in self._checkbox_items:
            if it.checkState() == Qt.CheckState.Checked:
                info = it.data(Qt.ItemDataRole.UserRole)
                if info and "client" in info:
                    selected.append(info["client"])
        return selected
