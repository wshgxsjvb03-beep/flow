import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from models.project_model import ProjectModel
from services.project_prompts import ProjectPromptStore, common_prompt_source, plan_template_edit


class PromptPlanningTests(unittest.TestCase):
    def test_different_templates_or_versions_are_rejected(self):
        source = {'template_id': 'stage', 'name': '舞台', 'content': '观众 {spanish_text}'}
        for other in ({**source, 'template_id': 'other'}, {**source, 'content': '男性观众 {spanish_text}'}):
            with self.assertRaisesRegex(ValueError, '不同'):
                common_prompt_source([source, other])

    def test_protected_tokens_cannot_be_removed_or_duplicated(self):
        sources = {0: {'template_id': 'stage', 'name': '舞台', 'content': '观众 {spanish_text} {camera_motion}'}}
        for content in ('缺少文案', '{spanish_text}', '{spanish_text}{spanish_text}{camera_motion}'):
            with self.assertRaisesRegex(ValueError, '占位符'):
                plan_template_edit(sources, content)


class PromptStorageTests(unittest.TestCase):
    def test_identity_survives_reorder_and_duplicate_sentence_text(self):
        with tempfile.TemporaryDirectory() as folder:
            model = ProjectModel(folder)
            model.spanish_segments = [{'text': 'Same'}, {'text': 'Same'}, {'text': 'Other'}]
            model.prompt_store.apply(model, {0: {'content': '观众 {spanish_text}', 'group': '观众组'}})
            model.spanish_segments.reverse()
            model.save()
            loaded = ProjectModel(folder)
            self.assertEqual(loaded.prompt_store.get(loaded.spanish_segments[0]), {})
            self.assertEqual(loaded.prompt_store.get(loaded.spanish_segments[1]), {})
            self.assertEqual(loaded.prompt_store.get(loaded.spanish_segments[2])['group'], '观众组')
            # Copying a sentence's metadata must not couple its later edits.
            loaded.spanish_segments.append(dict(loaded.spanish_segments[2]))
            loaded.prompt_store.apply(loaded, {3: {'content': '男性观众 {spanish_text}'}})
            self.assertEqual(loaded.prompt_store.get(loaded.spanish_segments[2])['content'], '观众 {spanish_text}')
            loaded.spanish_segments.append(dict(loaded.spanish_segments[2]))
            with patch('services.project_prompts.os.replace', side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    loaded.prompt_store.apply(loaded, {4: {'content': '改动 {spanish_text}'}})
            reloaded = ProjectModel(folder)
            self.assertEqual(reloaded.prompt_store.get(reloaded.spanish_segments[4])['content'], '观众 {spanish_text}')

    def test_save_failures_do_not_apply_partial_prompts(self):
        with tempfile.TemporaryDirectory() as folder:
            model = ProjectModel(folder)
            model.spanish_segments = [{'text': 'Hola'}]
            with patch.object(model, 'save', return_value=False):
                with self.assertRaises(OSError):
                    model.prompt_store.apply(model, {0: {'content': '观众 {spanish_text}'}})
            self.assertNotIn(ProjectPromptStore.ID_FIELD, model.spanish_segments[0])
            self.assertFalse(model.prompt_store.path.exists())
            model.prompt_store.apply(model, {0: {'content': '观众 {spanish_text}'}})
            before = model.prompt_store.path.read_bytes()
            with patch('services.project_prompts.os.replace', side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    model.prompt_store.apply(model, {0: {'content': '男性观众 {spanish_text}'}})
            self.assertEqual(model.prompt_store.path.read_bytes(), before)
            self.assertEqual(model.prompt_store.get(model.spanish_segments[0])['content'], '观众 {spanish_text}')

    def test_corrupt_file_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder, ProjectPromptStore.FILE_NAME)
            target.write_text('broken', encoding='utf-8')
            model = ProjectModel(folder)
            model.spanish_segments = [{'text': 'Hola'}]
            with self.assertRaises(ValueError):
                model.prompt_store.apply(model, {0: {'group': '观众组'}})
            self.assertEqual(target.read_text(), 'broken')


class ProjectPromptIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_right_click_edit_five_sentences_preserves_text_export_and_original_config(self):
        from PIL import Image
        from PyQt6.QtCore import QItemSelectionModel
        from views.main_window import MainWindow
        from views.project_prompt_dialog import ProjectPromptEditDialog
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            project = root / 'projects' / 'sample'
            downloads = project / 'downloads'
            downloads.mkdir(parents=True)
            Image.new('RGB', (8, 8)).save(downloads / '1.png')
            (root / '.app_config.json').write_text(json.dumps({
                'base_path': str(project.parent), 'enable_plugin_server': False}), encoding='utf-8')
            (root / 'prompt_templates.json').write_text(json.dumps([
                {'id': 'stage', 'name': '舞台', 'content': '舞台 观众 手持话筒 {spanish_text} {camera_motion}'},
                {'id': 'question', 'name': '提问', 'content': '提问 观众 手持话筒 {spanish_text} {camera_motion}'},
            ], ensure_ascii=False), encoding='utf-8')
            model = ProjectModel(project)
            model.selected_template_id = 'stage'
            model.spanish_segments = [{'text': f'Hola amigos {i}', 'image_name': '1.png', 'duration': 6,
                                       'template_id': 'question' if i == 9 else 'stage'} for i in range(10)]
            model.save()
            window = MainWindow(root)
            try:
                detail = window.detail_widget
                detail.set_project(project)
                names = ['prompt_templates.json', 'camera_motions.json', 'batch_templates.json', '.app_config.json']
                original_files = {name: (root / name).read_bytes() for name in names}
                original_templates = copy.deepcopy(window.template_manager.templates)
                sources = {i: detail.get_project_prompt_source(i) for i in range(5)}
                dialog = ProjectPromptEditDialog(sources, detail.apply_project_prompt_edits)
                try:
                    self.assertNotIn('Hola amigos', dialog.template_content())
                    self.assertFalse(dialog.save_button.isEnabled())
                    dialog.editors[0].setPlainText('舞台 男性观众 佩戴式话筒 ')
                    self.assertEqual(len(dialog.updates), 5)
                    dialog.save()
                    self.assertEqual(dialog.result(), dialog.DialogCode.Accepted)
                finally:
                    dialog.close()
                # Context-menu selection keeps multiple selected rows together.
                detail.table_segments.clearSelection()
                for row in range(5):
                    detail.table_segments.selectionModel().select(detail.table_segments.model().index(row, 0),
                        QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
                self.assertEqual(detail.selected_prompt_rows(), list(range(5)))
                with patch('views.project_detail_widget.QMenu.exec') as menu_exec:
                    point = detail.table_segments.visualItemRect(detail.table_segments.item(2, 1)).center()
                    detail.show_segment_prompt_menu(point)
                    self.assertTrue(menu_exec.called)
                self.assertEqual(detail.selected_prompt_rows(), list(range(5)))
                with patch('PyQt6.QtWidgets.QMessageBox.information') as blocked:
                    detail.table_segments.selectRow(9)
                    detail.table_segments.selectionModel().select(detail.table_segments.model().index(0, 0),
                        QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
                    detail.edit_selected_prompts()
                    blocked.assert_called_once()
                loaded = ProjectModel(project)
                records = [loaded.prompt_store.get(segment) for segment in loaded.spanish_segments]
                self.assertEqual(sum('男性观众' in record.get('content', '') for record in records), 5)
                self.assertTrue(all(record == {} for record in records[5:]))
                self.assertEqual([segment['text'] for segment in loaded.spanish_segments],
                                 [f'Hola amigos {i}' for i in range(10)])
                detail.set_project(project)
                exported = [task for batch in detail.build_batches()['batches'] for task in batch]
                self.assertEqual(sum('男性观众' in task['prompt'] for task in exported), 5)
                packed = detail.pack_batch_for_capacity(500)
                self.assertEqual(sum('佩戴式话筒' in task['prompt'] for task in packed), 5)
                hosted, errors = window.hosted_mode._collect_project_batches(False)
                self.assertEqual(errors, [])
                self.assertEqual(sum('男性观众' in task['prompt'] for batch in hosted for task in batch['tasks']), 5)
                self.assertEqual(window.template_manager.templates, original_templates)
                for name, original in original_files.items():
                    self.assertEqual((root / name).read_bytes(), original, name)
            finally:
                window.close()
