import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from models.config_manager import ConfigManager


class ConfigRegressionTests(unittest.TestCase):
    def test_first_run_env_keys_are_rotated_without_being_saved(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {
            'GLADIA_API_KEYS': 'first,second\nthird',
            'ELEVENLABS_API_KEY': 'single',
        }, clear=True):
            config = ConfigManager(folder)
            self.assertEqual([config.get_next_gladia_key() for _ in range(4)],
                             ['first', 'second', 'third', 'first'])
            self.assertEqual(config.get_next_elevenlabs_key(), 'single')
            config.task_interval = 12
            config.default_aspect_ratio = '16:9'
            self.assertTrue(config.save())
            saved = json.loads(config.config_path.read_text(encoding='utf-8'))
            self.assertEqual(saved['gladia_api_keys'], [])
            self.assertEqual(saved['elevenlabs_api_keys'], [])
            reloaded = ConfigManager(folder)
            self.assertEqual(reloaded.task_interval, 12)
            self.assertEqual(reloaded.default_aspect_ratio, '16:9')

    def test_invalid_generation_defaults_fall_back(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, '.app_config.json').write_text(json.dumps({
                'task_interval': 'bad', 'default_video_model': 'missing',
                'default_generation_mode': 'missing', 'default_aspect_ratio': 'missing',
            }), encoding='utf-8')
            config = ConfigManager(folder)
            self.assertEqual(config.task_interval, config.DEFAULT_TASK_INTERVAL)
            self.assertEqual(config.default_video_model, config.DEFAULT_VIDEO_MODEL)
            self.assertEqual(config.default_generation_mode, config.DEFAULT_GENERATION_MODE)


class MigrationRegressionTests(unittest.TestCase):
    def test_settings_migrate_once_and_relative_storage_keeps_its_location(self):
        import main
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            old = root / 'application'
            old.mkdir()
            (old / '.app_config.json').write_text(json.dumps({'base_path': 'projects'}))
            for name in ('prompt_templates.json', 'batch_templates.json', 'hosted_mode.json', '.env'):
                (old / name).write_text('[]', encoding='utf-8')
            with patch.dict(os.environ, {'APPDATA': str(root / 'appdata')}), \
                    patch.object(main, 'get_workspace_dir', return_value=str(old)):
                destination = Path(main.get_data_dir())
                saved = json.loads((destination / '.app_config.json').read_text())
                self.assertEqual(Path(saved['base_path']), old / 'projects')
                self.assertTrue((destination / '.env').exists())
                self.assertTrue((destination / 'hosted_mode.json').exists())
                self.assertTrue((destination / 'batch_templates.json').exists())
                (destination / 'prompt_templates.json').write_text('["custom"]')
                main.get_data_dir()
                self.assertEqual((destination / 'prompt_templates.json').read_text(), '["custom"]')


class IntegrationRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_websocket_origin_validation_supports_vids_and_rejects_spoofed_hosts(self):
        from services.plugin_server import PluginServer
        server = PluginServer()
        for origin in ('https://docs.google.com', 'https://labs.google', 'chrome-extension://sample'):
            self.assertTrue(server._is_allowed_origin(origin), origin)
        for origin in ('null', 'https://docs.google.com.evil.example', 'https://evil.example'):
            self.assertFalse(server._is_allowed_origin(origin), origin)

    def test_main_window_loads_legacy_project_and_exports_new_generation_fields(self):
        from views.main_window import MainWindow
        from models.project_model import ProjectModel
        from PIL import Image
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(MainWindow, '_silent_update_check'), \
                patch('PyQt6.QtWidgets.QMessageBox.information'):
            root = Path(folder)
            storage = root / 'projects'
            project = storage / 'legacy'
            downloads = project / 'downloads'
            downloads.mkdir(parents=True)
            Image.new('RGB', (8, 8)).save(downloads / '1.png')
            config = {'base_path': str(storage), 'enable_plugin_server': False,
                      'task_interval': 9, 'default_aspect_ratio': '16:9'}
            (root / '.app_config.json').write_text(json.dumps(config), encoding='utf-8')
            model = ProjectModel(project)
            model.spanish_segments = [{'text': 'Hola amigos ' * 5, 'image_name': '1.png', 'duration': 6}]
            model.selected_template_id = 'test'
            model.save()
            (root / 'prompt_templates.json').write_text(json.dumps([
                {'id': 'test', 'name': 'Test', 'content': '{spanish_text} {camera_motion}'}
            ]), encoding='utf-8')
            window = MainWindow(root)
            try:
                window.detail_widget.set_project(project)
                result = window.detail_widget.build_batches()
                self.assertEqual(result['error'], '')
                task = result['batches'][0][0]
                self.assertEqual(task['duration'], 6)
                self.assertEqual(task['interval'], 9)
                self.assertEqual(task['aspect_ratio'], '16:9')
                self.assertTrue(Path(task['local_image_path']).is_file())
                self.assertIn('Hola amigos', task['prompt'])
            finally:
                window.close()


if __name__ == '__main__':
    unittest.main()
