import base64
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

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
        for origin in ('https://docs.google.com', 'https://labs.google', 'chrome-extension://' + 'a' * 32):
            self.assertTrue(server._is_allowed_origin(origin), origin)
        for origin in ('null', 'https://docs.google.com.evil.example', 'https://evil.example',
                       'chrome-extension://sample', 'http://docs.google.com', 'file://',
                       'https://docs.google.com:8080', 'https://user@docs.google.com',
                       'https://docs.google.com/path', 'http://localhost'):
            self.assertFalse(server._is_allowed_origin(origin), origin)

    def test_websocket_batch_encodes_both_frames_without_changing_original_task(self):
        from services.plugin_server import PluginServer
        with tempfile.TemporaryDirectory() as folder:
            start = Path(folder, 'start.png')
            end = Path(folder, 'end.png')
            start.write_bytes(b'start-frame')
            end.write_bytes(b'end-frame')
            task = {'local_image_path': str(start), 'end_local_image_path': str(end),
                    'end_image_name': end.name}
            server = PluginServer()
            socket = Mock()
            server.clients[socket] = {'client_id': 'test'}
            with patch('base64.b64encode', wraps=base64.b64encode) as encode:
                self.assertTrue(server.send_tasks_to_client('test', 'batch', [task] * 10))
                self.assertEqual(encode.call_count, 2)
            payload = json.loads(socket.sendTextMessage.call_args.args[0])
            sent = payload['tasks'][0]
            self.assertEqual(sent['image_data_url'], 'data:image/png;base64,c3RhcnQtZnJhbWU=')
            self.assertEqual(sent['end_image_data_url'], 'data:image/png;base64,ZW5kLWZyYW1l')
            self.assertNotIn('end_image_data_url', task)
            end.write_bytes(b'updated-end-frame')
            self.assertTrue(server.send_tasks_to_client('test', 'next-batch', [task]))
            updated = json.loads(socket.sendTextMessage.call_args.args[0])['tasks'][0]
            self.assertEqual(updated['end_image_data_url'],
                             'data:image/png;base64,' + base64.b64encode(end.read_bytes()).decode())
            self.assertEqual(updated['endImageDataUrl'], updated['end_image_data_url'])

    def test_main_window_loads_legacy_project_and_exports_new_generation_fields(self):
        from views.main_window import MainWindow
        from models.project_model import ProjectModel
        from PIL import Image
        with tempfile.TemporaryDirectory() as folder, \
                patch('PyQt6.QtWidgets.QMessageBox.information'):
            root = Path(folder)
            storage = root / 'projects'
            project = storage / 'legacy'
            downloads = project / 'downloads'
            downloads.mkdir(parents=True)
            Image.new('RGB', (8, 8)).save(downloads / '1.png')
            Image.new('RGB', (8, 8), 'blue').save(downloads / 'end.png')
            config = {'base_path': str(storage), 'enable_plugin_server': False,
                      'task_interval': 9, 'default_aspect_ratio': '16:9'}
            (root / '.app_config.json').write_text(json.dumps(config), encoding='utf-8')
            model = ProjectModel(project)
            model.enable_end_frame = True
            model.spanish_segments = [{'text': 'Hola amigos ' * 5, 'image_name': '1.png',
                                       'end_image_name': 'end.png', 'duration': 6}]
            model.selected_template_id = 'test'
            model.save()
            (root / 'prompt_templates.json').write_text(json.dumps([
                {'id': 'test', 'name': 'Test', 'content': '{spanish_text} {camera_motion}'}
            ]), encoding='utf-8')
            window = MainWindow(root)
            try:
                detail = window.detail_widget
                original_metadata = (project / 'metadata.json').read_bytes()
                with patch.object(ProjectModel, 'save', autospec=True, side_effect=ProjectModel.save) as save, \
                        patch('base64.b64encode', wraps=base64.b64encode) as encode, \
                        patch.object(detail, 'populate_segments_table', wraps=detail.populate_segments_table) as render:
                    detail.set_project(project)
                    self.assertEqual(render.call_count, 1)
                    result = detail.build_batches()
                    packed = detail.pack_batch_for_capacity(50)
                    self.assertEqual(packed[0]['end_image_name'], 'end.png')
                    # Global hosted mode uses build_batches -> collection -> run_tasks,
                    # rather than send_tasks_to_client's execute_tasks path.
                    hosted = window.hosted_mode
                    batches, errors = hosted._collect_project_batches(False)
                    self.assertEqual(errors, [])
                    self.assertEqual(batches[0]['tasks'][0]['end_image_name'], 'end.png')
                    self.assertEqual(batches[0]['tasks'][0]['end_local_image_path'], str((downloads / 'end.png').resolve()))
                    self.assertIn(str((downloads / 'end.png').resolve()), batches[0]['images'])
                    from services.plugin_server import PluginServer
                    rpc_server = PluginServer()
                    socket = Mock()
                    rpc_server.clients[socket] = {'client_id': 'hosted-test'}
                    batch = batches[0]
                    batch.update(cid='hosted-test', email='test', upload_state='成功')
                    entry = {'batch_ids': [batch['id']], 'email': 'test', 'cid': 'hosted-test'}
                    hosted.batches = batches
                    hosted.running = True
                    with patch.object(hosted, 'plugin_server', rpc_server), \
                            patch.object(hosted, '_resolve_client', return_value={'client_id': 'hosted-test'}), \
                            patch.object(hosted, 'refresh_all'):
                        hosted._dispatch_next(entry)
                    hosted.running = False
                    wire = json.loads(socket.sendTextMessage.call_args.args[0])
                    self.assertEqual(wire['action'], 'run_tasks')
                    self.assertEqual(wire['params']['tasks'][0]['end_image_name'], 'end.png')
                    self.assertEqual(wire['params']['tasks'][0]['end_local_image_path'], str((downloads / 'end.png').resolve()))
                    save.assert_not_called()
                    encode.assert_not_called()
                    self.assertEqual((project / 'metadata.json').read_bytes(), original_metadata)

                    # Association still resolves automatically; callers can explicitly request image data.
                    segment = detail.project_model.spanish_segments[0]
                    segment['image_name'] = ''
                    name, _, data = detail.resolve_segment_image_and_data(0, segment, encode_data=False)
                    self.assertEqual(name, '1.png')
                    self.assertEqual(data, '')
                    _, _, data = detail.resolve_segment_end_image_and_data(0, segment)
                    self.assertTrue(data.startswith('data:image/png;base64,'))
                    self.assertEqual(encode.call_count, 1)

                    # Manual completion changes save immediately, but repainting does not.
                    detail.change_row_color(0, copied=True)
                    self.assertEqual(save.call_count, 1)
                    self.assertTrue(json.loads((project / 'metadata.json').read_text())['spanish_segments'][0]['copied'])
                    detail.update_segment_row_prompt(0)
                    detail.change_row_color(0, copied=True)
                    self.assertEqual(save.call_count, 1)
                    detail.on_cell_double_clicked(0, 3)
                    self.assertEqual(save.call_count, 2)
                self.assertEqual(result['error'], '')
                task = result['batches'][0][0]
                self.assertEqual(task['duration'], 6)
                self.assertEqual(task['interval'], 9)
                self.assertEqual(task['aspect_ratio'], '16:9')
                self.assertTrue(Path(task['local_image_path']).is_file())
                self.assertEqual(task['end_image_name'], 'end.png')
                self.assertEqual(Path(task['end_local_image_path']), downloads / 'end.png')
                self.assertIn('Hola amigos', task['prompt'])
            finally:
                window.close()


if __name__ == '__main__':
    unittest.main()
