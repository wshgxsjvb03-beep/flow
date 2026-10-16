# -*- coding: utf-8 -*-
"""检查更新对话框：检查 → 显示更新说明 → 一键下载并安装。"""
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                             QProgressBar, QTextEdit, QMessageBox, QApplication)
from PyQt6.QtCore import Qt

from version import __version__
from services.updater import CheckUpdateThread, DownloadUpdateThread, launch_installer


class UpdateDialog(QDialog):
    def __init__(self, parent=None, auto_check=True):
        super().__init__(parent)
        self.setWindowTitle("检查更新")
        self.resize(520, 420)
        self.info = None
        self.check_thread = None
        self.dl_thread = None

        lay = QVBoxLayout(self)
        self.lbl_cur = QLabel(f"当前版本：v{__version__}")
        self.lbl_cur.setStyleSheet("font-size:13px;")
        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet("font-size:14px;font-weight:bold;")
        self.txt_notes = QTextEdit()
        self.txt_notes.setReadOnly(True)
        self.txt_notes.setPlaceholderText("更新说明会显示在这里")
        self.bar = QProgressBar()
        self.bar.setVisible(False)
        lay.addWidget(self.lbl_cur)
        lay.addWidget(self.lbl_status)
        lay.addWidget(self.txt_notes, 1)
        lay.addWidget(self.bar)

        row = QHBoxLayout()
        self.btn_check = QPushButton("🔄 重新检查")
        self.btn_update = QPushButton("⬇️ 立即更新")
        self.btn_update.setEnabled(False)
        self.btn_update.setStyleSheet("QPushButton{background:#059669;color:white;font-weight:bold;padding:6px 14px;border-radius:4px;}"
                                      "QPushButton:disabled{background:#9CA3AF;}")
        self.btn_close = QPushButton("关闭")
        row.addWidget(self.btn_check)
        row.addStretch()
        row.addWidget(self.btn_update)
        row.addWidget(self.btn_close)
        lay.addLayout(row)

        self.btn_check.clicked.connect(self.start_check)
        self.btn_update.clicked.connect(self.start_update)
        self.btn_close.clicked.connect(self.close)
        if auto_check:
            self.start_check()

    # ── 检查 ──
    def start_check(self):
        self.btn_check.setEnabled(False)
        self.btn_update.setEnabled(False)
        self.txt_notes.clear()
        self.lbl_status.setText("正在检查更新…")
        self.check_thread = CheckUpdateThread()
        self.check_thread.finished_signal.connect(self._on_checked)
        self.check_thread.start()

    def _on_checked(self, res):
        self.info = res
        self.btn_check.setEnabled(True)
        if not res["ok"]:
            self.lbl_status.setText(f"❌ {res['error']}")
        elif res["has_update"]:
            mb = f"（{res['size'] / 1048576:.1f} MB）" if res["size"] else ""
            self.lbl_status.setText(f"🎉 发现新版本 v{res['version']} {mb}")
            self.txt_notes.setPlainText(res["notes"] or "（无更新说明）")
            self.btn_update.setEnabled(True)
        else:
            self.lbl_status.setText(f"✅ 已是最新版本（v{__version__}）" + (f"\n{res['error']}" if res["error"] else ""))

    # ── 下载并安装 ──
    def start_update(self):
        if not self.info or not self.info.get("has_update"):
            return
        r = QMessageBox.question(
            self, "确认更新",
            f"将下载 v{self.info['version']} 并自动安装。\n\n安装时软件会自动关闭并在完成后重新打开。\n"
            "您的规则设置、模板预设等不会受影响。\n\n请确认当前没有正在进行的任务，是否继续？")
        if r != QMessageBox.StandardButton.Yes:
            return
        self.btn_update.setEnabled(False)
        self.btn_check.setEnabled(False)
        self.bar.setVisible(True)
        self.bar.setValue(0)
        self.lbl_status.setText("正在下载更新…")
        self.dl_thread = DownloadUpdateThread(self.info["url"], self.info["name"], self.info["size"])
        self.dl_thread.progress_signal.connect(self._on_progress)
        self.dl_thread.finished_signal.connect(self._on_downloaded)
        self.dl_thread.start()

    def _on_progress(self, done, total):
        if total:
            self.bar.setMaximum(total)
            self.bar.setValue(done)
            self.lbl_status.setText(f"正在下载更新… {done / 1048576:.1f} / {total / 1048576:.1f} MB")
        else:
            self.bar.setMaximum(0)

    def _on_downloaded(self, ok, msg):
        if not ok:
            self.bar.setVisible(False)
            self.btn_check.setEnabled(True)
            self.btn_update.setEnabled(True)
            self.lbl_status.setText(f"❌ {msg}")
            return
        self.lbl_status.setText("下载完成，正在启动安装程序，软件即将自动重启…")
        try:
            launch_installer(msg)
        except Exception as e:
            self.lbl_status.setText(f"❌ 无法启动安装程序：{e}\n安装包位置：{msg}")
            self.btn_check.setEnabled(True)
            return
        QApplication.quit()

    def closeEvent(self, e):
        if self.dl_thread and self.dl_thread.isRunning():
            self.dl_thread.requestInterruption()
            self.dl_thread.wait(2000)
        super().closeEvent(e)
