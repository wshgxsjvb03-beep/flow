const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const source = fs.readFileSync(path.join(__dirname, '../extension/injects/ui.js'), 'utf8');
// Exercise the production functions without starting the extension's page/UI lifecycle.
function extract(name) {
  const declarations = [...source.matchAll(/^  (?:async )?function (\w+)\(/gm)];
  const index = declarations.findIndex(match => match[1] === name);
  assert.ok(index >= 0, name);
  return source.slice(declarations[index].index, declarations[index + 1]?.index || source.length);
}
const state = { tasks: [], settings: { aspectRatio: 'ASPECT_RATIO_9_16', videoModel: 'omni_1_1_flash' } };
let pageImages = [];
const context = vm.createContext({
  state, console: { log() {}, warn() {} }, window: {},
  document: { getElementById: () => null, querySelector: () => null, querySelectorAll: () => [] },
  getLoadedPageImages: () => pageImages,
  cleanCompactName: name => String(name || '').toLowerCase().replace(/\s+/g, ''),
  isImageNameMatch: (a, b) => a === b,
  splitTextToLines: text => text.split('\n').filter(Boolean),
  extractTileDisplayName: element => element.name || '',
  delay: async () => {},
});
for (const name of ['getFilenameFromPath', 'normalizeDuration', 'isStrictImageMatch',
  'normalizeEndImage', 'getTaskFrameReceipt', 'resolveTaskImages', 'getTaskUploadName', 'findStrictPageImage',
  'getTasksNeedingUpload', 'importTaskList', 'getFrameTrigger', 'flowImageMediaId', 'matchesFrameIdentity', 'exactFlowImageName', 'flowImageSource',
  'isRemoveMediaButton', 'getFramePickerButton', 'findMediaConfirmButton', 'attachImageToPage',
  'verifyImageAttached', 'getFlowEditor', 'verifyFlowPrompt', 'assertFlowTaskReady',
  'writeFlowPrompt', 'submitTaskToPage']) {
  vm.runInContext(extract(name), context);
}

async function run() {
  if (process.argv[2]) {
    const wire = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
    assert.equal(wire.action, 'run_tasks');
    const received = wire.params.tasks;
    assert.equal(context.importTaskList(received), received.length);
    received.forEach((item, index) => {
      assert.equal(state.tasks[index].endImage?.displayName || '', item.end_image_name || '');
      assert.equal(state.tasks[index].endImage?.localImagePath || '', item.end_local_image_path || '');
    });
    console.log(`Hosted RPC audit passed: ${received.length} tasks, ${state.tasks.filter(t => t.endImage).length} end frames received.`);
    state.tasks = [];
  }
  context.importTaskList([{
    prompt: 'Hello', image_name: 'start.png', local_image_path: 'C:\\images\\start.png',
    image_data_url: 'data:image/png;base64,c3RhcnQ=', end_image_name: 'end.png',
    end_local_image_path: 'C:\\images\\end.png', end_image_data_url: 'data:image/png;base64,ZW5k',
  }]);
  const task = state.tasks[0];
  assert.deepEqual(JSON.parse(JSON.stringify(context.getTaskFrameReceipt(state.tasks))),
    [{ row: 0, first: 'start.png', last: 'end.png' }]);
  assert.equal(task.image.src, 'data:image/png;base64,c3RhcnQ=');
  assert.equal(task.endImage.displayName, 'end.png');
  assert.equal(task.endImage.localImagePath, 'C:\\images\\end.png');
  assert.equal(task.endImage.src, 'data:image/png;base64,ZW5k');
  assert.deepEqual(Array.from(context.getTasksNeedingUpload(), item => item.name), ['start.png', 'end.png']);
  pageImages = [{ displayName: 'start.png', id: 'start-id' }];
  assert.deepEqual(Array.from(context.getTasksNeedingUpload(), item => item.name), ['end.png']);
  pageImages.push({ displayName: 'end.png', id: 'end-id', src: 'https://example.test/end.png' });
  context.resolveTaskImages(task, pageImages);
  assert.equal(task.endImage.id, 'end-id');
  assert.equal(task.image.id, 'start-id');
  assert.equal(context.getTasksNeedingUpload().length, 0);
  assert.equal(context.normalizeEndImage({}), null);
  assert.equal(context.normalizeEndImage({ endImageName: 'alias.png', endImageDataUrl: 'data:image/png;base64,YQ==' }).displayName, 'alias.png');

  const slot = (label, name = '') => ({
    name, textContent: label, getAttribute: () => '',
    querySelector: selector => selector === 'img' && name ? { src: 'preview' } : null,
  });
  const first = slot('开始', 'start.png');
  const last = slot('结束', 'end.png');
  const bar = { querySelectorAll: () => [first, last] };
  delete context.window.promptBoxStore;
  context.document.querySelector = () => bar;
  assert.equal(context.getFrameTrigger(bar, 'last'), last);
  assert.equal(context.getFrameTrigger({ querySelectorAll: () => [first] }, 'last'), null);
  assert.equal(context.verifyImageAttached(task.endImage, 'VIDEO_FRAMES', 'last'), true);
  await context.attachImageToPage(task.endImage, 'VIDEO_FRAMES', 'last');
  assert.equal(first.name, 'start.png');
  last.name = 'wrong.png';
  assert.equal(context.verifyImageAttached(task.endImage, 'VIDEO_FRAMES', 'last'), false);
  await assert.rejects(context.submitTaskToPage({ endImage: task.endImage, footageType: 'VIDEO_REFERENCES' }), /必须使用帧模式/);
  context.document.querySelector = () => null;
  await assert.rejects(context.attachImageToPage(task.endImage, 'VIDEO_FRAMES', 'last'), /未找到/);
  console.log('End-frame regression checks passed: import, upload, binding, slots, and submission guards.');
}
run().catch(error => { console.error(error); process.exitCode = 1; });
