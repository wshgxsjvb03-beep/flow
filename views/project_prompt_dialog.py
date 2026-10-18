from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel, QPlainTextEdit, QScrollArea, QVBoxLayout, QWidget,
)
from services.project_prompts import PROTECTED_TOKEN, common_prompt_source, plan_template_edit


class ProjectPromptEditDialog(QDialog):
    """Edit template text while document placeholders remain outside editable fields."""
    def __init__(self, sources, apply_callback, parent=None):
        super().__init__(parent)
        source = common_prompt_source(list(sources.values()))
        self.sources, self.apply_callback = sources, apply_callback
        self.setWindowTitle(f'编辑提示词 · {source["name"]} · 已选 {len(sources)} 句')
        self.resize(760, 640)
        layout = QVBoxLayout(self)
        label = QLabel(f'仅修改选中的 {len(sources)} 句。文案已自动还原为固定占位符，各句文案保持原样。')
        label.setWordWrap(True)
        layout.addWidget(label)
        area = QScrollArea()
        area.setWidgetResizable(True)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        self.parts = []
        self.editors = []
        for part in PROTECTED_TOKEN.split(source['content']):
            if PROTECTED_TOKEN.fullmatch(part):
                description = '每句文案自动填入，不能修改' if part == '{spanish_text}' else '每句运镜自动填入，不能修改'
                fixed = QLabel(f'{part}　〔{description}〕')
                fixed.setWordWrap(True)
                fixed.setStyleSheet('background: #eee6dd; color: #795548; padding: 12px; border-radius: 4px;')
                body_layout.addWidget(fixed)
                self.parts.append(part)
            else:
                editor = QPlainTextEdit(part)
                lines = sum(max(1, (len(line) + 54) // 55) for line in (part.splitlines() or ['']))
                editor.setMinimumHeight(60)
                editor.setMaximumHeight(min(220, max(60, lines * 22 + 20)))
                editor.setPlaceholderText('在这里修改模板描述')
                body_layout.addWidget(editor, 1)
                self.parts.append(editor)
                self.editors.append(editor)
        body_layout.addStretch()
        area.setWidget(body)
        layout.addWidget(area, 1)
        note = QLabel('保存到当前项目的提示词副本，不修改原始模板。')
        layout.addWidget(note)
        self.feedback = QLabel()
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        self.save_button.setText(f'保存到选中的 {len(sources)} 句')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        for editor in self.editors:
            editor.textChanged.connect(self.validate)
        self.updates = {}
        self.validate()

    def template_content(self):
        return ''.join(part if isinstance(part, str) else part.toPlainText() for part in self.parts)

    def validate(self):
        try:
            self.updates = plan_template_edit(self.sources, self.template_content())
            self.feedback.setText('')
        except ValueError as error:
            self.updates = {}
            self.feedback.setText(str(error))
        self.save_button.setEnabled(bool(self.updates))

    def save(self):
        self.validate()
        if self.updates and self.apply_callback(self.updates):
            self.accept()
