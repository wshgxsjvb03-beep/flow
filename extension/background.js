// background.js - 后台 Service Worker，负责处理下载任务、路径重定向与配置持久化

// 1. 监听来自 content-isolated.js 的消息
function isTrustedPage(url) {
  try {
    const parsed = new URL(url);
    const host = parsed.hostname;
    return parsed.protocol === 'https:' && !parsed.username && !parsed.password &&
      (!parsed.port || parsed.port === '443') &&
      (host === 'flow.google.com' || host.endsWith('.flow.google.com') ||
       host === 'labs.google' || host.endsWith('.labs.google') ||
       (host === 'docs.google.com' && parsed.pathname.startsWith('/videos/')));
  } catch (_) { return false; }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (sender.id !== chrome.runtime.id || sender.frameId !== 0 || sender.tab?.id == null ||
      !isTrustedPage(sender.url) || !isTrustedPage(sender.tab.url) ||
      !message || typeof message !== 'object' || Array.isArray(message)) {
    sendResponse({ error: '消息来源不受信任' });
    return;
  }
  // 后台版本握手：用于检测「网页脚本已更新但插件后台仍是旧版本」的情况
  if (message.action === "getBgVersion") {
    sendResponse({ version: chrome.runtime.getManifest().version, nativeDrag: !!(chrome.debugger && chrome.debugger.attach) });
    return;
  }
  // 兼容旧桥接消息；不再用全局当前任务重命名任何下载。
  if (["setActiveTask", "clearActiveTask"].includes(message.action)) {
    sendResponse({ success: true });
    return;
  }

  console.log(`[Background] 收到操作: ${message.action}`);

  if (message.action === "download") {
    handleDownload(message.url, message.filename, { ...message.task, tabId: sender.tab?.id, frameId: sender.frameId })
      .then(result => {
        console.log(`[Background] handleDownload 处理完毕返回:`, result);
        sendResponse(result);
      })
      .catch(err => {
        console.error(`[Background] handleDownload 处理异常:`, err);
        sendResponse({ error: err.message });
      });
    return true; // 保持通道开启以进行异步响应
  }

  if (message.action === "getDownloadStatus") {
    if (!Number.isSafeInteger(message.downloadId) || message.downloadId < 0) {
      sendResponse({ error: '下载 ID 无效' }); return;
    }
    chrome.downloads.search({ id: message.downloadId }).then(items => {
      const item = items[0];
      console.log(`[Background] 查询 downloadId=${message.downloadId} 结果:`, item ? { state: item.state, error: item.error } : "不存在");
      sendResponse(item ? { state: item.state, error: item.error } : { error: "下载记录不存在" });
    }).catch(err => {
      console.error(`[Background] 查询 downloadId=${message.downloadId} 失败:`, err);
      sendResponse({ error: err.message });
    });
    return true;
  }

  if (message.action === "getStorage") {
    if (!Array.isArray(message.keys) || message.keys.length > 100 ||
        message.keys.some(key => !isPageStorageKey(key))) {
      sendResponse({ error: '存储键无效' }); return;
    }
    chrome.storage.local.get(message.keys, (result) => {
      sendResponse(result);
    });
    return true;
  }

  if (message.action === "setStorage") {
    if (!message.data || typeof message.data !== 'object' || Array.isArray(message.data) ||
        Object.keys(message.data).length > 100 || Object.keys(message.data).some(key => !isPageStorageKey(key))) {
      sendResponse({ error: '存储数据无效' }); return;
    }
    chrome.storage.local.set(message.data, () => {
      sendResponse({ success: true });
    });
    return true;
  }

  // 本地图片原生拖放上传：通过 Chrome DevTools 协议把「本地绝对路径」作为真实文件拖进 Flow 页面
  if (message.action === "nativeFileDrag") {
    const tabId = sender.tab?.id;
    if (tabId == null) { sendResponse({ ok: false, error: "无法识别当前标签页" }); return; }
    dispatchNativeFileDrag(tabId, message.paths, message.x, message.y)
      .then(r => sendResponse(r))
      .catch(err => sendResponse({ ok: false, error: String(err?.message || err) }));
    return true;
  }

  // 桌面软件「账号积分管理」：关闭本浏览器（关闭该浏览器配置下的所有窗口）
  if (message.action === "closeBrowser") {
    sendResponse({ success: true });
    setTimeout(() => {
      // 优先尝试关闭整个窗口
      chrome.windows.getAll({}, (wins) => {
        if (wins && wins.length > 0) {
            for (const w of wins) {
                chrome.windows.remove(w.id, () => {
                    // 如果关闭窗口失败（某些指纹浏览器可能拦截），则降级为关闭当前所有标签页
                    if (chrome.runtime.lastError) {
                        chrome.tabs.query({windowId: w.id}, (tabs) => {
                            for (const t of tabs) {
                                chrome.tabs.remove(t.id, () => void chrome.runtime.lastError);
                            }
                        });
                    }
                });
            }
        } else {
            // 保底关闭
            chrome.tabs.query({}, (tabs) => {
                for (const t of tabs) {
                    chrome.tabs.remove(t.id, () => void chrome.runtime.lastError);
                }
            });
        }
      });
    }, 200);
    return;
  }
});

function isPageStorageKey(key) {
  return typeof key === 'string' && key.length <= 1024 &&
    (['settings', 'presets'].includes(key) ||
     /^(tasks|taskRecord|downloadedUrls|isRunning|currentIndex|currentLineIndex|retryCount)_.+/.test(key));
}

// 2.0 原生文件拖放（移植自 FlowStudio 插件的已验证方案）
// 原理：普通网页脚本 new File()/DataTransfer 伪造的拖放事件 isTrusted=false，Flow 会忽略；
// 而 Chrome DevTools 协议 Input.dispatchDragEvent 由浏览器内核发出「真实」拖放，
// 并且 data.files 直接接收本地绝对路径，浏览器自己读取文件，效果等同于用户从资源管理器拖入。
const dragLanes = new Map();
function serialByTab(tabId, fn) {
  const prev = dragLanes.get(tabId) || Promise.resolve();
  const p = prev.catch(() => {}).then(fn);
  dragLanes.set(tabId, p.catch(() => {}));
  return p;
}

async function dispatchNativeFileDrag(tabId, paths, x, y) {
  if (!Array.isArray(paths) || paths.length > 100 || paths.some(p => typeof p !== 'string')) {
    throw new Error('本地图片路径列表无效');
  }
  const clean = [...new Set((paths || []).map(String).map(s => s.trim()).filter(Boolean))];
  if (!clean.length) throw new Error("没有可上传的本地文件路径");

  const ALLOWED_IMAGE_EXTS = new Set([".jpg", ".jpeg", ".png", ".webp", ".bmp"]);
  const validFiles = clean.filter(p => {
    const dot = p.lastIndexOf(".");
    // Reject network shares, device paths and NTFS alternate data streams.
    const absolute = /^[A-Za-z]:[\\/]/.test(p) || (p.startsWith('/') && !p.startsWith('//'));
    const rest = /^[A-Za-z]:/.test(p) ? p.slice(2) : p;
    return absolute && !rest.includes(':') && !/[\x00-\x1f]/.test(p) &&
      !p.startsWith('\\\\') && !rest.split(/[\\/]/).includes('..') &&
      dot !== -1 && ALLOWED_IMAGE_EXTS.has(p.substring(dot).toLowerCase());
  });
  if (!validFiles.length || validFiles.length !== clean.length) {
    throw new Error("安全拦截：原生拖放仅允许上传本地图片文件 (.jpg, .jpeg, .png, .webp, .bmp)");
  }

  return serialByTab(tabId, async () => {
    const target = { tabId };
    let attachedHere = false;
    try {
      try {
        await chrome.debugger.attach(target, "1.3");
        attachedHere = true;
      } catch (e) {
        // 已被本扩展附加时继续使用；被其他调试器（如 DevTools 之外的工具）占用时报错
        if (!/already attached/i.test(String(e?.message || e))) throw e;
      }
      // 后台标签页也能正常处理拖放
      try { await chrome.debugger.sendCommand(target, "Emulation.setFocusEmulationEnabled", { enabled: true }); } catch (_) {}
      const dragData = {
        items: [{ mimeType: "application/octet-stream", data: "", title: "", baseURL: "" }],
        files: validFiles,
        dragOperationsMask: 1
      };
      const px = Number.isFinite(Number(x)) ? Number(x) : 640;
      const py = Number.isFinite(Number(y)) ? Number(y) : 420;
      for (const type of ["dragEnter", "dragOver", "drop"]) {
        await chrome.debugger.sendCommand(target, "Input.dispatchDragEvent", { type, x: px, y: py, data: dragData });
        if (type !== "drop") await new Promise(r => setTimeout(r, 120));
      }
      console.log(`[Background] ✅ 原生拖放已发送 ${clean.length} 个文件 @(${px},${py})`);
      return { ok: true, count: clean.length, method: "chrome_debugger_native_drag" };
    } finally {
      if (attachedHere) {
        try { await chrome.debugger.sendCommand(target, "Emulation.setFocusEmulationEnabled", { enabled: false }); } catch (_) {}
        try { await chrome.debugger.detach(target); } catch (_) {}
      }
    }
  });
}

// 2. 处理直接下载逻辑
async function handleDownload(url, filename, task) {
  try {
    console.log('[Background] 开始校验视频下载任务');
    // 规范化文件名中的斜杠，防止创建非法的多层级路径
    if (!task?.mediaId || !task.submissionId || !task.taskId || !filename || filename !== task.download_path) {
      console.error("[Background] 拒绝下载: 缺少媒体 ID 或任务文件名绑定");
      throw new Error("缺少媒体 ID 或任务文件名绑定，拒绝下载");
    }
    const parsed = new URL(url);
    if (parsed.protocol !== 'https:' || parsed.username || parsed.password ||
        (parsed.port && parsed.port !== '443')) throw new Error('仅允许 HTTPS 媒体下载');
    const isVidsHost = (
      parsed.hostname.endsWith(".usercontent.google.com") ||
      parsed.hostname.endsWith(".googleusercontent.com") ||
      parsed.hostname === "docs.google.com"
    );
    const isGoogleFlowHost = (
      parsed.hostname === "flow-content.google" ||
      parsed.hostname === "labs.google" ||
      parsed.hostname.endsWith(".labs.google")
    );
    if (!isVidsHost && !isGoogleFlowHost) {
      console.error(`[Background] ❌ 拒绝下载: 域名不在受信任的 Google CDN 白名单中: ${parsed.hostname}`);
      throw new Error("下载域名不受信任，已安全拦截");
    }

    const mediaId = parsed.hostname === "flow-content.google" ? parsed.pathname.match(/^\/video\/([a-zA-Z0-9_-]+)$/)?.[1] :
      parsed.hostname === "labs.google" && parsed.pathname === "/fx/api/trpc/media.getMediaUrlRedirect" ?
        ((parsed.searchParams.get("name") || "").split("/media/").pop().replace(/^media\//, "")) :
      isVidsHost ? task.mediaId : null;
    console.log(`[Background] URL 解析出的 mediaId: ${mediaId}, task.mediaId: ${task.mediaId}, isVidsHost: ${isVidsHost}`);
    if (mediaId !== task.mediaId) {
      console.error(`[Background] ❌ 拒绝下载: 下载地址的媒体 ID (${mediaId}) 与任务 (${task.mediaId}) 不一致`);
      throw new Error("下载地址的媒体 ID 与任务不一致");
    }
    const sanitizedFilename = filename.replace(/\\/g, "/").replace(/^\/+/, "");
    if (sanitizedFilename.split("/").some(part => !part || part === "." || part === ".." || /[<>:"|?*\x00-\x1f]/.test(part))) {
      console.error(`[Background] ❌ 拒绝下载: 文件名包含非法字符: ${sanitizedFilename}`);
      throw new Error("下载文件名无效");
    }
    if (!sanitizedFilename.toLowerCase().endsWith(".mp4")) {
      console.error(`[Background] ❌ 拒绝下载: 仅允许下载 .mp4 视频文件: ${sanitizedFilename}`);
      throw new Error("文件类型不安全，仅允许 .mp4 视频");
    }
    // 在 Chrome 触发文件命名事件之前保存这个 URL 的独立文件名。
    await chrome.storage.session.set({ [`filename_${url}`]: sanitizedFilename });
    console.log('[Background] 开始调用 Chrome API 下载视频');
    
    return new Promise((resolve) => {
      chrome.downloads.download({
        url: url,
        filename: sanitizedFilename,
        conflictAction: 'uniquify',
        saveAs: false
      }, async (downloadId) => {
        try {
        if (chrome.runtime.lastError) {
          console.error(`[Background] ❌ chrome.downloads.download 失败:`, chrome.runtime.lastError.message);
          resolve({ error: chrome.runtime.lastError.message });
        } else {
          console.log(`[Background] ✅ chrome.downloads.download 已启动，分配 ID=${downloadId}`);
          await chrome.storage.session.set({ [`download_${downloadId}`]: { ...task, filename: sanitizedFilename, url } });
          resolve({ success: true, downloadId: downloadId });
          // 下载可能在关联信息落盘之前就完成。
          const items = await chrome.downloads.search({ id: downloadId });
          if (items[0]?.state === "complete" || items[0]?.state === "interrupted") {
            await notifyDownload(downloadId, items[0].state, items[0].error);
          }
        }
        } catch (err) {
          console.error("[Background] 下载跟踪失败", err);
          resolve({ error: err.message });
        }
      });
    });
  } catch (e) {
    console.error(`[Background] 下载函数捕获到异常:`, e);
    return { error: e.message };
  }
}

// 只处理本扩展发起、精确 URL/下载 ID 已登记的下载。
chrome.downloads.onDeterminingFilename.addListener((item, suggest) => {
  if (item.byExtensionId !== chrome.runtime.id) { suggest(); return; }
  const keys = [`download_${item.id}`, `filename_${item.url}`];
  if (item.finalUrl) keys.push(`filename_${item.finalUrl}`);
  chrome.storage.session.get(keys).then(saved => {
    const filename = saved[`download_${item.id}`]?.filename || saved[`filename_${item.url}`] || (item.finalUrl ? saved[`filename_${item.finalUrl}`] : null);
    console.log(`[Background] onDeterminingFilename: ID=${item.id}`);
    if (filename) suggest({ filename, conflictAction: "uniquify" });
    else suggest();
  }).catch(() => suggest());
  return true;
});

// 按下载 ID 保存归属，标签页切换或 Service Worker 重启不会串任务。
async function notifyDownload(id, state, error) {
  const key = `download_${id}`;
  const saved = await chrome.storage.session.get(key);
  const task = saved[key];
  if (!task || task.tabId == null) return;
  try {
    console.log(`[Background] 📢 notifyDownload: 通知标签页 tabId=${task.tabId}, downloadId=${id}, state=${state}, error=${error}`);
    await chrome.tabs.sendMessage(task.tabId, {
      action: state === "complete" ? "downloadCompleted" : "downloadFailed",
      downloadId: id, task, error: error || "下载中断"
    }, { frameId: task.frameId ?? 0 });
    await chrome.storage.session.remove(key);
  } catch (err) { console.warn("[Background] 下载通知未送达", err); }
}
chrome.downloads.onChanged.addListener(delta => {
  if (["complete", "interrupted"].includes(delta.state?.current)) {
    console.log(`[Background] 🔄 downloads.onChanged: ID=${delta.id}, state=${delta.state?.current}, error=${delta.error?.current || '无'}`);
    notifyDownload(delta.id, delta.state.current, delta.error?.current);
  }
});
