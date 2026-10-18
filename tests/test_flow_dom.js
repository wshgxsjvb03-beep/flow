// Replay production automation against a sanitized snapshot of the user's saved Flow DOM.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { randomUUID } = require('node:crypto');
let JSDOM;
try { ({ JSDOM } = require('jsdom')); }
catch { ({ JSDOM } = require('../scratch/flow-dom-runtime/node_modules/jsdom')); }
const source = fs.readFileSync(path.join(__dirname, '../extension/injects/ui.js'), 'utf8');
const fixture = fs.readFileSync(path.join(__dirname, 'fixtures/flow-page.html'), 'utf8');
function extract(name) {
  const declarations = [...source.matchAll(/^  (?:async )?function (\w+)\(/gm)];
  const index = declarations.findIndex(match => match[1] === name);
  assert.ok(index >= 0, name);
  return source.slice(declarations[index].index, declarations[index + 1]?.index || source.length);
}

function harness(options = {}) {
  const dom = new JSDOM(fixture, { url: 'https://labs.google/fx/tools/flow/project/fixture', runScripts: 'outside-only' });
  const w = dom.window;
  const doc = w.document;
  const template = doc.querySelector('.cdk-overlay-pane').cloneNode(true);
  doc.querySelector('.cdk-overlay-pane').remove();
  const slots = [...doc.querySelectorAll('.ingredient-bar-container > .frame-trigger')];
  const generated = [];
  const clicks = [];
  const browserErrors = [];
  let prompt = '';
  w.console = { log() {}, warn() {} };
  w.addEventListener('error', event => { browserErrors.push(event.error); event.preventDefault(); });
  w.state = { tasks: [{}, {}, {}, {}], settings: {}, activeTasksQueue: [] };
  w.delay = async () => {};
  w.isStopRequested = false;
  w.syncPageVideoSettings = async () => {};
  w.sendToExtension = async () => ({ ok: true });
  w.saveState = async () => { if (options.clearDuringSave) setPrompt(''); };
  w.resolveDownloadPath = () => 'Flow/test.mp4';
  w.getStorageKey = () => 'fixture';
  Object.defineProperty(w.crypto, 'randomUUID', { value: randomUUID });
  const helpers = ['isSystemHotbarLabel', 'extractTileDisplayName', 'normalizeNameHelper', 'cleanCompactName',
    'getLoadedPageImages', 'getFilenameFromPath', 'isStrictImageMatch', 'exactFlowImageName', 'flowImageSource',
    'normalizeDuration', 'normalizeEndImage', 'resolveTaskImages', 'getTaskUploadName', 'findStrictPageImage', 'importTaskList',
    'getFrameTrigger', 'flowImageMediaId', 'matchesFrameIdentity', 'isRemoveMediaButton', 'findFlowPickerAsset', 'waitForFlowState', 'attachImageToPage', 'clearUnusedFlowEndFrame',
    'verifyImageAttached', 'getFlowEditor', 'verifyFlowPrompt', 'assertFlowTaskReady', 'writeFlowPrompt',
    'cleanupPageOverlays', 'simulateClick', 'submitTaskToPage', 'createTaskFramePreview', 'renderTable'];
  w.splitTextToLines = text => text.split('\n').filter(Boolean);
  for (const name of helpers) w.eval(extract(name));
  const images = w.getLoadedPageImages();
  assert.equal(images.length, 4, 'The real snapshot has four image assets and one video');

  function setPrompt(value) {
    prompt = value;
    const editor = doc.querySelector('.ProseMirror');
    editor.replaceChildren(...value.split('\n').map(line => {
      const p = doc.createElement('p'); p.textContent = line; return p;
    }));
  }
  const view = {
    state: {
      doc: { content: { size: 0 }, textBetween: () => prompt },
      schema: { text: value => value, nodes: {
        paragraph: { create: (_, value = '') => value },
        doc: { create: (_, paragraphs) => ({ content: paragraphs.join('\n') }) },
      } },
      tr: { replaceWith: (_, __, value) => value },
    },
    dispatch: value => {
      setPrompt(value);
      // Test both the actual separate media bar and a page re-render that resets it.
      if (options.resetFramesOnPrompt) {
        for (const [i, slot] of slots.entries()) slot.innerHTML = `<button class="empty-chip">${i ? '结束' : '开始'}</button>`;
      }
    },
  };
  doc.querySelector('.ProseMirror').pmViewDesc = { view };

  function readSlot(slot) {
    return slot.querySelector('img')?.getAttribute('data-media-id') || null;
  }
  function openPicker(slotIndex) {
    const pane = template.cloneNode(true);
    const picker = pane.querySelector('flow-add-menu-popover-content');
    doc.querySelector('.cdk-overlay-container').append(pane);
    picker.querySelector('.header-close-btn').addEventListener('click', () => { clicks.push('close-picker'); pane.remove(); });
    const opts = [...picker.querySelectorAll('button.asset-item')];
    if (options.duplicateName) {
      opts[1].querySelector('.asset-title').textContent = opts[0].querySelector('.asset-title').textContent;
    }
    const preview = picker.querySelector('.detail-preview-image');
    // Real snapshot starts with a different active item: only an explicit row click changes it.
    opts.forEach((opt, index) => opt.addEventListener('click', () => {
      clicks.push(`select:${index}`);
      opts.forEach(item => item.setAttribute('aria-selected', String(item === opt)));
      preview.src = opt.querySelector('img.asset-thumbnail-image').src;
      preview.alt = opt.querySelector('.asset-title').textContent;
    }));
    if (options.initiallyHiddenIndex !== undefined) {
      const hidden = opts[options.initiallyHiddenIndex].closest('.asset-item-container');
      const list = hidden.parentElement;
      hidden.remove();
      picker.querySelector('input.search-input').addEventListener('input', () => list.append(hidden));
    }
    picker.querySelector('.detail-add-to-prompt-btn').addEventListener('click', () => {
      clicks.push(`add:${slotIndex}`);
      const selected = opts.find(item => item.getAttribute('aria-selected') === 'true');
      assert.ok(selected, 'A row must be selected before clicking Add to prompt');
      const image = images.find(item => item.displayName === selected.querySelector('.asset-title').textContent.trim());
      const chip = doc.createElement('flow-image-ingredient-chip');
      chip.title = image.displayName;
      const img = doc.createElement('img');
      img.src = options.cdnChips ? `https://flow-content.google/image/${image.id}?Expires=123&Signature=changing` : image.src;
      img.alt = options.cdnChips ? '素材图片' : image.displayName;
      if (!options.cdnChips) img.setAttribute('data-media-id', options.wrongFirst && slotIndex === 0 ? 'wrong-id' : image.id);
      const remove = doc.createElement('button');
      remove.className = 'chip-container';
      remove.setAttribute('aria-label', '图片素材');
      remove.innerHTML = '<div class="hover-icon-overlay"><mat-icon>cancel</mat-icon></div>';
      remove.prepend(img);
      remove.addEventListener('click', event => {
        event.stopPropagation();
        clicks.push(`remove:${slotIndex}`);
        slots[slotIndex].innerHTML = `<button class="empty-chip">${slotIndex ? '结束' : '开始'}</button>`;
      });
      chip.append(remove);
      slots[slotIndex].replaceChildren(chip);
      pane.remove();
      if (options.clearPromptOnLast && slotIndex === 1) setPrompt('');
    });
  }
  slots.forEach((slot, index) => slot.addEventListener('click', event => {
    // Live browser: only the empty button opens the picker. Clicking the outer
    // populated frame-trigger does nothing; the chip button removes the frame.
    if (!event.target.closest('button.empty-chip')) return;
    clicks.push(`open:${index}`);
    openPicker(index);
  }));
  for (const button of doc.querySelectorAll('flow-image-hotbar button, flow-video-hotbar button, .clear-button')) {
    button.addEventListener('click', () => { throw new Error('Unrelated toolbar controls must never be clicked'); });
  }
  const generate = doc.querySelector('flow-generate-icon-button button[type="submit"]');
  generate.disabled = !!options.disabledButton;
  generate.addEventListener('click', event => {
    event.preventDefault();
    assert.ok(prompt.trim());
    generated.push({ prompt, first: readSlot(slots[0]), last: readSlot(slots[1]) });
  });
  function params(index) {
    return { image: images[index % images.length], endImage: images[(index + 1) % images.length],
      lineText: `Prompt ${index}\nSecond paragraph`, footageType: 'VIDEO_FRAMES', count: 1,
      duration: 8, rowIndex: index, lineIndex: 0 };
  }
  return { w, dom, doc, images, params, generated, clicks, openPicker, browserErrors };
}

async function run() {
  const cdn = harness({ cdnChips: true });
  try {
    for (let i = 0; i < 4; i++) {
      const params = cdn.params(i);
      params.checkOnly = true;
      await cdn.w.submitTaskToPage(params);
      assert.equal(cdn.w.verifyImageAttached(params.image, 'VIDEO_FRAMES'), true);
      assert.equal(cdn.w.verifyImageAttached(params.endImage, 'VIDEO_FRAMES', 'last'), true);
      assert.equal(cdn.w.verifyImageAttached(params.endImage, 'VIDEO_FRAMES'), false);
    }
    assert.equal(cdn.generated.length, 0);
    assert.equal(cdn.w.flowImageMediaId('https://evil.invalid/image/fake'), '');
  } finally { cdn.dom.window.close(); }
  const inspection = harness();
  try {
    const params = inspection.params(0);
    params.checkOnly = true;
    await inspection.w.submitTaskToPage(params);
    assert.equal(inspection.generated.length, 0, 'Inspection must never generate');
    assert.equal(inspection.clicks.filter(value => value.startsWith('add:')).length, 2);
    assert.equal(params.submissionId, undefined, 'Inspection must not register a generation');
    assert.deepEqual(inspection.w.state.tasks[0], {});
  } finally { inspection.dom.window.close(); }
  const normal = harness();
  try {
    normal.openPicker(0); // a stale picker must be closed through its own header button
    for (let i = 0; i < 4; i++) await normal.w.submitTaskToPage(normal.params(i));
    assert.equal(normal.generated.length, 4);
    for (let i = 0; i < 4; i++) assert.deepEqual(normal.generated[i], {
      prompt: `Prompt ${i}\nSecond paragraph`, first: normal.images[i].id, last: normal.images[(i + 1) % 4].id,
    });
    assert.equal(normal.clicks.filter(value => value.startsWith('add:')).length, 8);
    assert.ok(normal.clicks.includes('close-picker'));
    assert.equal(normal.clicks.filter(value => value.startsWith('remove:')).length, 6);
    const removals = normal.clicks.filter(value => value.startsWith('remove:')).length;
    const unchanged = normal.params(3);
    unchanged.checkOnly = true;
    await normal.w.submitTaskToPage(unchanged);
    assert.equal(normal.clicks.filter(value => value.startsWith('remove:')).length, removals,
      'Matching frames must be retained');
    assert.deepEqual(normal.browserErrors, []);
    assert.equal(normal.w.isStrictImageMatch('image_1.jpeg', 'image_10.jpeg'), false);
    assert.equal(normal.w.isStrictImageMatch('image-1.jpeg', 'image1.jpeg'), false);
    const requestedName = normal.images[0].displayName.replace(/\.jpeg$/, ' copy.jpeg');
    normal.w.importTaskList([{ prompt: 'New task', image_name: requestedName,
      end_image_name: normal.images[1].displayName }]);
    const imported = normal.w.state.tasks.at(-1);
    assert.equal(imported.image.displayName, requestedName);
    assert.equal(imported.image.id, null, 'A similar filename must not replace the requested image');
    assert.equal(imported.endImage.id, normal.images[1].id);
    const singleFrame = normal.params(0);
    delete singleFrame.endImage;
    await normal.w.submitTaskToPage(singleFrame);
    assert.equal(normal.generated[4].last, null);
    assert.ok(normal.clicks.includes('remove:1'));
    assert.equal(normal.generated[4].first, normal.images[0].id);
    assert.deepEqual(normal.browserErrors, []);
  } finally { normal.dom.window.close(); }
  for (const [options, expected] of [
    [{ clearPromptOnLast: true }, /提示词/],
    [{ wrongFirst: true }, /对应槽位/],
    [{ disabledButton: true }, /生成按钮尚未就绪/],
    [{ clearDuringSave: true }, /提示词/],
  ]) {
    const scenario = harness(options);
    try {
      await assert.rejects(scenario.w.submitTaskToPage(scenario.params(0)), expected);
      assert.equal(scenario.generated.length, 0);
    } finally { scenario.dom.window.close(); }
  }
  const duplicates = harness({ duplicateName: true });
  try {
    duplicates.openPicker(0);
    const panel = duplicates.doc.querySelector('flow-add-menu-popover-content');
    assert.throws(() => duplicates.w.findFlowPickerAsset(panel, { displayName: duplicates.images[0].displayName }), /重名/);
  } finally { duplicates.dom.window.close(); }
  const reset = harness({ resetFramesOnPrompt: true });
  try {
    for (let i = 0; i < 4; i++) await reset.w.submitTaskToPage(reset.params(i));
    assert.equal(reset.generated.length, 4);
    assert.deepEqual(reset.browserErrors, []);
  } finally { reset.dom.window.close(); }
  const search = harness({ initiallyHiddenIndex: 0 });
  try {
    await search.w.submitTaskToPage(search.params(0));
    assert.equal(search.generated[0].first, search.images[0].id);
    assert.deepEqual(search.browserErrors, []);
  } finally { search.dom.window.close(); }
  const importedPreview = harness();
  try {
    const { w, doc, images } = importedPreview;
    const table = doc.createElement('table');
    table.id = 'flow-tasks-table';
    table.appendChild(doc.createElement('tbody'));
    doc.body.appendChild(table);
    w.setSafeHTML = (element, html) => { element.innerHTML = html; };
    w.renderTableStatusCell = () => {};
    w.state.presets = [];
    w.state.tasks = [];
    w.importTaskList([{ prompt: 'Imported first and last frames', image_name: images[0].displayName,
      end_image_name: images[1].displayName, end_local_image_path: 'C:\\images\\last.jpeg' }]);
    w.renderTable();
    const first = table.querySelector('[data-frame-role="first"]');
    const last = table.querySelector('[data-frame-role="last"]');
    assert.equal(first.querySelector('img').src, images[0].src);
    assert.equal(last.querySelector('img').src, images[1].src);
    assert.equal(last.querySelector('.cell-image-name').textContent, images[1].displayName);
    assert.equal(last.dataset.previewState, 'ready');

    w.state.tasks[0].endImage = { displayName: 'not-uploaded.jpeg', localImagePath: 'C:\\images\\not-uploaded.jpeg' };
    w.renderTable();
    const pending = table.querySelector('[data-frame-role="last"]');
    assert.equal(pending.querySelector('img'), null);
    assert.equal(pending.querySelector('.task-frame-status').textContent, '已收到路径，待上传');
    assert.equal(pending.dataset.previewState, 'pending');

    w.state.tasks[0].endImage = null;
    w.renderTable();
    assert.equal(table.querySelector('[data-frame-role="last"]').dataset.previewState, 'unset');
    assert.deepEqual(importedPreview.browserErrors, []);
  } finally { importedPreview.dom.window.close(); }
  console.log('Real Flow DOM replay passed: four tasks, eight explicit Add-to-prompt clicks, correct frame identities, no unrelated toolbar clicks, and guarded failure cases.');
}
run().catch(error => { console.error(error); process.exitCode = 1; });
