// injects/ui.js - 核心 UI 渲染及批量生成自动化控制脚本 (支持手动 JSON 导出对接与断点重载刷新)

(function() {
  "use strict";
  if (window.top !== window) return;

  console.log("[FlowUI] 界面控制器正在初始化...");

  // ----------------------------------------------------
  // 0. Trusted Types 兼容与安全 DOM 操作封装 (针对 flow.google.com CSP 限制)
  // ----------------------------------------------------
  let flowTrustedPolicy = null;
  if (typeof window !== "undefined" && window.trustedTypes && window.trustedTypes.createPolicy) {
    try {
      flowTrustedPolicy = window.trustedTypes.createPolicy("flow-ui-policy", {
        createHTML: (s) => s,
        createScript: (s) => s,
        createScriptURL: (s) => s,
      });
    } catch (e) {
      try {
        flowTrustedPolicy = window.trustedTypes.createPolicy("default", {
          createHTML: (s) => s,
          createScript: (s) => s,
          createScriptURL: (s) => s,
        });
      } catch (err) {
        flowTrustedPolicy = window.trustedTypes.defaultPolicy || null;
      }
    }
  }

  function setSafeHTML(element, htmlContent) {
    if (!element) return;
    try {
      if (flowTrustedPolicy) {
        element.innerHTML = flowTrustedPolicy.createHTML(htmlContent);
      } else if (window.trustedTypes && window.trustedTypes.defaultPolicy) {
        element.innerHTML = window.trustedTypes.defaultPolicy.createHTML(htmlContent);
      } else {
        element.innerHTML = htmlContent;
      }
    } catch (err) {
      console.warn("[FlowUI] innerHTML 受 Trusted Types 拦截，使用 DOMParser 安全降级注入:", err);
      try {
        const doc = new DOMParser().parseFromString(htmlContent, "text/html");
        element.replaceChildren(...doc.body.childNodes);
      } catch (domErr) {
        console.warn("[FlowUI] DOMParser 降级失败，尝试 ContextualFragment:", domErr);
        try {
          const range = document.createRange();
          range.selectNodeContents(document.documentElement || document.body);
          const fragment = range.createContextualFragment(htmlContent);
          element.replaceChildren(fragment);
        } catch (rangeErr) {
          console.error("[FlowUI] 无法注入 HTML 内容:", rangeErr);
        }
      }
    }
  }

  // ----------------------------------------------------
  // 1. 消息中间件（使用 window.postMessage 桥接后台）
  // ----------------------------------------------------
  const extensionCallbacks = new Map();

  function sendToExtension(action, data) {
    return new Promise((resolve) => {
      const callbackId = Math.random().toString(36).substring(2, 9);
      extensionCallbacks.set(callbackId, resolve);
      
      // 15秒超时保底，防止扩展桥接未就绪导致初始化永久阻塞
      setTimeout(() => {
        if (extensionCallbacks.has(callbackId)) {
          extensionCallbacks.delete(callbackId);
          console.warn(`[FlowUI] sendToExtension(${action}) 15秒无响应，自动跳过`);
          resolve({ error: "timeout" });
        }
      }, 15000);

      window.postMessage({
        sender: "flow-main",
        callbackId: callbackId,
        payload: { action, ...data }
      }, "*");
    });
  }

  // 监听来自 content-isolated.js 的响应与广播事件
  window.addEventListener("message", (event) => {
    if (event.source !== window || !event.data) return;
    
    if (event.data.sender === "flow-isolated-open-panel") {
      openPanel();
      return;
    }

    if (event.data.sender === "flow-isolated-event") {
      if (["downloadCompleted", "downloadFailed"].includes(event.data.event)) {
        const taskInfo = event.data.data?.task;
        console.log("[FlowUI] 收到后台下载完成广播通知:", taskInfo);
        if (taskInfo && taskInfo.projectId === getStorageKey()) {
          const r = taskInfo.rowIndex;
          const l = taskInfo.lineIndex;
          if (state.tasks[r]?.taskId === taskInfo.taskId && state.tasks[r]?.mediaBindings?.[l]?.submissionId === taskInfo.submissionId) {
            if (event.data.event === "downloadFailed") {
              updateLineStatus(r, l, "failed", `下载失败: ${event.data.data.error}`);
              return;
            }
            updateLineStatus(r, l, "success", `自动下载成功: ${taskInfo.download_path}`);
            if (Array.isArray(state.tasks[r].downloaded)) {
              state.tasks[r].downloaded[l] = true;
            }
            saveState();
          }
        }
      }
      return;
    }

    if (event.data.sender !== "flow-isolated") {
      return;
    }
    const { callbackId, response } = event.data;
    if (extensionCallbacks.has(callbackId)) {
      extensionCallbacks.get(callbackId)(response);
      extensionCallbacks.delete(callbackId);
    }
  });

  const downloadedUrlsSet = new Set();

  // ----------------------------------------------------
  // 2. 状态管理与配置项
  // ----------------------------------------------------
  let state = {
    tasks: [],             // 批量生成任务列表 (含 prompt, mode, image_name, local_image_path, duration, download_path, status, message, downloaded)
    taskRecord: {},        // mediaName -> 任务进度关联信息映射表
    activeTasksQueue: [],  // FIFO 活跃任务排队队列，用于与完成的视频松散匹配
    downloadedUrls: [],    // 已下载视频 URL 记录，防止重复下载
    settings: {
      interval: 5,         // 每次生成的间隔基数(秒，默认 5 秒，遵循软件规则设置)
      intervalRandom: 0,   // 随机抖动上限(秒，默认 0 秒，严格按设定间隔执行)
      maxLetterFor4s: 40,  // 4s视频最大字数
      maxLetterFor6s: 60,  // 6s视频最大字数
      defaultCount: 1,     // 默认生成数量
      footageType: "VIDEO_FRAMES", // 默认素材类型 (VIDEO_FRAMES 帧模式)
      resolution: "VIDEO_RESOLUTION_720P", // 默认分辨率 (720p)
      aspectRatio: "ASPECT_RATIO_9_16",    // 尺寸比例 (默认 9:16 竖屏)
      videoModel: "omni_1_1_flash"       // 生成模型 (默认 Omni 1.1 Flash)
    },
    presets: [             // 提示词模板预设 (首尾拼接)
      { name: "无模版(直接填入)", content: "\n\n" },
      { name: "写实风格电影感", content: "A cinematic film of\n\n4k resolution, highly detailed, photorealistic." },
      { name: "3D卡通动画", content: "A 3D animated scene of\n\npixar style, vibrant colors, clay model." },
      { name: "极简插画", content: "A minimalist vector illustration of\n\nflat color, clean lines, modern design." }
    ],
    isRunning: false,
    isSuspended: false,
    activeProjectId: "",
    currentIndex: 0,       // 当前正在跑的任务索引
    currentLineIndex: 0,   // 当前正在跑的提示词分行索引
    retryCount: 0          // 单个任务失败刷新重试计数
  };

  // 检测当前是否为 Google Vids 页面
  function isVidsPage() {
    return location.hostname === "docs.google.com" && location.pathname.includes("/videos/");
  }

  // 生成缓存 KEY 规则：工程ID + 合集ID (或 Vids 文档 ID)
  function getStorageKey() {
    const url = location.href;
    if (isVidsPage()) {
      const vidsMatch = url.match(/\/videos\/d\/([^/]+)/);
      return vidsMatch ? `vids_${vidsMatch[1]}` : "default-vids-project";
    }
    const projectMatch = url.match(/\/project\/([^/]+)/);
    const collectionMatch = url.match(/\/collection\/([^/]+)/);
    const pId = projectMatch ? projectMatch[1] : "";
    const cId = collectionMatch ? collectionMatch[1] : "";
    return [pId, cId].filter(Boolean).join("-") || "default-flow-project";
  }

  // 写入配置和状态到 Storage (通过插件 Background 存储)
  async function saveState() {
    const key = getStorageKey();
    state.activeProjectId = key;
    
    const dataToSave = {
      [`tasks_${key}`]: state.tasks,
      settings: state.settings,
      presets: state.presets,
      [`taskRecord_${key}`]: state.taskRecord,
      [`downloadedUrls_${key}`]: Array.from(downloadedUrlsSet),
      [`isRunning_${key}`]: state.isRunning,
      [`currentIndex_${key}`]: state.currentIndex,
      [`currentLineIndex_${key}`]: state.currentLineIndex,
      [`retryCount_${key}`]: state.retryCount
    };
    
    const res = await sendToExtension("setStorage", { data: dataToSave });
    if (res && res.error) {
      console.error("[FlowUI] 保存状态失败:", res.error);
      if (res.error.includes("失效") || res.error.includes("invalidated")) {
        showToast("检测到插件连接失效，请刷新网页以重新连接！", 8000);
      }
    }
  }

  // 从 Storage 读取配置和状态
  async function loadState() {
    const key = getStorageKey();
    state.activeProjectId = key;
    
    const saved = await sendToExtension("getStorage", {
      keys: [
        `tasks_${key}`, "settings", "presets", `taskRecord_${key}`, `downloadedUrls_${key}`,
        `isRunning_${key}`, `currentIndex_${key}`, `currentLineIndex_${key}`, `retryCount_${key}`
      ]
    });
    
    if (saved) {
      if (saved.error) {
        console.error("[FlowUI] 加载状态失败:", saved.error);
        if (saved.error.includes("失效") || saved.error.includes("invalidated")) {
          showToast("检测到插件连接失效或重启，请刷新网页以重新连接！", 8000);
        }
        return;
      }
      if (saved[`tasks_${key}`]) state.tasks = saved[`tasks_${key}`];
      if (saved.settings) state.settings = { ...state.settings, ...saved.settings };
      // 迁移: 旧默认值 VIDEO_REFERENCES / veo_fast 自动升级为标准模型 ID
      if (state.settings.videoModel === "VIDEO_REFERENCES" || !state.settings.videoModel) {
        state.settings.videoModel = "omni_1_1_flash";
      } else if (state.settings.videoModel === "veo_fast") {
        state.settings.videoModel = "veo_3_1_fast";
      }
      if (saved.presets) state.presets = saved.presets;
      if (saved[`taskRecord_${key}`]) state.taskRecord = saved[`taskRecord_${key}`];
      if (saved[`downloadedUrls_${key}`] && Array.isArray(saved[`downloadedUrls_${key}`])) {
        state.downloadedUrls = saved[`downloadedUrls_${key}`];
        saved[`downloadedUrls_${key}`].forEach(u => downloadedUrlsSet.add(u));
      }
      if (saved[`isRunning_${key}`] !== undefined) state.isRunning = saved[`isRunning_${key}`];
      if (saved[`currentIndex_${key}`] !== undefined) state.currentIndex = saved[`currentIndex_${key}`];
      if (saved[`currentLineIndex_${key}`] !== undefined) state.currentLineIndex = saved[`currentLineIndex_${key}`];
      if (saved[`retryCount_${key}`] !== undefined) state.retryCount = saved[`retryCount_${key}`];
    }
  }

  // ----------------------------------------------------
  // 3. UI 界面构建
  // ----------------------------------------------------
  let fabEl = null;
  let overlayEl = null;
  let importDialogEl = null;
  let alarmDialogEl = null;

  function createUI() {
    const targetParent = document.body || document.documentElement;
    let existingFab = document.getElementById("flow-batch-fab");
    if (existingFab && (!existingFab.querySelector("#flow-batch-fab-quick") || !existingFab.querySelector("#flow-batch-fab-vids"))) {
      // 旧版单/双按钮（或独立世界兜底按钮）→ 替换为三按钮胶囊框 (⚡ + 🎬 Vids + ➕)
      existingFab.remove();
      existingFab = null;
    }
    const existingOverlay = document.getElementById("flow-batch-overlay");
    if (existingFab && existingOverlay && targetParent && targetParent.contains(existingFab)) {
      return;
    }

    console.log("[FlowUI] 正在创建控制台 UI 界面...", location.href);

    if (!existingFab) {
      // 三按钮悬浮胶囊框：上 ⚡ 一键导入剪贴板并开始；中 🎬 Google Vids 逐个生成模式；下 + 打开控制面板
      // 在 Vids 页面上，右侧是 AI 视频片段侧边栏，因此自动将悬浮胶囊框置于页面左侧，绝不遮挡右侧生成栏！
      const horizontalPos = isVidsPage() ? "left: 24px !important;" : "right: 24px !important;";
      fabEl = document.createElement("div");
      fabEl.id = "flow-batch-fab";
      fabEl.style.cssText = `position: fixed !important; bottom: 120px !important; ${horizontalPos} width: 56px !important; height: 168px !important; border-radius: 28px !important; background: linear-gradient(180deg, #8b5cf6, #3b82f6) !important; box-shadow: 0 8px 32px rgba(139, 92, 246, 0.6), inset 0 2px 4px rgba(255, 255, 255, 0.3) !important; display: flex !important; flex-direction: column !important; align-items: stretch !important; justify-content: stretch !important; cursor: default !important; z-index: 2147483647 !important; border: 2px solid rgba(255, 255, 255, 0.2) !important; box-sizing: border-box !important; overflow: hidden !important; padding: 0 !important; transform: none !important;`;

      const makeFabBtn = (title, pathD, color, viewBox) => {
        const btn = document.createElement("div");
        btn.title = title;
        btn.style.cssText = "flex: 1 1 33.33% !important; display: flex !important; align-items: center !important; justify-content: center !important; cursor: pointer !important; transition: background 0.15s ease !important; background: transparent !important;";
        btn.addEventListener("mouseenter", () => btn.style.setProperty("background", "rgba(255,255,255,0.18)", "important"));
        btn.addEventListener("mouseleave", () => btn.style.setProperty("background", "transparent", "important"));
        const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        svg.setAttribute("viewBox", viewBox || "0 0 24 24");
        svg.setAttribute("width", "24");
        svg.setAttribute("height", "24");
        svg.style.cssText = `width: 24px !important; height: 24px !important; fill: ${color} !important; pointer-events: none !important; transform: none !important;`;
        const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
        path.setAttribute("d", pathD);
        path.setAttribute("fill", color);
        svg.appendChild(path);
        btn.appendChild(svg);
        return btn;
      };

      const makeDivider = () => {
        const div = document.createElement("div");
        div.style.cssText = "height: 1px !important; margin: 0 10px !important; background: rgba(255,255,255,0.35) !important; flex: 0 0 1px !important;";
        return div;
      };

      const quickBtn = makeFabBtn("⚡ 一键执行：读取剪贴板 JSON → 导入 → 开始批量生成",
        "M13 2L4.5 13.5H11L10 22L19.5 10.5H13L13 2Z", "#FDE047");
      quickBtn.id = "flow-batch-fab-quick";
      quickBtn.addEventListener("click", (e) => { e.stopPropagation(); quickRunFromClipboard(); });

      const vidsBtn = makeFabBtn("🎬 Vids 专属一键生成：自动打开 AI 视频侧边栏 → 切换「添加动画」→ 逐个任务上传图片、生成并下载视频 (无 50 积分限制)",
        "M18 4l2 4h-3l-2-4h-2l2 4h-3l-2-4H8l2 4H7L5 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V4h-4zm-6.75 11.25L10 18l-1.25-2.75L6 14l2.75-1.25L10 10l1.25 2.75L14 14l-2.75 1.25zm5.69-3.31L16 14l-.94-2.06L13 11l2.06-.94L16 8l.94 2.06L19 11l-2.06.94z", "#67E8F9");
      vidsBtn.id = "flow-batch-fab-vids";
      vidsBtn.addEventListener("click", (e) => { e.stopPropagation(); vidsQuickRunFromClipboard(); });

      const openBtn = makeFabBtn("打开批量生成助手控制面板", "M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z", "#ffffff");
      openBtn.id = "flow-batch-fab-open";
      openBtn.addEventListener("click", (e) => { e.stopPropagation(); openPanel(); });

      fabEl.appendChild(quickBtn);
      fabEl.appendChild(makeDivider());
      fabEl.appendChild(vidsBtn);
      fabEl.appendChild(makeDivider());
      fabEl.appendChild(openBtn);

      if (targetParent) {
        targetParent.appendChild(fabEl);
        console.log("[FlowUI] FAB 三按钮已挂载至:", targetParent.tagName);
      }
    } else {
      fabEl = existingFab;
      if (targetParent && !targetParent.contains(fabEl)) {
        targetParent.appendChild(fabEl);
      }
    }

    if (document.getElementById("flow-batch-overlay")) return;

    // 创建控制面板遮罩层 (使用 setSafeHTML 安全注入)
    overlayEl = document.createElement("div");
    overlayEl.id = "flow-batch-overlay";
    const panelTitleText = isVidsPage()
      ? "FlowCue · Google Vids 逐个生成与自动下载助手 (无 50 积分限制)"
      : "Flow 批量生成与自动下载助手";
    setSafeHTML(overlayEl, `
      <div id="flow-batch-panel">
        <div id="flow-batch-panel-header">
          <h2>
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="color: #a78bfa;"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"></path><polyline points="3.27 6.96 12 12.01 20.73 6.96"></polyline><line x1="12" y1="22.08" x2="12" y2="12"></line></svg>
            ${panelTitleText}
          </h2>
          <div class="flow-close-btn" id="flow-panel-close">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
          </div>
        </div>
        
        <div id="flow-batch-panel-content">
          <!-- 左侧：任务表格 -->
          <div id="flow-table-container">
            <table class="flow-table" id="flow-tasks-table">
              <thead>
                <tr>
                  <th style="width: 115px; text-align: center;">图片</th>
                  <th>提示词文本 (分行分割)</th>
                  <th style="width: 145px;">提示词模板</th>
                  <th style="width: 135px;">素材类型</th>
                  <th style="width: 85px;">时长（秒）</th>
                  <th style="width: 70px;">生成数</th>
                  <th style="width: 220px;">状态与日志</th>
                  <th style="width: 80px; text-align: center;">操作</th>
                </tr>
              </thead>
              <tbody>
                <!-- 动态渲染 -->
              </tbody>
            </table>
          </div>

          <!-- 右侧：设置面板 -->
          <div id="flow-settings-drawer">
            <h3 style="margin-top: 0; font-family: var(--flow-font-heading); font-size: 16px; border-bottom: 1px solid var(--flow-border-glass); padding-bottom: 10px;">自动化参数配置</h3>
            
            <div class="settings-group">
              <label>生成间隔基数 (秒)</label>
              <input type="number" class="settings-input" id="cfg-interval" min="0" value="5">
            </div>
            
            <div class="settings-group">
              <label>随机抖动时间 (秒)</label>
              <input type="number" class="settings-input" id="cfg-random" min="0" value="0">
            </div>
            
            <div class="settings-group">
              <label>4秒视频最大字数限额</label>
              <input type="number" class="settings-input" id="cfg-max4s" min="1" value="40">
            </div>
            
            <div class="settings-group">
              <label>6秒视频最大字数限额</label>
              <input type="number" class="settings-input" id="cfg-max6s" min="1" value="60">
            </div>

            <div class="settings-group">
              <label>画面尺寸 / 比例</label>
              <select class="settings-input" id="cfg-aspect" style="background: rgba(255,255,255,0.05); color: var(--flow-text-primary);">
                <option value="ASPECT_RATIO_9_16" selected>9:16 (竖屏 / 手机短视频 默认)</option>
                <option value="ASPECT_RATIO_16_9">16:9 (横屏 / 宽屏)</option>
                <option value="ASPECT_RATIO_1_1">1:1 (正方形)</option>
              </select>
            </div>

            <div class="settings-group">
              <label>视频生成模型</label>
              <select class="settings-input" id="cfg-model" style="background: rgba(255,255,255,0.05); color: var(--flow-text-primary);">
                <option value="omni_1_1_flash" selected>Omni 1.1 Flash (默认)</option>
                <option value="veo_3_1_lite">Veo 3.1 - Lite</option>
                <option value="veo_3_1_fast">Veo 3.1 - Fast</option>
                <option value="veo_3_1_quality">Veo 3.1 - Quality</option>
                <option value="veo_3_1_lite_low_priority">Veo 3.1 - Lite [Lower Priority]</option>
                <option value="veo_2">Veo 2</option>
              </select>
            </div>

            <div class="settings-group">
              <label>清晰度 / 分辨率</label>
              <select class="settings-input" id="cfg-resolution" style="background: rgba(255,255,255,0.05); color: var(--flow-text-primary);">
                <option value="VIDEO_RESOLUTION_720P" selected>720p (高清 默认)</option>
                <option value="VIDEO_RESOLUTION_360P">360p (低分辨率 / 省流量)</option>
                <option value="VIDEO_RESOLUTION_1080P">1080p (全高清)</option>
              </select>
            </div>

            <div class="settings-group">
              <label>默认素材模式</label>
              <select class="settings-input" id="cfg-footagetype" style="background: rgba(255,255,255,0.05); color: var(--flow-text-primary);">
                <option value="VIDEO_FRAMES" selected>帧模式 (首帧作为起始视频帧 默认)</option>
                <option value="VIDEO_REFERENCES">素材模式 (图片作为参考物)</option>
              </select>
            </div>

            <div class="settings-group" style="margin-top: 20px; border-top: 1px solid var(--flow-border-glass); padding-top: 15px;">
              <label style="font-weight: 600;">模版自定义预设</label>
              <button class="flow-btn secondary" id="btn-add-preset" style="font-size: 12px; padding: 6px 12px;">新建模板</button>
              <div id="presets-list-container" style="display:flex; flex-direction:column; gap:8px; margin-top:8px; max-height: 180px; overflow-y:auto;">
                <!-- 预设列表 -->
              </div>
            </div>
          </div>
        </div>

        <div id="flow-batch-panel-footer">
          <div class="footer-actions-left">
            <button class="flow-btn secondary" id="btn-load-images">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><circle cx="8.5" cy="8.5" r="1.5"></circle><polyline points="21 15 16 10 5 21"></polyline></svg>
              加载页面图片
            </button>
            <button class="flow-btn secondary" id="btn-open-import" style="border-color: #8b5cf6; color: #a78bfa;">
              导入外部 JSON
            </button>
            <button class="flow-btn secondary" id="btn-upload-local" style="border-color: #10b981; color: #34d399;" title="把任务中的本地图片（local_image_path）真实上传到当前 Flow 项目">
              上传本地图片到 Flow
            </button>
            <button class="flow-btn secondary" id="btn-copy-report">
              导出结果报告
            </button>
            <button class="flow-btn secondary" id="btn-clear-tasks" style="color: #ef4444; border-color: rgba(239,68,68,0.2);" title="清空表格中的全部任务">
              清空全部任务列表
            </button>
          </div>
          <div class="footer-actions-right">
            <button class="flow-btn danger" id="btn-stop-batch" style="display: none !important;">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="4" y="4" width="16" height="16" rx="2"></rect></svg>
              停止生成
            </button>
            <button class="flow-btn primary" id="btn-start-batch">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
              开始批量生成
            </button>
          </div>
        </div>
      </div>
    `);
    targetParent.appendChild(overlayEl);

    // 创建粘贴导入弹窗
    importDialogEl = document.createElement("div");
    importDialogEl.id = "flow-import-dialog";
    setSafeHTML(importDialogEl, `
      <div class="import-box">
        <h3 class="import-title">
          导入外部数据配置 (多套 JSON)
          <span style="font-size:11px; font-weight:normal; color:var(--flow-text-secondary);">支持多任务数组一键导入</span>
        </h3>
        <textarea class="import-textarea" id="flow-import-textarea" placeholder='请在此处粘贴 Python 导出的 JSON 数组配置...\n例如:\n[\n  {\n    "prompt": "Un perro corriendo",\n    "mode": "VIDEO_FRAMES",\n    "image_name": "dog.png",\n    "duration": 6,\n    "download_path": "D:\\\\videos\\\\project\\\\dog.mp4"\n  }\n]'></textarea>
        <div class="import-actions">
          <button class="flow-btn secondary" id="btn-import-cancel">取消</button>
          <button class="flow-btn primary" id="btn-import-confirm">确认导入</button>
        </div>
      </div>
    `);
    targetParent.appendChild(importDialogEl);

    // 创建异常活动报警弹窗
    alarmDialogEl = document.createElement("div");
    alarmDialogEl.id = "flow-alarm-dialog";
    alarmDialogEl.style.cssText = "display: none; position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; background: rgba(220, 38, 38, 0.15); backdrop-filter: blur(12px); z-index: 2147483646 !important; align-items: center; justify-content: center;";
    setSafeHTML(alarmDialogEl, `
      <div class="import-box" style="border-color: rgba(220, 38, 38, 0.4); box-shadow: 0 20px 48px rgba(220, 38, 38, 0.25);">
        <h3 class="import-title" style="color: #ef4444; display: flex; align-items: center; gap: 8px;">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>
          🚨 检测到安全限制（异常活动）
        </h3>
        <p style="font-size: 14px; line-height: 1.6; color: var(--flow-text-primary); margin: 8px 0;">
          Google Flow 网页提示“我们发现了一些异常活动”安全拦截。
        </p>
        <p id="flow-alarm-message" style="font-size: 13px; color: #f59e0b; font-weight: 500; margin: 4px 0;">
          系统将在 45 秒后自动刷新网页以尝试恢复，您也可以立即进行手动处理...
        </p>
        <div class="import-actions" style="margin-top: 16px;">
          <button class="flow-btn secondary" id="btn-alarm-manual" style="border-color: rgba(245, 158, 11, 0.3); color: #f59e0b;">我来手动处理 (暂停倒计时)</button>
          <button class="flow-btn danger" id="btn-alarm-reload">立即刷新网页</button>
          <button class="flow-btn primary" id="btn-alarm-resume">消除限制，继续生成</button>
        </div>
      </div>
    `);
    targetParent.appendChild(alarmDialogEl);

    // 创建 Toast 元素
    const toast = document.createElement("div");
    toast.id = "flow-batch-toast";
    toast.className = "flow-toast";
    targetParent.appendChild(toast);

    // 安全绑定基础 UI 事件
    const safeOn = (id, event, handler) => {
      const el = document.getElementById(id);
      if (el) el.addEventListener(event, handler);
      else console.warn(`[FlowUI] 挂载未找到元素 #${id}`);
    };

    safeOn("flow-panel-close", "click", () => closePanel());
    if (overlayEl) {
      overlayEl.addEventListener("click", (e) => {
        if (e.target === overlayEl) closePanel();
      });
    }

    // 绑定数据导入/导出/加载按钮
    safeOn("btn-load-images", "click", () => loadPageImages());
    safeOn("btn-open-import", "click", () => openImportDialog());
    safeOn("btn-import-cancel", "click", () => closeImportDialog());
    safeOn("btn-import-confirm", "click", () => handleJSONImport());
    safeOn("btn-copy-report", "click", () => copyExecutionReport());
    safeOn("btn-upload-local", "click", () => {
      if (batchPromise) { showToast("请先停止队列，再手动上传图片"); return; }
      uploadLocalImagesToFlow();
    });
    
    safeOn("btn-alarm-manual", "click", () => pauseAlarmCountdown());
    safeOn("btn-alarm-reload", "click", () => {
      if (alarmTimer) clearInterval(alarmTimer);
      saveState().then(() => location.reload());
    });
    safeOn("btn-alarm-resume", "click", () => resumeFromAlarm());
    
    safeOn("btn-clear-tasks", "click", () => {
      if (batchPromise) { showToast("请先停止队列，再清空任务列表"); return; }
      if (confirm("确定清空插件中的全部任务列表吗？Flow 云端项目和已下载文件不受影响。")) {
        state.tasks = [];
        state.taskRecord = {};
        state.activeTasksQueue = [];
        state.currentIndex = 0;
        state.currentLineIndex = 0;
        state.retryCount = 0;
        renderTable();
        saveState();
        showToast("已清空全部任务列表");
      }
    });

    overlayEl.addEventListener("click", event => {
      if (!batchPromise) return;
      const target = event.target.closest("button, input, select, textarea");
      if (!target) return;
      if (target.closest("#flow-tasks-table") || ["btn-open-import", "btn-load-images", "btn-clear-tasks"].includes(target.id)) {
        event.preventDefault();
        event.stopImmediatePropagation();
        showToast("请先停止队列，再修改任务");
      }
    }, true);
    safeOn("btn-start-batch", "click", () => startBatch());
    safeOn("btn-stop-batch", "click", () => stopBatch());

    bindSettingsEvents();
  }

  function showToast(message, duration = 3000) {
    let el = document.getElementById("flow-batch-toast");
    if (!el) {
      el = document.createElement("div");
      el.id = "flow-batch-toast";
      el.className = "flow-toast";
      (document.body || document.documentElement).appendChild(el);
    }
    el.innerText = message;
    el.style.cssText = "position: fixed !important; bottom: 24px !important; left: 24px !important; background: rgba(18, 18, 22, 0.95) !important; backdrop-filter: blur(8px) !important; border: 1px solid rgba(255, 255, 255, 0.15) !important; padding: 12px 24px !important; border-radius: 12px !important; color: #f3f4f6 !important; box-shadow: 0 8px 32px rgba(0,0,0,0.5) !important; font-size: 14px !important; z-index: 2147483647 !important; transform: translateY(0) !important; opacity: 1 !important; pointer-events: none !important; display: block !important;";
    el.classList.add("show");
    setTimeout(() => {
      el.classList.remove("show");
      el.style.setProperty("display", "none", "important");
    }, duration);
  }

  async function openPanel() {
    console.log("[FlowUI] 正在呼出主控制面板...");
    if (!overlayEl) overlayEl = document.getElementById("flow-batch-overlay");
    if (!overlayEl) {
      console.warn("[FlowUI] 遮罩层丢失，正在重新创建 UI...");
      createUI();
      overlayEl = document.getElementById("flow-batch-overlay");
    }

    if (overlayEl) {
      overlayEl.style.cssText = "position: fixed !important; top: 0 !important; left: 0 !important; width: 100vw !important; height: 100vh !important; background: rgba(0, 0, 0, 0.75) !important; backdrop-filter: blur(12px) !important; z-index: 2147483640 !important; display: flex !important; align-items: center !important; justify-content: center !important; opacity: 1 !important; pointer-events: auto !important;";
      overlayEl.classList.add("active");
    }

    const panel = document.getElementById("flow-batch-panel");
    if (panel) {
      panel.style.cssText = "width: 92vw !important; height: 88vh !important; max-width: 1400px !important; background: #121216 !important; border: 1px solid rgba(255, 255, 255, 0.15) !important; border-radius: 20px !important; box-shadow: 0 24px 64px rgba(0, 0, 0, 0.8) !important; display: flex !important; flex-direction: column !important; color: #f3f4f6 !important; overflow: hidden !important; z-index: 2147483641 !important; pointer-events: auto !important;";
    }

    try {
      await loadState();
    } catch (e) {
      console.warn("[FlowUI] 读取状态异常:", e);
    }
    
    // 安全同步设置项输入框
    const setVal = (id, val) => {
      const el = document.getElementById(id);
      if (el && val !== undefined) el.value = val;
    };
    setVal("cfg-interval", state.settings.interval);
    setVal("cfg-random", state.settings.intervalRandom);
    setVal("cfg-max4s", state.settings.maxLetterFor4s);
    setVal("cfg-max6s", state.settings.maxLetterFor6s);
    setVal("cfg-aspect", state.settings.aspectRatio || "ASPECT_RATIO_9_16");
    setVal("cfg-model", state.settings.videoModel || "omni_1_1_flash");
    setVal("cfg-resolution", state.settings.resolution || "VIDEO_RESOLUTION_720P");
    setVal("cfg-footagetype", state.settings.footageType || "VIDEO_FRAMES");
    
    try {
      renderTable();
    } catch (e) {
      console.warn("[FlowUI] 渲染任务表异常:", e);
    }
    try {
      renderPresetsList();
    } catch (e) {
      console.warn("[FlowUI] 渲染模板列表异常:", e);
    }
  }

  function closePanel() {
    if (!overlayEl) overlayEl = document.getElementById("flow-batch-overlay");
    if (overlayEl) {
      overlayEl.style.cssText = "display: none !important; opacity: 0 !important; pointer-events: none !important;";
      overlayEl.classList.remove("active");
    }
  }

  // ⚡ 一键执行：剪贴板 JSON → 打开面板 → 导入外部 JSON → 粘贴 → 确认导入 → 开始批量生成
  let quickRunBusy = false;
  async function quickRunFromClipboard() {
    if (quickRunBusy) return;
    if (batchPromise) { showToast("⚡ 批量生成正在运行中，请先停止后再使用一键执行", 4000); return; }
    quickRunBusy = true;
    try {
      // 3. 先读取剪贴板（必须在点击后立即读取，否则浏览器会拒绝）
      let text = "";
      try {
        text = ((await navigator.clipboard.readText()) || "").trim();
      } catch (e) {
        console.warn("[FlowUI] 读取剪贴板失败:", e);
        showToast("⚡ 无法读取剪贴板：请在地址栏左侧允许本网站「剪贴板」权限后重试", 6000);
        return;
      }
      if (!text) { showToast("⚡ 剪贴板为空，请先在软件中点击「复制任务 JSON」", 5000); return; }
      if (!text.startsWith("[")) { showToast("⚡ 剪贴板内容不是任务 JSON（应以 [ 开头），已取消", 5000); return; }

      // 1. 打开 UI 控制页面
      await openPanel();
      await delay(500);

      // 1.5. 在导入前先清空原本的任务列表
      state.tasks = [];
      state.taskRecord = {};
      state.globalProcessedTasks = 0;
      renderTable();
      saveState();
      await delay(100);

      // 2. 点击「导入外部 JSON」
      const btnOpenImport = document.getElementById("btn-open-import");
      if (!btnOpenImport) { showToast("⚡ 未找到「导入外部 JSON」按钮"); return; }
      btnOpenImport.click();
      await delay(500);

      // 4. 粘贴到「导入外部数据配置 (多套 JSON)」
      const ta = document.getElementById("flow-import-textarea");
      if (!ta) { showToast("⚡ 未找到导入输入框"); return; }
      ta.value = text;
      ta.dispatchEvent(new Event("input", { bubbles: true }));
      await delay(400);

      // 5. 点击「确认导入」
      const before = state.tasks.length;
      const btnConfirm = document.getElementById("btn-import-confirm");
      if (!btnConfirm) { showToast("⚡ 未找到「确认导入」按钮"); return; }
      btnConfirm.click();
      await delay(800);
      const added = state.tasks.length - before;
      if (added <= 0) { showToast("⚡ 导入未成功，已停止，未开始生成", 5000); return; }

      // 6. 点击「开始批量生成」
      await delay(500);
      const btnStart = document.getElementById("btn-start-batch");
      if (!btnStart) { showToast("⚡ 未找到「开始批量生成」按钮"); return; }
      btnStart.click();
      if (isVidsPage()) {
        await delay(400);
        closePanel();
        showToast(`🎬 [Vids 模式] 已导入 ${added} 个任务，开始逐个上传图片并生成视频！`, 5000);
      } else {
        showToast(`⚡ 已导入 ${added} 个任务并开始批量生成`, 4000);
      }
    } catch (e) {
      console.error("[FlowUI] 一键执行异常:", e);
      showToast(`⚡ 一键执行出错：${e.message}`, 6000);
    } finally {
      quickRunBusy = false;
    }
  }

  // 🎬 Google Vids 专属一键生成：自动打开右侧 AI 视频片段侧边栏 → 切换「添加动画」→ 读取剪贴板 JSON（或已有任务）逐个上传图片、生成并下载
  async function vidsQuickRunFromClipboard() {
    if (quickRunBusy) return;
    if (batchPromise) {
      await openPanel();
      showToast("🎬 Vids 队列正在运行中，您可在控制面板查看进度或点击「停止生成」", 4000);
      return;
    }
    if (!isVidsPage()) {
      showToast("🎬 正在为您打开 Google Vids 页面，进入视频项目后再次点击 🎬 按钮即可开始！", 6000);
      window.open("https://docs.google.com/videos/", "_blank");
      return;
    }
    quickRunBusy = true;
    try {
      let text = "";
      try {
        text = ((await navigator.clipboard.readText()) || "").trim();
      } catch (e) {
        console.warn("[FlowUI] [Vids] 读取剪贴板提示:", e);
      }

      if (text && text.startsWith("[")) {
        let parsedList = null;
        try {
          parsedList = JSON.parse(text);
        } catch (err) {
          showToast(`🎬 剪贴板 JSON 解析失败：${err.message}`, 5000);
          return;
        }
        if (Array.isArray(parsedList) && parsedList.length > 0) {
          state.tasks = [];
          state.taskRecord = {};
          state.activeTasksQueue = [];
          state.currentIndex = 0;
          state.currentLineIndex = 0;
          state.retryCount = 0;
          const added = importTaskList(parsedList);
          try { renderTable(); } catch (_) {}
          await saveState();
          closePanel();
          showToast(`🎬 [Vids 模式] 已导入 ${added} 个任务（无 50 积分限制），正在逐个上传图片并生成视频...`, 5000);
          startBatch();
          return;
        }
      }

      // 若剪贴板不是新 JSON，但当前列表已有待执行任务，则直接启动 Vids 逐个生成
      const hasPending = Array.isArray(state.tasks) && state.tasks.some(t =>
        splitTextToLines(t.text).length > 0 && (!Array.isArray(t.status) || t.status.some(s => s !== "success"))
      );
      if (hasPending) {
        closePanel();
        showToast(`🎬 [Vids 模式] 开始执行列表中的 ${state.tasks.length} 个任务...`, 4000);
        startBatch();
        return;
      }

      await openPanel();
      openImportDialog();
      showToast("🎬 请先在 FlowCue 软件中点击「复制任务 JSON」，然后粘贴导入或再次点击 🎬 按钮", 6000);
    } catch (e) {
      console.error("[FlowUI] [Vids] 一键执行异常:", e);
      showToast(`🎬 Vids 一键执行出错：${e.message}`, 6000);
    } finally {
      quickRunBusy = false;
    }
  }

  function openImportDialog() {
    if (!importDialogEl) importDialogEl = document.getElementById("flow-import-dialog");
    if (importDialogEl) {
      importDialogEl.style.cssText = "position: fixed !important; top: 0 !important; left: 0 !important; width: 100vw !important; height: 100vh !important; background: rgba(0, 0, 0, 0.75) !important; backdrop-filter: blur(12px) !important; z-index: 2147483647 !important; display: flex !important; align-items: center !important; justify-content: center !important; opacity: 1 !important; pointer-events: auto !important;";
      importDialogEl.classList.add("active");
    }
    const txt = document.getElementById("flow-import-textarea");
    if (txt) txt.value = "";
  }

  function closeImportDialog() {
    if (!importDialogEl) importDialogEl = document.getElementById("flow-import-dialog");
    if (importDialogEl) {
      importDialogEl.style.cssText = "display: none !important; opacity: 0 !important; pointer-events: none !important;";
      importDialogEl.classList.remove("active");
    }
  }

  function bindSettingsEvents() {
    const syncSetting = (elementId, settingKey) => {
      const el = document.getElementById(elementId);
      if (el) {
        el.addEventListener("change", (e) => {
          const val = parseInt(e.target.value, 10);
          if (!Number.isNaN(val) && val >= 0) {
            state.settings[settingKey] = val;
          }
          saveState();
        });
      }
    };

    syncSetting("cfg-interval", "interval");
    syncSetting("cfg-random", "intervalRandom");
    syncSetting("cfg-max4s", "maxLetterFor4s");
    syncSetting("cfg-max6s", "maxLetterFor6s");

    const syncSelect = (elementId, settingKey) => {
      const el = document.getElementById(elementId);
      if (el) {
        el.addEventListener("change", (e) => {
          state.settings[settingKey] = e.target.value;
          saveState();
        });
      }
    };

    syncSelect("cfg-aspect", "aspectRatio");
    syncSelect("cfg-model", "videoModel");
    syncSelect("cfg-resolution", "resolution");
    syncSelect("cfg-footagetype", "footageType");

    document.getElementById("btn-add-preset").addEventListener("click", () => {
      const name = prompt("请输入模板名称:");
      if (!name) return;
      const content = prompt("请输入模板内容（在要插入提示词的位置，用两个回车/换行符隔开）");
      if (content === null) return;
      state.presets.push({ name, content });
      saveState();
      renderPresetsList();
      renderTable();
    });
  }

  function renderPresetsList() {
    const container = document.getElementById("presets-list-container");
    if (!container) return;
    container.replaceChildren();
    state.presets.forEach((preset, index) => {
      const item = document.createElement("div");
      item.style.cssText = "display:flex; justify-content:space-between; align-items:center; background:rgba(255,255,255,0.03); padding:6px 12px; border-radius:6px; border:1px solid var(--flow-border-glass);";
      setSafeHTML(item, `
        <span style="font-size:12px; font-weight:500;">${preset.name}</span>
        <button class="flow-btn secondary" style="font-size:10px; padding:4px 8px; color:#ef4444; border-color:rgba(239,68,68,0.2);" data-idx="${index}">删除</button>
      `);
      item.querySelector("button").addEventListener("click", (e) => {
        const idx = parseInt(e.target.dataset.idx, 10);
        if (confirm(`确定删除模板 "${state.presets[idx].name}" 吗？`)) {
          state.presets.splice(idx, 1);
          saveState();
          renderPresetsList();
          renderTable();
        }
      });
      container.appendChild(item);
    });
  }

  // ----------------------------------------------------
  // 4. 加载页面图片
  // ----------------------------------------------------
  // 检查是否为 Google Flow 系统按钮/热键图标文字（排除取消收藏、更多选项等噪声，兼容简中/繁中/英文）
  function isSystemHotbarLabel(text) {
    if (!text || typeof text !== "string") return true;
    const t = text.trim().toLowerCase();
    const systemSet = new Set([
      "取消收藏", "收藏", "加入最愛", "移除最愛", "取消最愛", "favorite", "unfavorite", "add to favorites", "remove from favorites",
      "更多选项", "更多選項", "更多项目选项", "更多專案選項", "more_vert", "more options", "more project options",
      "image", "play_circle", "play_arrow", "download", "redo", "delete", "search", "filter_list", "add", "home", "help", "swap_horiz",
      "显示用户图片的图块", "顯示使用者圖像的圖塊", "顯示使用者圖片的圖塊", "tile showing user image", "user image tile",
      "生成的视频缩略图", "生成的影片縮圖", "generated video thumbnail", "video thumbnail",
      "图块", "圖塊", "tile", "重复使用提示词", "重複使用提示詞", "reuse prompt"
    ]);
    return systemSet.has(t);
  }

  // 精准提取媒体图块标题名称
  function extractTileDisplayName(container, imgEl) {
    if (!container) return "";
    
    // 1. 最优先：明确的卡片标题元素（Google Flow 底部浮层文件名）
    const titleEl = typeof container.querySelector === "function" ? container.querySelector(".footer-title, .tile-name, .tile-title, input.editable-text-input, [data-tile-title]") : null;
    if (titleEl) {
      const val = titleEl.value || titleEl.textContent?.trim();
      if (val && !isSystemHotbarLabel(val)) return val;
    }

    // 2. 宿主卡片的 aria-label（Google Flow 顶层容器通常带有完整文件名）
    const card = (typeof container.closest === "function" ? container.closest("flow-grid-tile-container, [data-tile-id], flow-tile, flow-media-tile") : null) || container;
    const cardAria = card?.getAttribute?.("aria-label") || container.getAttribute?.("aria-label");
    if (cardAria && !isSystemHotbarLabel(cardAria)) {
      return cardAria.trim();
    }

    // 3. footer-left 区域（移除 mat-icon 等图标后的纯文件名）
    const footerLeft = typeof container.querySelector === "function" ? container.querySelector(".footer-left, .hover-footer, flow-tile-hover-footer") : null;
    if (footerLeft) {
      if (typeof footerLeft.cloneNode === "function") {
        const clone = footerLeft.cloneNode(true);
        if (typeof clone.querySelectorAll === "function") {
          clone.querySelectorAll("mat-icon, svg, button").forEach(el => el.remove());
        }
        const val = clone.textContent?.trim();
        if (val && !isSystemHotbarLabel(val)) return val;
      } else {
        const val = footerLeft.textContent?.trim();
        if (val && !isSystemHotbarLabel(val)) return val;
      }
    }

    // 4. 卡片的 title 属性
    const cardTitle = card?.getAttribute?.("title") || container.getAttribute?.("title");
    if (cardTitle && !isSystemHotbarLabel(cardTitle)) return cardTitle.trim();

    // 5. 图片自身属性
    if (imgEl) {
      const imgTitle = imgEl.getAttribute?.("title") || imgEl.getAttribute?.("aria-label");
      if (imgTitle && !isSystemHotbarLabel(imgTitle)) return imgTitle.trim();
      if (imgEl.alt && !isSystemHotbarLabel(imgEl.alt)) {
        return imgEl.alt.trim();
      }
    }

    return "";
  }

  // 深度归一化图名辅助器
  function normalizeNameHelper(name) {
    if (!name || typeof name !== "string") return "";
    return name
      .toLowerCase()
      // 全角转半角 (如 （1） 转为 (1) )
      .replace(/[\uff01-\uff5e]/g, ch => String.fromCharCode(ch.charCodeAt(0) - 0xfee0))
      // 去除文件扩展名
      .replace(/\.(jpeg|jpg|png|webp|gif|bmp|mp4|mov)$/i, "")
      // 统一符号为空格
      .replace(/[()[\]{}（）【】_.\-\s]+/g, " ")
      .trim();
  }

  function cleanCompactName(name) {
    return normalizeNameHelper(name).replace(/\s+/g, "");
  }

  function extractSequenceIndex(name) {
    if (!name) return null;
    const norm = String(name).replace(/[\uff01-\uff5e]/g, ch => String.fromCharCode(ch.charCodeAt(0) - 0xfee0));
    const m = norm.match(/(?:[(_\-\s]|^)(\d{1,3})(?:[)_\-\s]|\.\w+$|$)/);
    return m ? parseInt(m[1], 10) : null;
  }

  // 智能图名比对判定器（完全支持各种日期、格式、括号、序号、前后缀差异）
  function isImageNameMatch(targetName, pageName) {
    if (!targetName || !pageName) return false;

    const targetClean = cleanCompactName(targetName);
    const pageClean = cleanCompactName(pageName);

    if (!targetClean || !pageClean) return false;

    // 1. 紧凑形式完全一致
    if (targetClean === pageClean) return true;

    // 2. 检查序号一致性：若两者都有序号，但序号不相等，则严禁匹配！（例如 (3) 绝对不匹配 (6)）
    const targetSeq = extractSequenceIndex(targetName);
    const pageSeq = extractSequenceIndex(pageName);
    if (targetSeq !== null && pageSeq !== null && targetSeq !== pageSeq) {
      return false;
    }

    // 3. 包含匹配（且序号必须一致）
    if (targetClean.includes(pageClean) || pageClean.includes(targetClean)) {
      if (targetSeq !== null && pageSeq !== null) {
        return targetSeq === pageSeq;
      }
      return true;
    }

    // 4. 标准分词重叠匹配（去掉纯数字后关键词有交集）
    const targetNorm = normalizeNameHelper(targetName);
    const pageNorm = normalizeNameHelper(pageName);
    const targetWords = targetNorm.split(" ").filter(w => w.length >= 2 && !/^\d+$/.test(w));
    const pageWords = pageNorm.split(" ").filter(w => w.length >= 2 && !/^\d+$/.test(w));

    if (targetWords.length > 0 && pageWords.length > 0) {
      const hasCommon = targetWords.some(tw => pageWords.some(pw => tw.includes(pw) || pw.includes(tw)));
      if (hasCommon) {
        if (targetSeq !== null && pageSeq !== null) {
          return targetSeq === pageSeq;
        }
        return true;
      }
    }

    return false;
  }

  // 获取当前 Flow 合集/项目页面的所有已上传素材列表
  function getLoadedPageImages() {
    const images = [];
    const seenIds = new Set();

    // 1. 优先从所有图块容器中扫描（排除视频图块 flow-video-tile）
    const candidateContainers = document.querySelectorAll(
      "flow-grid-tile-container, " +
      "flow-image-tile, " +
      "flow-tile, " +
      "flow-media-tile, " +
      ".virtual-item-container:has(img), " +
      "[data-tile-id]"
    );

    candidateContainers.forEach((container, idx) => {
      if (container.tagName === "FLOW-VIDEO-TILE" || container.querySelector?.("flow-video-tile") || container.closest?.("flow-video-tile")) return;
      const img = container.querySelector("img");
      if (!img || img.classList.contains("thumbnail")) return;
      const src = img.src || img.getAttribute("src") || "";
      if (!src || src.includes("avatar") || src.includes("favicon") || src.includes("googlelogo") || src.startsWith("data:image/svg") || img.closest(".gb_X, .gbii")) return;

      const displayName = extractTileDisplayName(container, img) || `素材图片_${idx + 1}`;
      const mediaId = img.getAttribute("data-media-id") || container.dataset?.tileId || container.closest("[data-tile-id]")?.dataset?.tileId;
      const nameMatch = src.match(/name=([0-9a-zA-Z_-]+)/) || src.match(/\/([0-9a-fA-F-]{36})/) || src.match(/key=([^&]+)/);
      const uniqueId = mediaId || (nameMatch ? nameMatch[1] : `img_${idx}_${src.substring(src.length - 16)}`);

      if (!seenIds.has(uniqueId)) {
        seenIds.add(uniqueId);
        images.push({
          id: uniqueId,
          primaryMediaKey: uniqueId,
          displayName: displayName,
          src: src
        });
      }
    });

    // 2. 降级兜底：扫描全局 img 元素
    if (!images.length) {
      document.querySelectorAll("flow-project-page img, cdk-virtual-scroll-viewport img, .tiles-container img, .virtual-scroll-container img").forEach((img, idx) => {
        const src = img.src || "";
        if (!src || src.startsWith("data:image/svg") || src.includes(".svg") || src.includes("googlelogo") || src.includes("avatar") || src.includes("favicon") || src.includes("gb_")) return;
        const card = img.closest("flow-grid-tile-container, [data-tile-id], mat-card, div") || img.parentElement;
        const displayName = extractTileDisplayName(card, img) || `页面素材_${idx + 1}`;
        const uniqueId = `img_fallback_${idx}`;
        if (!seenIds.has(uniqueId)) {
          seenIds.add(uniqueId);
          images.push({
            id: uniqueId,
            primaryMediaKey: uniqueId,
            displayName: displayName,
            src: src
          });
        }
      });
    }

    console.log(`[FlowUI] 读取到页面素材图片共 ${images.length} 张:`, images);
    return images;
  }

  function loadPageImages() {
    const images = getLoadedPageImages();
    if (!images.length) {
      showToast("页面暂未识别到候选素材图片。请确认项目已有素材，或直接点击“导入外部配置”粘贴任务。");
      return;
    }

    // 对当前任务列表中未关联到缩略图的任务进行自动匹配补齐
    let autoResolvedCount = 0;
    state.tasks.forEach(task => {
      if (!task.image?.src) {
        const taskName = task.image?.displayName || "";
        const localName = getFilenameFromPath(task.image?.localImagePath || task.local_image_path);
        const matched = images.find(img => 
          (taskName && isImageNameMatch(taskName, img.displayName)) || 
          (localName && isImageNameMatch(localName, img.displayName))
        );
        if (matched) {
          task.image = {
            ...matched,
            src: matched.src,
            displayName: task.image?.displayName || matched.displayName,
            localImagePath: task.image?.localImagePath || task.local_image_path
          };
          autoResolvedCount++;
        }
      }
    });

    const addedImageIds = new Set(state.tasks.map(t => t.image?.id).filter(Boolean));
    const newTasks = [];

    images.forEach(img => {
      if (!addedImageIds.has(img.id)) {
        newTasks.push({
          image: img,
          text: "",
          preset: state.presets[0]?.name || "无模版(直接填入)",
          footageType: state.settings.footageType,
          count: state.settings.defaultCount,
          status: [],
          message: [],
          downloaded: [],
          download_path: ""
        });
      }
    });

    if (newTasks.length > 0 || autoResolvedCount > 0) {
      if (newTasks.length > 0) state.tasks = [...state.tasks, ...newTasks];
      renderTable();
      saveState();
      showToast(`加载成功！新增 ${newTasks.length} 个任务，自动补全 ${autoResolvedCount} 个已有任务图块`);
    } else {
      showToast(`页面识别到 ${images.length} 张图片，任务列表已为最新`);
    }
  }

  // ----------------------------------------------------
  // 4.5 本地图片 → Flow 原生拖放上传（方案移植自 FlowStudio 插件）
  //   网页脚本伪造的 DragEvent/File 都是 isTrusted=false，Flow 不会接收；
  //   这里改由后台 chrome.debugger 发送 Input.dispatchDragEvent，
  //   把 JSON 中的 local_image_path 绝对路径作为「真实文件」拖入 Flow 工作区。
  // ----------------------------------------------------
  const UPLOAD_BATCH_SIZE = 10;
  const UPLOAD_CONFIRM_TIMEOUT_MS = 120000;
  let uploadInFlight = false;

  // 严格比对：避免模糊关键词匹配把「同人物不同编号」的图误判为已上传
  function isStrictImageMatch(targetName, pageName) {
    const a = cleanCompactName(targetName), b = cleanCompactName(pageName);
    if (!a || !b) return false;
    if (a === b) return true;
    // Flow 卡片名称可能被截断：较长的一方以较短一方开头，且较短一方足够长
    const [s, l] = a.length <= b.length ? [a, b] : [b, a];
    return s.length >= 12 && l.startsWith(s);
  }

  function getTaskUploadName(task) {
    return getFilenameFromPath(task.image?.localImagePath || task.local_image_path || "") || task.image?.displayName || "";
  }

  function findStrictPageImage(task, pageImages) {
    const names = [getTaskUploadName(task), task.image?.displayName].filter(Boolean);
    return pageImages.find(img => names.some(n => isStrictImageMatch(n, img.displayName))) || null;
  }

  // 找出「有本地路径但 Flow 页面中还没有」的任务
  function getTasksNeedingUpload(rowFilter = null) {
    const pageImages = getLoadedPageImages();
    const out = [];
    state.tasks.forEach((task, idx) => {
      if (rowFilter !== null && idx !== rowFilter) return;
      if (!splitTextToLines(task.text).length) return;
      if ((task.status || []).length && task.status.every(s => s === "success")) return;
      const path = task.image?.localImagePath || task.local_image_path || "";
      if (!path || !/^([a-zA-Z]:[\\/]|\/|\\\\)/.test(path)) return; // 必须是绝对路径
      if (findStrictPageImage(task, pageImages)) return;
      out.push({ idx, task, path, name: getTaskUploadName(task) });
    });
    // 同一张图被多个任务使用时只上传一次
    const seen = new Set();
    return out.filter(x => { const k = x.path.toLowerCase(); if (seen.has(k)) return false; seen.add(k); return true; });
  }

  // 定位 Flow 的拖放区域（「开始创建或拖放媒体」/ 素材网格，兼容简中/繁中/英文）
  function findFlowDropPoint() {
    const phrases = [
      "开始创建或拖放媒体", "拖放媒体", "开始创建",
      "開始建立或拖放媒體", "拖放媒體", "新增媒體", "上傳項目",
      "drop media", "drag media", "drop files", "drag files", "start creating"
    ];
    let best = null;
    document.querySelectorAll("div,section,main,[role='main'],[role='button'],span,p").forEach(el => {
      if (el.closest("#flow-batch-overlay, #flow-import-dialog, #flow-alarm-dialog, #flow-batch-fab")) return;
      const r = el.getBoundingClientRect();
      if (r.width < 80 || r.height < 30 || r.bottom <= 0 || r.top >= innerHeight) return;
      const txt = String((el.innerText || "") + " " + (el.getAttribute("aria-label") || "")).replace(/\s+/g, " ").toLowerCase();
      if (!phrases.some(p => txt.includes(p))) return;
      const area = r.width * r.height;
      if (!best || area > best.area) best = { r, area };
    });
    if (best) {
      return {
        x: Math.max(10, Math.min(innerWidth - 10, Math.round(best.r.left + best.r.width / 2))),
        y: Math.max(10, Math.min(innerHeight - 10, Math.round(best.r.top + best.r.height / 2))),
        source: "flow_drop_zone"
      };
    }
    // 素材网格区域
    const grid = document.querySelector("flow-project-page cdk-virtual-scroll-viewport, cdk-virtual-scroll-viewport, .tiles-container, flow-project-page");
    if (grid) {
      const r = grid.getBoundingClientRect();
      if (r.width > 100 && r.height > 100) {
        return { x: Math.round(r.left + r.width / 2), y: Math.round(Math.max(r.top + 60, Math.min(r.bottom - 60, r.top + r.height * 0.4))), source: "media_grid" };
      }
    }
    return { x: Math.round(Math.max(420, innerWidth * 0.58)), y: Math.round(Math.max(330, innerHeight * 0.46)), source: "workspace_fallback" };
  }

  // 上传期间必须隐藏插件的全屏遮罩，否则原生拖放会落在插件面板上而不是 Flow 页面
  function setOverlayHiddenForUpload(hidden) {
    const ids = ["flow-batch-overlay", "flow-import-dialog", "flow-batch-fab"];
    ids.forEach(id => {
      const el = document.getElementById(id);
      if (!el) return;
      if (hidden) {
        el.dataset.uploadPrevVisibility = el.style.getPropertyValue("visibility") || "";
        el.style.setProperty("visibility", "hidden", "important");
        el.style.setProperty("pointer-events", "none", "important");
      } else {
        const prev = el.dataset.uploadPrevVisibility;
        if (prev) el.style.setProperty("visibility", prev, "important"); else el.style.removeProperty("visibility");
        el.style.setProperty("pointer-events", "auto", "important");
        delete el.dataset.uploadPrevVisibility;
      }
    });
  }

  /**
   * 把缺失的本地图片批量上传到当前 Flow 项目，并等待素材出现在页面中。
   * @returns {Promise<{ok:boolean, uploaded:number, missing:string[]}>}
   */
  async function uploadLocalImagesToFlow({ rowFilter = null, silent = false } = {}) {
    if (uploadInFlight) { showToast("图片正在上传中，请稍候..."); return { ok: false, uploaded: 0, missing: [] }; }
    if (!location.href.includes("/project/")) {
      showToast("请先进入具体的 Flow 项目页面再上传图片", 5000);
      return { ok: false, uploaded: 0, missing: [] };
    }
    const pending = getTasksNeedingUpload(rowFilter);
    if (!pending.length) {
      if (!silent) showToast("所有任务图片都已在 Flow 中，无需上传");
      return { ok: true, uploaded: 0, missing: [] };
    }

    uploadInFlight = true;
    const btn = document.getElementById("btn-upload-local");
    if (btn) btn.disabled = true;
    try {
      showToast(`📤 正在把 ${pending.length} 张本地图片上传到 Flow...`, 4000);
      setOverlayHiddenForUpload(true);
      await delay(250);

      // 1) 分批原生拖放
      for (let i = 0; i < pending.length; i += UPLOAD_BATCH_SIZE) {
        if (isStopRequested) break;
        const chunk = pending.slice(i, i + UPLOAD_BATCH_SIZE);
        const pt = findFlowDropPoint();
        console.log(`[FlowUpload] 拖放第 ${i / UPLOAD_BATCH_SIZE + 1} 批 ${chunk.length} 张 @`, pt, chunk.map(c => c.path));
        const res = await sendToExtension("nativeFileDrag", { paths: chunk.map(c => c.path), x: pt.x, y: pt.y });
        if (!res || res.ok === false || res.error) {
          const err = res?.error || "未知错误";
          console.error("[FlowUpload] 原生拖放失败:", err);
          showToast(`❌ 图片上传失败：${err}\n（如提示 debugger 权限，请在扩展管理页重新加载插件）`, 8000);
          return { ok: false, uploaded: 0, missing: pending.map(p => p.name) };
        }
        await delay(1500);
      }

      // 2) 轮询 Flow 素材网格，直到全部图片出现
      const start = Date.now();
      let remaining = pending;
      while (Date.now() - start < UPLOAD_CONFIRM_TIMEOUT_MS) {
        if (isStopRequested) break;
        await delay(2000);
        const pageImages = getLoadedPageImages();
        remaining = pending.filter(p => !findStrictPageImage(p.task, pageImages));
        showToast(`📤 Flow 已接收 ${pending.length - remaining.length}/${pending.length} 张图片...`, 2200);
        if (!remaining.length) break;
      }
      // 给 Flow 一点时间完成缩略图/媒体处理
      if (!remaining.length) await delay(2500);

      // 3) 将任务严格重新绑定到刚上传的素材（覆盖导入时可能的模糊误匹配）
      const pageImages = getLoadedPageImages();
      state.tasks.forEach((task, idx) => {
        if (rowFilter !== null && idx !== rowFilter) return;
        const m = findStrictPageImage(task, pageImages);
        if (m) {
          task.image = { ...m, src: m.src, displayName: task.image?.displayName || m.displayName, localImagePath: task.image?.localImagePath || task.local_image_path };
        }
      });
      await saveState();

      const missing = remaining.map(r => r.name);
      if (missing.length) {
        console.warn("[FlowUpload] 以下图片未在 Flow 中确认:", missing);
        showToast(`⚠️ 上传完成 ${pending.length - missing.length}/${pending.length}，未确认：${missing.slice(0, 3).join("、")}${missing.length > 3 ? " 等" : ""}`, 8000);
      } else {
        showToast(`✅ ${pending.length} 张本地图片已全部上传到 Flow`, 4000);
      }
      return { ok: missing.length === 0, uploaded: pending.length - missing.length, missing };
    } finally {
      setOverlayHiddenForUpload(false);
      uploadInFlight = false;
      if (btn) btn.disabled = false;
      try { renderTable(); } catch (_) {}
    }
  }

  /**
   * 全局托管模式：按「本地绝对路径列表」上传图片，并逐张确认是否真正进入 Flow。
   * @returns {Promise<{uploaded:string[], skipped:string[], failed:string[], errors:Object}>}
   */
  async function uploadPathsToFlow(paths, { timeoutMs = 60000 } = {}) {
    const clean = [...new Set((paths || []).map(p => String(p || "").trim()).filter(Boolean))];
    const result = { uploaded: [], skipped: [], failed: [], errors: {} };
    if (!clean.length) return result;
    const failAll = (list, reason) => list.forEach(p => { result.failed.push(p); result.errors[p] = reason; });

    if (!location.href.includes("/project/")) { failAll(clean, "浏览器当前不在 Flow 项目页面"); return result; }
    for (let i = 0; uploadInFlight && i < 60; i++) await delay(500);
    if (uploadInFlight) { failAll(clean, "插件正在执行其他上传"); return result; }

    const nameOf = p => getFilenameFromPath(p);
    const isPresent = (p, imgs) => imgs.some(img => isStrictImageMatch(nameOf(p), img.displayName));

    uploadInFlight = true;
    try {
      let imgs = getLoadedPageImages();
      const todo = [];
      clean.forEach(p => (isPresent(p, imgs) ? result.skipped.push(p) : todo.push(p)));
      if (!todo.length) return result;

      setOverlayHiddenForUpload(true);
      await delay(250);
      const dispatched = [];
      for (let i = 0; i < todo.length; i += UPLOAD_BATCH_SIZE) {
        const chunk = todo.slice(i, i + UPLOAD_BATCH_SIZE);
        const pt = findFlowDropPoint();
        const res = await sendToExtension("nativeFileDrag", { paths: chunk, x: pt.x, y: pt.y });
        if (!res || res.ok === false || res.error) failAll(chunk, "拖放失败：" + (res?.error || "未知错误"));
        else dispatched.push(...chunk);
        await delay(1500);
      }

      // 轮询确认
      const start = Date.now();
      let waiting = dispatched.slice();
      while (waiting.length && Date.now() - start < timeoutMs) {
        await delay(2000);
        imgs = getLoadedPageImages();
        waiting = waiting.filter(p => !isPresent(p, imgs));
      }
      dispatched.forEach(p => {
        if (waiting.includes(p)) { result.failed.push(p); result.errors[p] = "Flow 未确认收到该图片（超时）"; }
        else result.uploaded.push(p);
      });
      if (result.uploaded.length) await delay(2000);
      return result;
    } finally {
      setOverlayHiddenForUpload(false);
      uploadInFlight = false;
    }
  }

  // ----------------------------------------------------
  // 5. 对接导入解析与闭环报告导出
  // ----------------------------------------------------
  
  // 截取本地路径中的文件名
  function getFilenameFromPath(filePath) {
    if (!filePath) return "";
    const cleanPath = filePath.replace(/\\/g, "/");
    return cleanPath.substring(cleanPath.lastIndexOf("/") + 1);
  }

  function normalizeDuration(value, fallback = null) {
    if (value == null || value === "") return fallback;
    const match = String(value).trim().match(/^(\d+(?:\.\d+)?)\s*(?:s|秒|seconds?)?$/i);
    const seconds = match ? Number(match[1]) : NaN;
    if (!Number.isFinite(seconds) || seconds <= 0) throw new Error(`无效的视频秒数: ${value}`);
    return seconds;
  }

  // 手动解析 JSON 数据对接导入
  function handleJSONImport() {
    const rawVal = document.getElementById("flow-import-textarea").value.trim();
    if (!rawVal) {
      alert("内容为空！");
      return;
    }

    let parsedList = [];
    try {
      parsedList = JSON.parse(rawVal);
      if (!Array.isArray(parsedList)) {
        alert("导入数据格式错误！必须为 JSON 数组格式（由 [ 和 ] 包裹）。");
        return;
      }
    } catch (e) {
      alert(`JSON 解析失败，请检查格式！\n错误详情: ${e.message}`);
      return;
    }

    let importCount = 0;
    try {
      importCount = importTaskList(parsedList);
    } catch (err) { alert(`导入失败：${err.message}`); return; }

    closeImportDialog();
    renderTable();
    saveState();
    
    showToast(`导入成功！已加入 ${importCount} 个任务配置`);
  }

  // 可复用的任务导入核心（手动导入 / 全局托管模式共用）；出错时抛出异常，不弹窗
  function importTaskList(parsedList) {
    if (!Array.isArray(parsedList)) throw new Error("任务数据必须是数组");
    parsedList.forEach((item, index) => {
      if (!item || typeof item !== "object" || Array.isArray(item)) throw new Error(`第 ${index + 1} 项不是任务对象`);
      item.duration = normalizeDuration(item.duration ?? item.duration_seconds ?? item.durationSeconds, 6);
    });
    const loadedImages = getLoadedPageImages();
    console.log("[FlowUI] 正在导入 JSON，当前页面识别到的图片列表为:", loadedImages);
    
    let importCount = 0;

    parsedList.forEach(item => {
      const prompt = item.prompt || item.text || "";
      const mode = item.mode || item.footageType || "VIDEO_FRAMES";
      const duration = item.duration;
      const downloadPath = item.download_path || item.downloadPath || "";
      const imageName = item.image_name || item.imageName || item.displayName || item.name || "";
      const localImagePath = item.local_image_path || item.localImagePath || item.path || "";
      const localFileName = getFilenameFromPath(localImagePath);
      // 支持直接在 JSON 中传入网络图片或 Base64 DataURL
      const incomingSrc = item.image_url || item.imageUrl || item.src || item.image_src || item.base64 || item.image_base64 || item.dataUrl || "";

      // 图片查找匹配逻辑：采用多维度智能图名比对 (归一化、中英文括号、序号一致性、关键词交集)
      let matchedImg = null;
      if (imageName || localFileName) {
        matchedImg = loadedImages.find(img => {
          return (imageName && isImageNameMatch(imageName, img.displayName)) ||
                 (localFileName && isImageNameMatch(localFileName, img.displayName));
        });
      }

      console.log("[FlowUI] 匹配比对详情:", {
        输入图名: imageName,
        输入本地路径: localImagePath,
        匹配目标清理: { targetName: cleanCompactName(imageName), targetLocalName: cleanCompactName(localFileName) },
        匹配结果: matchedImg ? matchedImg.displayName : "未在页面即时找到"
      });

      const finalDisplayName = imageName || localFileName || (matchedImg ? matchedImg.displayName : "未命名素材");
      let finalTaskImage = null;

      if (matchedImg) {
        finalTaskImage = {
          ...matchedImg,
          src: matchedImg.src || incomingSrc,
          displayName: matchedImg.displayName || finalDisplayName,
          localImagePath: localImagePath
        };
      } else {
        finalTaskImage = {
          id: null,
          primaryMediaKey: null,
          displayName: finalDisplayName,
          src: incomingSrc,
          localImagePath: localImagePath
        };
      }

      // 关键！状态一律初始化为 pending 就绪态，绝不导入时判为 failed 错误！
      const linesCount = splitTextToLines(prompt).length || 1;
      const statusList = new Array(linesCount).fill("pending");
      const messageList = new Array(linesCount).fill("等待批量调度");

      // 提取 JSON 中可能指定的独立比例、分辨率、模型和间隔时间 (具备智能归一化与规则同步)
      const rawAspect = item.aspect_ratio || item.aspectRatio || "";
      let taskAspect = state.settings.aspectRatio;
      if (rawAspect.includes("9:16") || rawAspect.includes("9_16") || String(rawAspect).toUpperCase().includes("PORTRAIT")) {
        taskAspect = "ASPECT_RATIO_9_16";
      } else if (rawAspect.includes("1:1") || rawAspect.includes("1_1") || String(rawAspect).toUpperCase().includes("SQUARE")) {
        taskAspect = "ASPECT_RATIO_1_1";
      } else if (rawAspect.includes("16:9") || rawAspect.includes("16_9") || String(rawAspect).toUpperCase().includes("LANDSCAPE")) {
        taskAspect = "ASPECT_RATIO_16_9";
      }

      const rawRes = item.resolution || item.video_resolution || "";
      let taskRes = state.settings.resolution;
      if (String(rawRes).includes("360")) taskRes = "VIDEO_RESOLUTION_360P";
      else if (String(rawRes).includes("1080")) taskRes = "VIDEO_RESOLUTION_1080P";
      else if (String(rawRes).includes("720")) taskRes = "VIDEO_RESOLUTION_720P";

      const rawModel = String(item.model || item.video_model || "").trim().toLowerCase();
      let taskModel = state.settings.videoModel || "omni_1_1_flash";
      if (rawModel) {
        if (rawModel.includes("omni") || rawModel.includes("flash")) {
          taskModel = "omni_1_1_flash";
        } else if (rawModel.includes("low_priority") || rawModel.includes("lower priority") || rawModel.includes("lowpriority") || rawModel.includes("低优先级") || rawModel.includes("低優先順序")) {
          taskModel = "veo_3_1_lite_low_priority";
        } else if (rawModel.includes("quality")) {
          taskModel = "veo_3_1_quality";
        } else if (rawModel.includes("fast")) {
          taskModel = "veo_3_1_fast";
        } else if (rawModel.includes("lite")) {
          taskModel = "veo_3_1_lite";
        } else if (rawModel.includes("veo_2") || rawModel.includes("veo2") || rawModel === "veo 2") {
          taskModel = "veo_2";
        }
      }

      const rawInterval = item.interval ?? item.task_interval;
      let taskInterval = null;
      if (rawInterval !== undefined && rawInterval !== null && rawInterval !== "") {
        const parsedInt = Number(rawInterval);
        if (Number.isFinite(parsedInt) && parsedInt >= 0) {
          taskInterval = parsedInt;
          // 同步软件规则设置的间隔时间到全局设置，并将随机抖动归零以严格执行该间隔
          state.settings.interval = taskInterval;
          state.settings.intervalRandom = 0;
        }
      }

      // 同步软件规则设置的默认参数到插件面板
      if (rawAspect) state.settings.aspectRatio = taskAspect;
      if (rawModel) state.settings.videoModel = taskModel;
      if (item.mode || item.footageType) state.settings.footageType = mode;

      state.tasks.push({
        image: finalTaskImage,
        text: prompt,
        preset: "无模版(直接填入)",
        footageType: mode,
        count: item.count || 1,
        status: statusList,
        message: messageList,
        downloaded: new Array(linesCount).fill(false),
        download_path: downloadPath,
        duration: duration,
        aspectRatio: taskAspect,
        resolution: taskRes,
        videoModel: taskModel,
        interval: taskInterval
      });
      importCount++;
    });

    // 同步更新设置抽屉 DOM 控件显示
    const syncDomVal = (id, val) => {
      const el = document.getElementById(id);
      if (el && val !== undefined && val !== null) el.value = val;
    };
    syncDomVal("cfg-interval", state.settings.interval);
    syncDomVal("cfg-random", state.settings.intervalRandom);
    syncDomVal("cfg-aspect", state.settings.aspectRatio);
    syncDomVal("cfg-model", state.settings.videoModel);
    syncDomVal("cfg-footagetype", state.settings.footageType);

    return importCount;
  }

  // 复制执行报告（供 Python 读取剪贴板，一键归位）
  function copyExecutionReport() {
    if (!state.tasks.length) {
      alert("当前任务列表为空，无可导出的报告。");
      return;
    }

    const report = state.tasks.map(task => {
      // 合并状态 (因为页面支持分行，导入只对应单条绝对路径，直接去 status[0])
      return {
        prompt: task.text,
        image_name: task.image.displayName,
        download_path: task.download_path,
        duration: task.duration ?? null,
        status: task.status[0] || "pending",
        message: task.message[0] || ""
      };
    });

    try {
      const jsonStr = JSON.stringify(report, null, 2);
      navigator.clipboard.writeText(jsonStr).then(() => {
        alert("执行报告 JSON 已成功复制到系统剪贴板！\n请回到您的 Python 客户端软件中读取并点击“剪切归位”按钮。");
      }).catch(err => {
        alert("复制剪贴板失败，请手动在控制台查看。");
        console.log("[Execution Report]", jsonStr);
      });
    } catch (e) {
      alert("导出错误: " + e.message);
    }
  }

  // ----------------------------------------------------
  // 6. 任务表格渲染
  // ----------------------------------------------------
  function renderTable() {
    const tbody = document.querySelector("#flow-tasks-table tbody");
    if (!tbody) return;
    tbody.replaceChildren();

    // 自动对任务列表中没有预览图的任务尝试结合页面图片进行关联补全
    const pageImages = getLoadedPageImages();
    if (pageImages.length > 0) {
      state.tasks.forEach(task => {
        if (!task.image?.src) {
          const taskName = task.image?.displayName || "";
          const localName = getFilenameFromPath(task.image?.localImagePath || task.local_image_path);
          const matched = pageImages.find(img => 
            (taskName && isImageNameMatch(taskName, img.displayName)) || 
            (localName && isImageNameMatch(localName, img.displayName))
          );
          if (matched) {
            task.image = {
              ...matched,
              src: matched.src,
              displayName: task.image?.displayName || matched.displayName,
              localImagePath: task.image?.localImagePath || task.local_image_path
            };
          }
        }
      });
    }

    if (!state.tasks.length) {
      setSafeHTML(tbody, `
        <tr>
          <td colspan="8" style="text-align: center; color: var(--flow-text-secondary); padding: 40px 0;">
            暂无任务。请点击“导入外部 JSON”粘贴任务数据，或点击“加载页面图片”直接导入当前网页上的原料。
          </td>
        </tr>
      `);
      return;
    }

    state.tasks.forEach((task, rowIndex) => {
      const tr = document.createElement("tr");
      
      // 1. 图片预览与名称展示列
      const imgTd = document.createElement("td");
      imgTd.style.width = "115px";
      imgTd.style.textAlign = "center";
      
      const imgPreviewSrc = task.image?.src || (task.image?.primaryMediaKey?.startsWith("http") ? task.image.primaryMediaKey : "");
      const taskDisplayName = task.image?.displayName || "未命名素材";

      if (imgPreviewSrc) {
        setSafeHTML(imgTd, `
          <div class="cell-image-container" title="点击可更换本地图片预览" data-row="${rowIndex}">
            <div class="cell-image-box has-image">
              <img class="cell-image-preview" src="${imgPreviewSrc}" alt="预览" />
              <div class="cell-image-hover-mask">更换</div>
            </div>
            <span class="cell-image-name" title="${taskDisplayName}">${taskDisplayName}</span>
          </div>
        `);
      } else {
        setSafeHTML(imgTd, `
          <div class="cell-image-container" title="未关联图像，点击可直接选择本地图片预览" data-row="${rowIndex}">
            <div class="cell-image-box no-image">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
                <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
                <circle cx="8.5" cy="8.5" r="1.5"></circle>
                <polyline points="21 15 16 10 5 21"></polyline>
              </svg>
              <span class="cell-image-pick-text">选图</span>
            </div>
            <span class="cell-image-name" title="${taskDisplayName}">${taskDisplayName}</span>
          </div>
        `);
      }

      // 绑定点击本地选图/换图预览功能
      const imgContainer = imgTd.querySelector(".cell-image-container");
      if (imgContainer) {
        imgContainer.addEventListener("click", () => {
          const fileInput = document.createElement("input");
          fileInput.type = "file";
          fileInput.accept = "image/*";
          fileInput.style.setProperty("display", "none", "important");
          fileInput.onchange = (e) => {
            const file = e.target.files[0];
            if (file) {
              const reader = new FileReader();
              reader.onload = (loadEvt) => {
                if (!task.image) task.image = {};
                task.image.src = loadEvt.target.result;
                if (!task.image.displayName || task.image.displayName === "未命名素材" || task.image.displayName.startsWith("素材图片_")) {
                  task.image.displayName = file.name;
                }
                saveState();
                renderTable();
                showToast(`已成功为任务加载图片: ${file.name}`);
              };
              reader.readAsDataURL(file);
            }
          };
          document.body.appendChild(fileInput);
          fileInput.click();
          fileInput.remove();
        });
      }
      tr.appendChild(imgTd);

      // 2. 文本输入列
      const textTd = document.createElement("td");
      const textarea = document.createElement("textarea");
      textarea.className = "cell-textarea";
      textarea.value = task.text;
      textarea.placeholder = "分行输入提示词...";
      textarea.addEventListener("change", (e) => {
        task.text = e.target.value;
        const linesCount = splitTextToLines(task.text).length;
        task.status = extendArray(task.status, linesCount, "pending");
        task.message = extendArray(task.message, linesCount, "");
        task.downloaded = extendArray(task.downloaded, linesCount, false);
        saveState();
        renderTableStatusCell(tr, task, rowIndex);
      });
      textTd.appendChild(textarea);
      tr.appendChild(textTd);

      // 3. 模版下拉列
      const presetTd = document.createElement("td");
      const presetSelect = document.createElement("select");
      presetSelect.className = "cell-select";
      state.presets.forEach(p => {
        const opt = document.createElement("option");
        opt.value = p.name;
        opt.innerText = p.name;
        presetSelect.appendChild(opt);
      });
      presetSelect.value = task.preset || "无模版(直接填入)";
      presetSelect.addEventListener("change", (e) => {
        task.preset = e.target.value;
        saveState();
      });
      presetTd.appendChild(presetSelect);
      tr.appendChild(presetTd);

      // 4. 素材类型列
      const typeTd = document.createElement("td");
      const typeSelect = document.createElement("select");
      typeSelect.className = "cell-select";
      setSafeHTML(typeSelect, `
        <option value="VIDEO_FRAMES">帧模式 (默认)</option>
        <option value="VIDEO_REFERENCES">素材模式</option>
      `);
      typeSelect.value = task.footageType;
      typeSelect.addEventListener("change", (e) => {
        task.footageType = e.target.value;
        saveState();
      });
      typeTd.appendChild(typeSelect);
      tr.appendChild(typeTd);

      const durationTd = document.createElement("td");
      const durationInput = document.createElement("input");
      durationInput.type = "number";
      durationInput.min = "0.1";
      durationInput.step = "any";
      durationInput.className = "cell-select";
      durationInput.style.width = "70px";
      durationInput.value = task.duration ?? "";
      durationInput.placeholder = "自动";
      durationInput.title = "按此秒数提交；当前 Flow 模型不支持时会报错";
      durationInput.addEventListener("change", () => {
        try { task.duration = normalizeDuration(durationInput.value); saveState(); }
        catch (err) { showToast(err.message); durationInput.value = task.duration ?? ""; }
      });
      durationTd.appendChild(durationInput);
      tr.appendChild(durationTd);

      // 5. 生成数数量列
      const countTd = document.createElement("td");
      const countSelect = document.createElement("select");
      countSelect.className = "cell-select";
      countSelect.style.width = "60px";
      countSelect.style.minWidth = "60px";
      [1, 2, 3, 4].forEach(v => {
        const opt = document.createElement("option");
        opt.value = v;
        opt.innerText = v;
        countSelect.appendChild(opt);
      });
      countSelect.value = task.count;
      countSelect.addEventListener("change", (e) => {
        task.count = parseInt(e.target.value, 10);
        saveState();
      });
      countTd.appendChild(countSelect);
      tr.appendChild(countTd);

      // 6. 状态与日志列
      const statusTd = document.createElement("td");
      statusTd.className = "status-cell-container";
      tr.appendChild(statusTd);
      renderTableStatusCell(tr, task, rowIndex);

      // 7. 操作列 (单项运行 + 删除)
      const actionTd = document.createElement("td");
      actionTd.style.textAlign = "center";
      actionTd.style.width = "125px";
      actionTd.style.whiteSpace = "nowrap";

      const runBtn = document.createElement("button");
      runBtn.className = "flow-btn primary";
      runBtn.style.cssText = "padding: 3px 8px; font-size: 11px; margin-right: 6px; border-radius: 4px; display: inline-flex; align-items: center; gap: 3px; background: #10b981; border: none; color: #fff; cursor: pointer;";
      runBtn.title = "仅运行当前这一项任务，生成并下载完毕后即停止";
      setSafeHTML(runBtn, `
        <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
        <span>单跑</span>
      `);
      runBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        if (batchPromise) {
          showToast("已有生成队列正在执行中，请先停止后再启动");
          return;
        }
        startBatch(rowIndex);
      });
      actionTd.appendChild(runBtn);

      const delBtn = document.createElement("button");
      delBtn.className = "cell-btn-delete";
      delBtn.title = "单独删除此项任务配置";
      setSafeHTML(delBtn, `
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path><line x1="10" y1="11" x2="10" y2="17"></line><line x1="14" y1="11" x2="14" y2="17"></line></svg>
        <span>删除</span>
      `);
      delBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        if (batchPromise && rowIndex === state.currentIndex) {
          showToast("当前任务正在生成中，请先停止队列再删除该任务");
          return;
        }
        const taskName = task.image?.displayName || `任务 #${rowIndex + 1}`;
        if (state.currentIndex > rowIndex) {
          state.currentIndex--;
        } else if (state.currentIndex === rowIndex) {
          state.currentLineIndex = 0;
        }
        state.tasks.splice(rowIndex, 1);
        renderTable();
        saveState();
        showToast(`已删除任务: ${taskName}`);
      });
      actionTd.appendChild(delBtn);
      tr.appendChild(actionTd);

      tbody.appendChild(tr);
    });
  }

  function renderTableStatusCell(rowElement, task, rowIndex) {
    const container = rowElement.querySelector(".status-cell-container");
    if (!container) return;
    
    container.replaceChildren();
    const lines = splitTextToLines(task.text);
    
    if (lines.length === 0) {
      setSafeHTML(container, `<span style="color: var(--flow-text-secondary); font-size:12px;">待输入文本</span>`);
      return;
    }

    const wrapper = document.createElement("div");
    wrapper.style.cssText = "display:flex; flex-direction:column; gap:6px; max-height:86px; overflow-y:auto; padding-right:4px;";
    
    lines.forEach((line, lineIdx) => {
      const status = task.status[lineIdx] || "pending";
      const message = task.message[lineIdx] || "";
      
      const lineRow = document.createElement("div");
      lineRow.className = "status-line-row";
      
      let badgeHtml = "";
      if (status === "pending") {
        badgeHtml = `<span class="status-badge pending"><span style="width:6px; height:6px; border-radius:50%; background:#f59e0b; display:inline-block; box-shadow:0 0 6px #f59e0b; flex-shrink:0;"></span>等待</span>`;
      } else if (status === "generating") {
        badgeHtml = `<span class="status-badge generating"><span class="spinner"></span>生成中</span>`;
      } else if (status === "success") {
        badgeHtml = `<span class="status-badge success">✓ 成功</span>`;
      } else if (status === "failed") {
        badgeHtml = `<span class="status-badge failed" title="${message}">✗ 失败</span>`;
      }

      setSafeHTML(lineRow, `
        <span class="status-line-text" title="${line}">#${lineIdx+1}: ${line}</span>
        <div class="status-line-actions">
          ${badgeHtml}
          ${status !== "pending" && status !== "generating" ? `
            <button class="flow-btn secondary btn-line-reset" data-line="${lineIdx}">${task.mediaBindings?.[lineIdx]?.schema === 2 && status === "failed" ? "重试下载" : "重置"}</button>
          ` : ""}
        </div>
      `);

      // 绑定行重置功能
      const resetBtn = lineRow.querySelector(".btn-line-reset");
      if (resetBtn) {
        resetBtn.addEventListener("click", (e) => {
          const lIdx = parseInt(e.currentTarget.dataset.line, 10);
          const previousStatus = task.status[lIdx];
          task.status[lIdx] = "pending";
          const retryDownload = previousStatus !== "success" && task.mediaBindings?.[lIdx]?.schema === 2;
          task.message[lIdx] = retryDownload ? "等待重新下载已生成的视频" : "已重置等待生成";
          task.downloaded[lIdx] = false;
          if (!retryDownload && task.videoUrls) task.videoUrls[lIdx] = null;
          if (!retryDownload && task.downloadIds) task.downloadIds[lIdx] = null;
          if (!retryDownload && task.mediaBindings) task.mediaBindings[lIdx] = null;
          saveState();
          renderTableStatusCell(rowElement, task, rowIndex);
          if (retryDownload) startBatch();
        });
      }

      wrapper.appendChild(lineRow);
    });

    container.appendChild(wrapper);
  }

  // ----------------------------------------------------
  // 7. 后台防休眠保活引擎与页面遮罩清理
  // ----------------------------------------------------
  let keepAliveAudioCtx = null;
  let keepAliveOsc = null;

  function enableTabKeepAlive() {
    try {
      if (!keepAliveAudioCtx) {
        const AudioCtxClass = window.AudioContext || window.webkitAudioContext;
        if (AudioCtxClass) {
          keepAliveAudioCtx = new AudioCtxClass();
          keepAliveOsc = keepAliveAudioCtx.createOscillator();
          const gain = keepAliveAudioCtx.createGain();
          gain.gain.value = 0.00001; // 人耳绝对静音 (几乎为 0)
          keepAliveOsc.connect(gain);
          gain.connect(keepAliveAudioCtx.destination);
          keepAliveOsc.start();
          if (keepAliveAudioCtx.state === "suspended") {
            keepAliveAudioCtx.resume();
          }
          console.log("[FlowUI] 已激活后台防休眠引擎，Chrome 将以最高优先级持续执行后台任务！");
        }
      } else if (keepAliveAudioCtx.state === "suspended") {
        keepAliveAudioCtx.resume();
      }
    } catch (e) {
      console.warn("[FlowUI] 启用音频防休眠提示:", e);
    }
  }

  function disableTabKeepAlive() {
    try {
      if (keepAliveOsc) {
        keepAliveOsc.stop();
        keepAliveOsc.disconnect();
        keepAliveOsc = null;
      }
      if (keepAliveAudioCtx) {
        keepAliveAudioCtx.close();
        keepAliveAudioCtx = null;
      }
      console.log("[FlowUI] 已停用后台防休眠引擎");
    } catch (e) {}
  }

  // 清理 Flow 页面上的历史弹窗、菜单、全屏预览与 backdrop，保证操作视口清空
  async function cleanupPageOverlays() {
    try {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", code: "Escape", bubbles: true }));
      const backdrops = document.querySelectorAll(".cdk-overlay-backdrop");
      backdrops.forEach(bd => {
        try { bd.click(); } catch (_) {}
      });

      // 若意外打开了素材/大图详情面板，自动点击返回或关闭按钮退出大图模式（兼容简中/繁中/英文）
      const detailExitBtn = document.querySelector(
        "button[aria-label='返回'], button[aria-label='Back'], button[aria-label='关闭'], button[aria-label='關閉'], button[aria-label='Close'], .asset-detail-back, flow-asset-detail button:first-child"
      );
      if (detailExitBtn && !detailExitBtn.disabled) {
        console.log("[FlowUI] 检测到大图/素材详情面板，自动点击退出");
        try { detailExitBtn.click(); } catch (_) {}
      }

      const mainContainer = document.querySelector("flow-project-page, .project-container, body");
      if (mainContainer) {
        mainContainer.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      }
      await delay(200);
    } catch (e) {
      console.warn("[FlowUI] 清理页面遮罩提示:", e);
    }
  }

  let isStopRequested = false;

  let batchPromise = null;
  function startBatch(singleRowIndex = null) {
    if (batchPromise) return batchPromise;
    isStopRequested = false;
    document.querySelectorAll("#flow-tasks-table input, #flow-tasks-table textarea, #flow-tasks-table select, #flow-tasks-table button").forEach(el => el.disabled = true);
    document.getElementById("btn-start-batch")?.style.setProperty("display", "none", "important");
    document.getElementById("btn-stop-batch")?.style.setProperty("display", "inline-flex", "important");
    batchPromise = runBatch(singleRowIndex).catch(err => {
      console.error("[Batch] 队列异常", err);
      showToast(`队列停止：${err.message}`, 6000);
    }).finally(() => {
      onBatchFinished();
      document.querySelectorAll("#flow-tasks-table input, #flow-tasks-table textarea, #flow-tasks-table select, #flow-tasks-table button").forEach(el => el.disabled = false);
      batchPromise = null;
    });
    return batchPromise;
  }

  // ====================================================
  // 7.5 Google Vids 专属逐个任务自动化生成与下载引擎 (兼容简中/繁中/英文)
  // ====================================================
  async function ensureVidsSidebarAndAnimateTab() {
    // 1. 若存在初始模板欢迎弹窗，自动点击“生成 AI 视频片段”或按 Escape 关闭
    const welcomeDialog = document.querySelector('#insertabletemplates-dialog-notforstyling[role="dialog"]');
    if (welcomeDialog && welcomeDialog.offsetParent !== null && getComputedStyle(welcomeDialog).display !== "none") {
      const videogenEntryBtn = welcomeDialog.querySelector("button.appsDocsGettingStartedEntryPointSelectionViewButton.videogen");
      if (videogenEntryBtn) {
        console.log("[Vids] 检测到欢迎弹窗，自动点击 [生成 AI 视频片段] 入口...");
        simulateClick(videogenEntryBtn);
      } else {
        document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", code: "Escape", bubbles: true }));
      }
      await delay(700);
    }

    // 2. 确保右侧“AI 视频片段”侧边栏处于打开状态（兼容简中/繁中/英文）
    const isSidebarOpen = () => {
      const sb = document.querySelector(".appsDocsAiGenerativeaiVideoUiSidebarWizVideogensidebarSidebarContent, .appsDocsAiGenerativeaiVideoUiSidebarWizVideogensidebarWideSideSheet");
      return !!(sb && sb.offsetParent !== null && sb.getBoundingClientRect().width > 100);
    };

    if (!isSidebarOpen()) {
      const railBtn = document.getElementById("content-library-rail-video-generation-element") ||
                      document.querySelector(
                        '[aria-label="生成 AI 视频片段"], [aria-label="產生 AI 影片片段"], [aria-label="生成 AI 影片片段"], ' +
                        '[aria-label*="AI 视频"], [aria-label*="AI 影片"], [aria-label*="AI video" i], ' +
                        '[data-tooltip="AI 视频片段"], [data-tooltip="AI 影片片段"], [data-tooltip*="AI video" i]'
                      );
      if (railBtn) {
        console.log("[Vids] 正在点击右侧边栏按钮打开 [AI 视频片段] 面板...");
        simulateClick(railBtn);
        for (let w = 0; w < 12; w++) {
          await delay(500);
          if (isSidebarOpen()) break;
        }
      }
    }

    // 3. 确保切换到“添加动画”/“加入動畫”/“Animate”标签页（或第 2 个 Tab）
    let animateTab = null;
    const animateRe = /(添加动画|加入動畫|新增動畫|加上動畫|動畫|动画|Animate|Add animation|Image)/i;
    for (let w = 0; w < 8; w++) {
      const tabs = Array.from(document.querySelectorAll('button.collapsiblePromptBoxTabButton[role="tab"], button.collapsiblePromptBoxTabButton, .collapsiblePromptBoxContainerWithTabs button[role="tab"]'));
      animateTab = tabs.find(b => animateRe.test(b.textContent || "") || animateRe.test(b.getAttribute("aria-label") || "")) ||
                   (tabs.length >= 2 ? tabs[1] : null);
      if (animateTab) break;
      await delay(400);
    }

    if (animateTab && animateTab.getAttribute("aria-selected") !== "true") {
      console.log("[Vids] 正在切换到 [添加动画 / 加入動畫 / Animate] 标签页...");
      simulateClick(animateTab);
      await delay(500);
    }
  }

  async function ensureVidsPromptBoxExpanded() {
    for (let attempt = 0; attempt < 6; attempt++) {
      const container = document.querySelector(".collapsiblePromptBoxContainerWithTabs");
      const toggleBtn = document.querySelector("button.collapsiblePromptBoxToggleExpansionButton");
      const genBtn = document.querySelector("button.collapsiblePromptBoxGenerateButton");
      const genBtnVisible = !!(genBtn && genBtn.offsetParent !== null && genBtn.getBoundingClientRect().height > 0);
      const isExpandedClass = container ? container.classList.contains("collapsiblePromptBoxContainerWithTabsExpanded") : true;
      const toggleLabel = toggleBtn ? (toggleBtn.getAttribute("aria-label") || "").trim() : "";

      if (isExpandedClass && genBtnVisible && !/^(展开|展開|Expand)$/i.test(toggleLabel)) {
        return true;
      }
      if (toggleBtn && toggleBtn.offsetParent !== null) {
        console.log(`[Vids] 提示词框当前处于收起状态 (aria-label="${toggleLabel}")，点击展开...`);
        simulateClick(toggleBtn);
        await delay(500);
      } else if (container) {
        simulateClick(container);
        await delay(500);
      } else {
        await delay(400);
      }
    }
    return true;
  }

  async function expandAndClearVidsPromptBox() {
    // 1. 先确保提示词框已展开（Vids 每次提交生成后会自动收起提示词框）
    await ensureVidsPromptBoxExpanded();
    await delay(250);

    // 2. 点击“清除”/“Clear”按钮（同时清除上一次的提示词与已上传图片）
    const clearRe = /(清除|清空|Clear)/i;
    const clearBtn = document.querySelector("button.promptTextAreaMenuBarClearLabel") ||
                     Array.from(document.querySelectorAll(".promptTextAreaMenuBarRightActions button, .promptTextAreaMenuBarV2Container button"))
                       .find(b => clearRe.test((b.textContent || "").trim()) || clearRe.test(b.getAttribute("data-tooltip") || "") || clearRe.test(b.getAttribute("aria-label") || ""));
    if (clearBtn && clearBtn.offsetParent !== null && !clearBtn.disabled && clearBtn.getAttribute("aria-disabled") !== "true") {
      console.log("[Vids] 点击 [清除] 按钮清空上一任务的提示词与图片...");
      simulateClick(clearBtn);
      await delay(500);
    }

    // 3. 保底检查：若仍有残留图片预览，点击“移除图片”/“移除圖片”/“Remove image”按钮
    const removeImgBtn = document.querySelector(
      'button.removeInputButtonButton, .removeInputButtonContainer button, ' +
      'button[aria-label="移除图片"], button[aria-label="移除圖片"], button[aria-label="移除圖像"], button[aria-label*="Remove" i]'
    );
    if (removeImgBtn && removeImgBtn.offsetParent !== null) {
      console.log("[Vids] 点击 [移除图片] 按钮清理残留图片...");
      simulateClick(removeImgBtn);
      await delay(400);
    }

    // 4. 保底检查：若输入框仍有残留文字，清空输入框
    const editor = document.querySelector("div.promptTextAreaPromptRichTextInputInternal[contenteditable='true'], [jsname='ZeIRi'][role='textbox']");
    if (editor && (editor.textContent || "").trim().length > 0) {
      try {
        editor.focus();
        const sel = window.getSelection();
        const range = document.createRange();
        range.selectNodeContents(editor);
        sel.removeAllRanges();
        sel.addRange(range);
        document.execCommand("delete", false, null);
      } catch (_) {}
      if ((editor.textContent || "").trim().length > 0) {
        editor.textContent = "";
      }
      editor.dispatchEvent(new InputEvent("input", { bubbles: true, cancelable: true, inputType: "deleteContentBackward" }));
      await delay(250);
    }
  }

  async function syncVidsVideoSettings({ aspectRatio, resolution, duration }) {
    await ensureVidsPromptBoxExpanded();
    const settingsBtn = document.querySelector(
      "button.appsDocsAiGenerativeaiVideoUiSidebarWizVideogencreationviewMenubuttonsMenubuttonGenerationSettingsButton, " +
      "button[aria-label^='生成设置'], button[aria-label^='生成設定'], button[aria-label^='產生設定'], button[aria-label^='Generation settings' i]"
    );
    if (!settingsBtn) {
      console.warn("[Vids] 未找到 Vids 生成设置按钮，跳过设置同步");
      return;
    }

    const wantPortrait = !String(aspectRatio || "").includes("16_9") && !String(aspectRatio || "").includes("16:9");
    const targetAspectRe = wantPortrait
      ? /(竖屏|豎屏|直向|直式|9:16|Portrait)/i
      : /(横屏|橫屏|横向|橫向|橫式|16:9|Landscape)/i;
    const targetAspectLabel = wantPortrait ? "竖屏/直向(9:16)" : "横屏/橫向(16:9)";
    const targetResLabel = String(resolution || "").includes("1080") ? "1080p" : "720p";
    const targetDuration = Math.min(10, Math.max(3, Math.round(Number(duration) || 8)));

    const ariaSummary = settingsBtn.getAttribute("aria-label") || "";
    const textSummary = (settingsBtn.textContent || "").replace(/\s+/g, "");
    const aspectAlreadyOk = targetAspectRe.test(ariaSummary) || targetAspectRe.test(textSummary);
    const resAlreadyOk = ariaSummary.includes(targetResLabel) || textSummary.includes(targetResLabel);
    const durRe = new RegExp(`(^|\\D)${targetDuration}\\s*(秒|s|sec|seconds)(\\D|$)`, "i");
    const durAlreadyOk = durRe.test(ariaSummary) || durRe.test(textSummary);

    if (aspectAlreadyOk && resAlreadyOk && durAlreadyOk) {
      console.log(`[Vids] 当前生成设置 (${ariaSummary}) 已符合目标要求，无需打开设置菜单`);
      return;
    }

    console.log(`[Vids] 同步生成设置: 目标比例=${targetAspectLabel}, 分辨率=${targetResLabel}, 时长=${targetDuration}s (当前=${ariaSummary})`);
    simulateClick(settingsBtn);
    await delay(500);

    const popover = document.querySelector(".appsDocsAiGenerativeaiVideoUiSidebarWizVideogencreationviewMenubuttonsMenubuttonPopoverContainer");
    if (popover) {
      // (a) 宽高比：横屏 / 竖屏（兼容简中/繁中/英文）
      const aspectBtns = Array.from(popover.querySelectorAll(
        ".appsDocsAiGenerativeaiVideoUiSidebarWizVideogencreationviewMenubuttonsMenubuttonAspectRatioButtonGroup button[role='radio'], button[role='radio']"
      ));
      const targetAspectBtn = aspectBtns.find(b => targetAspectRe.test(b.textContent || "") || targetAspectRe.test(b.getAttribute("aria-label") || ""));
      if (targetAspectBtn && targetAspectBtn.getAttribute("aria-checked") !== "true") {
        console.log(`[Vids] 切换宽高比 -> ${targetAspectLabel}`);
        simulateClick(targetAspectBtn);
        await delay(300);
      }

      // (b) 分辨率：720p / 1080p
      const resSection = popover.querySelector(".appsDocsAiGenerativeaiVideoUiSidebarWizVideogencreationviewMenubuttonsMenubuttonResolutionSection");
      if (resSection) {
        const resDropBtn = resSection.querySelector("button");
        if (resDropBtn && !(resDropBtn.textContent || "").includes(targetResLabel)) {
          simulateClick(resDropBtn);
          await delay(350);
          const menuItems = Array.from(document.querySelectorAll("li[role='menuitemradio'], [role='menuitemradio']"));
          const targetItem = menuItems.find(li => (li.textContent || "").includes(targetResLabel));
          if (targetItem) {
            console.log(`[Vids] 切换分辨率 -> ${targetResLabel}`);
            simulateClick(targetItem);
            await delay(350);
          }
        }
      }

      // (c) 视频时长滑块 (3s - 10s)
      const sliderInput = popover.querySelector("input.javascriptMaterialdesignGm3WizSlider-slider__input[type='range'], input[type='range']");
      if (sliderInput && Number(sliderInput.value) !== targetDuration) {
        console.log(`[Vids] 调整视频时长滑块: ${sliderInput.value}s -> ${targetDuration}s`);
        try {
          const track = popover.querySelector(".javascriptMaterialdesignGm3WizSlider-slider__track");
          if (track) {
            const rect = track.getBoundingClientRect();
            if (rect.width > 20) {
              const ratio = (targetDuration - 3) / (10 - 3);
              const clientX = Math.round(rect.left + ratio * rect.width);
              const clientY = Math.round(rect.top + rect.height / 2);
              const pInit = { bubbles: true, cancelable: true, view: window, clientX, clientY, pointerId: 1, isPrimary: true };
              track.dispatchEvent(new PointerEvent("pointerdown", pInit));
              track.dispatchEvent(new PointerEvent("pointermove", pInit));
              track.dispatchEvent(new PointerEvent("pointerup", pInit));
              track.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, view: window, clientX, clientY }));
              await delay(200);
            }
          }
          const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set;
          if (nativeSetter) {
            nativeSetter.call(sliderInput, String(targetDuration));
          } else {
            sliderInput.value = String(targetDuration);
          }
          sliderInput.setAttribute("value", String(targetDuration));
          sliderInput.setAttribute("aria-valuetext", `${targetDuration} 秒`);
          sliderInput.dispatchEvent(new Event("focus", { bubbles: true }));
          sliderInput.dispatchEvent(new Event("input", { bubbles: true }));
          sliderInput.dispatchEvent(new Event("change", { bubbles: true }));
          sliderInput.dispatchEvent(new Event("blur", { bubbles: true }));
          await delay(300);
        } catch (sErr) {
          console.warn("[Vids] 调整时长滑块异常:", sErr);
        }
      }
    }

    // 关闭设置菜单
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", code: "Escape", bubbles: true }));
    await delay(250);
  }

  function hasVidsUploadedImagePreview() {
    const img = document.querySelector("img.inputPreviewItemPreview, .inputPreviewItemPreviewContainer img");
    if (!img || img.offsetParent === null) return false;
    const src = img.getAttribute("src") || img.src || "";
    return src.length > 10;
  }

  function getVidsDropTargetPoint() {
    const candidates = [
      document.querySelector(".promptTextAreaPromptRichTextInput"),
      document.querySelector(".videoGenCreationViewFileInputsContainerV2"),
      document.querySelector(".collapsiblePromptBoxTabPanelContent"),
      document.querySelector(".collapsiblePromptBoxContainerWithTabs")
    ].filter(Boolean);

    for (const el of candidates) {
      const r = el.getBoundingClientRect();
      if (r.width > 50 && r.height > 20 && r.top >= 0 && r.bottom <= window.innerHeight) {
        return {
          x: Math.round(r.left + r.width / 2),
          y: Math.round(r.top + Math.min(r.height / 2, 48))
        };
      }
    }
    return { x: Math.round(window.innerWidth - 200), y: Math.round(window.innerHeight - 220) };
  }

  async function uploadSingleImageToVids(task) {
    const localPath = String(task.image?.localImagePath || task.local_image_path || "").trim();
    const imgSrc = String(task.image?.src || "").trim();
    const imgName = task.image?.displayName || getFilenameFromPath(localPath) || "image.png";

    if (!localPath && !imgSrc) {
      console.log("[Vids] 当前任务未指定图片，跳过图片上传");
      return true;
    }

    await ensureVidsPromptBoxExpanded();

    // 策略 1：使用后台 Chrome Debugger 原生文件拖放 (Input.dispatchDragEvent) 把本地路径图片直接拖入 Vids 提示词框
    if (localPath && /^([a-zA-Z]:[\\/]|\/|\\\\)/.test(localPath)) {
      for (let attempt = 0; attempt < 2; attempt++) {
        if (isStopRequested) return false;
        const pt = getVidsDropTargetPoint();
        console.log(`[Vids] 正在通过原生拖放上传本地图片 (尝试 ${attempt + 1}/2) @(${pt.x}, ${pt.y}): ${localPath}`);
        setOverlayHiddenForUpload(true);
        await delay(150);
        let res = null;
        try {
          res = await sendToExtension("nativeFileDrag", { paths: [localPath], x: pt.x, y: pt.y });
        } finally {
          setOverlayHiddenForUpload(false);
        }

        if (res && res.ok !== false && !res.error) {
          for (let w = 0; w < 18; w++) {
            if (isStopRequested) return false;
            await delay(400);
            if (hasVidsUploadedImagePreview()) {
              console.log(`[Vids] ✅ 本地图片上传成功，已检测到预览缩略图: ${imgName}`);
              await delay(600);
              return true;
            }
          }
        } else {
          console.warn("[Vids] 原生文件拖放返回异常:", res?.error);
        }
      }
    }

    // 策略 2：若存在 Base64 / Blob / 网络图片 src，通过 ClipboardEvent('paste') 与 DragEvent('drop') 注入
    if (imgSrc) {
      try {
        console.log("[Vids] 尝试通过剪贴板 Paste / Drop 注入图片数据...");
        let blob = null;
        if (imgSrc.startsWith("data:image/")) {
          const byteString = atob(imgSrc.split(",")[1]);
          const mimeString = imgSrc.split(",")[0].split(":")[1].split(";")[0];
          const ab = new ArrayBuffer(byteString.length);
          const ia = new Uint8Array(ab);
          for (let i = 0; i < byteString.length; i++) ia[i] = byteString.charCodeAt(i);
          blob = new Blob([ab], { type: mimeString });
        } else {
          const resp = await fetch(imgSrc);
          blob = await resp.blob();
        }
        if (blob) {
          const file = new File([blob], imgName, { type: blob.type || "image/png" });
          const dt = new DataTransfer();
          dt.items.add(file);

          const editor = document.querySelector("div.promptTextAreaPromptRichTextInputInternal[contenteditable='true']") ||
                         document.querySelector(".promptTextAreaPromptRichTextInput");
          if (editor) {
            editor.focus();
            editor.dispatchEvent(new ClipboardEvent("paste", { bubbles: true, cancelable: true, clipboardData: dt }));
            editor.dispatchEvent(new DragEvent("drop", { bubbles: true, cancelable: true, dataTransfer: dt }));
          }
          for (let w = 0; w < 12; w++) {
            await delay(400);
            if (hasVidsUploadedImagePreview()) {
              console.log("[Vids] ✅ Paste/Drop 图片上传成功！");
              await delay(500);
              return true;
            }
          }
        }
      } catch (e) {
        console.warn("[Vids] Paste/Drop 注入图片失败:", e);
      }
    }

    return hasVidsUploadedImagePreview();
  }

  async function fillVidsPromptAndSubmit(finalPrompt) {
    await ensureVidsPromptBoxExpanded();
    const editor = document.querySelector("div.promptTextAreaPromptRichTextInputInternal[contenteditable='true']") ||
                   document.querySelector("[jsname='ZeIRi'][role='textbox']");
    if (!editor) {
      throw new Error("未找到 Google Vids 提示词输入框，请确认右侧 [AI 视频片段] 侧边栏已打开");
    }

    editor.focus();
    simulateClick(editor);
    await delay(150);

    let injected = false;
    try {
      const sel = window.getSelection();
      const range = document.createRange();
      range.selectNodeContents(editor);
      sel.removeAllRanges();
      sel.addRange(range);
      injected = document.execCommand("insertText", false, finalPrompt);
    } catch (e) {
      console.warn("[Vids] execCommand 注入提示词异常:", e);
    }

    if (!injected || (editor.textContent || "").trim() !== finalPrompt.trim()) {
      editor.textContent = finalPrompt;
    }
    editor.classList.remove("promptTextAreaPromptRichTextInputInternalIsEmpty");

    editor.dispatchEvent(new InputEvent("beforeinput", { bubbles: true, cancelable: true, inputType: "insertText", data: finalPrompt }));
    editor.dispatchEvent(new InputEvent("input", { bubbles: true, cancelable: true, inputType: "insertText", data: finalPrompt }));
    editor.dispatchEvent(new KeyboardEvent("keyup", { key: " ", code: "Space", bubbles: true }));
    editor.dispatchEvent(new Event("change", { bubbles: true }));
    await delay(400);

    // 等待生成按钮可用并点击（兼容简中/繁中/英文，严格排除顶部 Tab 按钮如「建立」）
    const findGenBtn = () => {
      const byClass = document.querySelector(
        "button.collapsiblePromptBoxGenerateButton, " +
        "button[data-idom-class*='collapsiblePromptBoxGenerateButton'], " +
        ".promptTextAreaMenuBarRightActions button.collapsiblePromptBoxGenerateButton, " +
        ".promptTextAreaMenuBarRightActions button:not(.promptTextAreaMenuBarClearLabel)"
      );
      if (byClass) return byClass;

      const touchDiv = document.querySelector(
        "button.collapsiblePromptBoxGenerateButton .javascriptMaterialdesignGm3WizIconButtonFilled-icon-button__touch, " +
        ".promptTextAreaMenuBarRightActions .javascriptMaterialdesignGm3WizIconButtonFilled-icon-button__touch, " +
        ".promptTextAreaMenuBarV2Container .javascriptMaterialdesignGm3WizIconButtonFilled-icon-button__touch"
      );
      if (touchDiv) {
        const parentBtn = touchDiv.closest("button");
        if (parentBtn) return parentBtn;
      }

      const candidates = Array.from(document.querySelectorAll(
        "button[aria-label='生成'], button[aria-label='產生'], button[aria-label='傳送'], button[aria-label='发送'], button[aria-label='Generate' i]"
      ));
      return candidates.find(b =>
        b.getAttribute("role") !== "tab" &&
        !b.classList.contains("collapsiblePromptBoxTabButton") &&
        !b.closest("[role='tablist']")
      ) || null;
    };

    let genBtn = null;
    for (let i = 0; i < 20; i++) {
      if (isStopRequested) throw new Error("用户已停止任务");
      genBtn = findGenBtn();
      if (genBtn && !genBtn.disabled && !genBtn.hasAttribute("disabled") && genBtn.getAttribute("aria-disabled") !== "true") {
        break;
      }
      if (editor) {
        editor.dispatchEvent(new InputEvent("input", { bubbles: true, cancelable: true, inputType: "insertText", data: finalPrompt }));
      }
      genBtn = null;
      await delay(350);
    }

    if (!genBtn) {
      genBtn = findGenBtn();
      if (!genBtn) throw new Error("未找到 Google Vids [生成] 按钮");
      genBtn.removeAttribute("disabled");
      genBtn.disabled = false;
      genBtn.setAttribute("aria-disabled", "false");
    }

    const touchTarget = genBtn.querySelector(".javascriptMaterialdesignGm3WizIconButtonFilled-icon-button__touch") || genBtn;
    console.log("[Vids] 🚀 点击 [生成] 按钮提交当前任务...", { genBtn, touchTarget });
    const rect = touchTarget.getBoundingClientRect();
    const cx = rect.width > 0 ? Math.round(rect.left + rect.width / 2) : 0;
    const cy = rect.height > 0 ? Math.round(rect.top + rect.height / 2) : 0;
    try {
      if (typeof PointerEvent !== "undefined") {
        touchTarget.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, cancelable: true, view: window, clientX: cx, clientY: cy, pointerId: 1, isPrimary: true }));
        touchTarget.dispatchEvent(new PointerEvent("pointerup", { bubbles: true, cancelable: true, view: window, clientX: cx, clientY: cy, pointerId: 1, isPrimary: true }));
      }
      touchTarget.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true, view: window, clientX: cx, clientY: cy }));
      touchTarget.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, cancelable: true, view: window, clientX: cx, clientY: cy }));
    } catch (_) {}
    if (typeof touchTarget.click === "function") {
      touchTarget.click();
    } else {
      genBtn.click();
    }
    await delay(400);

    // 保底：若 400ms 后按钮仍处于可用未提交状态且提示词框仍展开，直接在 button 本体上补发一次点击
    const stillBtn = findGenBtn();
    const stillExpanded = document.querySelector(".collapsiblePromptBoxContainerWithTabsExpanded");
    if (stillBtn && stillExpanded && !stillBtn.disabled && !stillBtn.hasAttribute("disabled") && stillBtn.getAttribute("aria-disabled") !== "true") {
      console.log("[Vids] 🔁 检测到 touch 层点击后按钮仍未进入提交态，在 button 本体补发 click...");
      stillBtn.click();
    }
    await delay(400);
  }

  async function runVidsBatch(singleRowIndex = null) {
    state.isSuspended = false;
    enableTabKeepAlive();

    const validTasks = state.tasks.filter(t => splitTextToLines(t.text).length > 0);
    if (!validTasks.length) {
      alert("无可执行生成任务！(任务列表为空或提示词未填)");
      return;
    }

    if (isStopRequested) return;
    state.isRunning = true;
    document.getElementById("btn-start-batch")?.style.setProperty("display", "none", "important");
    document.getElementById("btn-stop-batch")?.style.setProperty("display", "inline-flex", "important");

    // 在 Vids 模式下自动收起全屏面板遮罩，方便右侧侧边栏交互与实时查看生成过程
    closePanel();

    const isSingle = singleRowIndex !== null && typeof singleRowIndex === "number";
    showToast(isSingle ? `🎬 [Vids] 开始执行单项任务 #${singleRowIndex + 1}...` : `🎬 [Vids] 开始逐个任务生成队列 (共 ${state.tasks.length} 项)...`, 4000);

    // 1. 打开右侧 AI 视频片段侧边栏并切换到“添加动画”
    await ensureVidsSidebarAndAnimateTab();

    const startRow = isSingle ? singleRowIndex : (state.currentIndex || 0);
    const endRow = isSingle ? (singleRowIndex + 1) : state.tasks.length;

    for (let rIdx = startRow; rIdx < endRow; rIdx++) {
      state.currentIndex = rIdx;
      await saveState();

      const task = state.tasks[rIdx];
      const lines = splitTextToLines(task.text);
      if (!lines.length) continue;
      if (!task.image) task.image = { displayName: `任务_${rIdx + 1}`, primaryMediaKey: "" };

      for (let lIdx = state.currentLineIndex || 0; lIdx < lines.length; lIdx++) {
        state.currentLineIndex = lIdx;
        await saveState();

        if (isStopRequested) {
          showToast("🎬 用户中断了 Vids 批量任务！");
          onBatchFinished();
          return;
        }

        if (task.status[lIdx] === "success" || (Array.isArray(task.downloaded) && task.downloaded[lIdx])) {
          continue;
        }

        const lineText = lines[lIdx];
        const duration = normalizeDuration(task.duration, calculateDuration(lineText));
        const preset = state.presets.find(p => p.name === task.preset);
        const parsedPreset = parsePreset(preset?.content);
        const finalPrompt = `${parsedPreset.before || ""}\n${lineText || ""}\n${parsedPreset.after || ""}`.trim();

        const targetDownloadPath = resolveDownloadPath(task.download_path, {
          image: task.image,
          rowIndex: rIdx,
          lineIndex: lIdx
        });

        updateLineStatus(rIdx, lIdx, "pending", "正在展开并清空 Vids 输入框...");
        showToast(`🎬 [Vids ${rIdx + 1}/${state.tasks.length}] 准备任务: ${task.image?.displayName || `#${rIdx + 1}`}`, 3500);

        // Step A: 确保侧边栏与“添加动画”标签页打开，点击“展开”并点击“清除”
        await ensureVidsSidebarAndAnimateTab();
        await expandAndClearVidsPromptBox();

        // Step B: 同步生成设置 (宽高比、分辨率、时长 3-10s)
        try {
          await syncVidsVideoSettings({
            aspectRatio: task.aspectRatio || state.settings.aspectRatio,
            resolution: task.resolution || state.settings.resolution,
            duration: duration
          });
        } catch (settErr) {
          console.warn("[Vids] 同步生成设置提示:", settErr);
        }

        // Step C: 上传当前任务的单张图片
        if (task.image && (task.image.localImagePath || task.local_image_path || task.image.src)) {
          updateLineStatus(rIdx, lIdx, "pending", `正在上传图片: ${task.image.displayName || ""}...`);
          showToast(`📤 [Vids ${rIdx + 1}/${state.tasks.length}] 正在上传图片: ${task.image.displayName || ""}`, 3500);
          const upOk = await uploadSingleImageToVids(task);
          if (!upOk) {
            updateLineStatus(rIdx, lIdx, "failed", "图片上传到 Vids 失败或超时，未检测到图片预览");
            showToast(`❌ [Vids ${rIdx + 1}/${state.tasks.length}] 图片上传失败，跳过本项`, 5000);
            continue;
          }
        }

        // Step D: 拍摄提交前已有视频与错误卡片快照
        const existingGenIds = new Set(
          Array.from(document.querySelectorAll("[data-generation-id]"))
            .map(el => el.getAttribute("data-generation-id"))
            .filter(Boolean)
        );
        const existingVideoUrls = new Set(
          Array.from(document.querySelectorAll(".appsDocsAiGenerativeaiVideoUiSidebarWizVideogenerationthumbnailsContainer video, video"))
            .map(v => (v.getAttribute("src") || v.currentSrc || v.src || "").trim().replace(/&amp;/g, "&"))
            .filter(Boolean)
        );
        const existingFailedEls = new Set(
          Array.from(document.querySelectorAll(".appsDocsAiGenerativeaiVideoUiSidebarWizFailedvideogenerationthumbnailContainer"))
        );

        // Step E: 输入提示词并点击“生成”
        const submissionId = crypto.randomUUID();
        task.taskId = task.taskId || crypto.randomUUID();
        task.mediaBindings = task.mediaBindings || [];
        task.downloadIds = task.downloadIds || [];
        task.downloadIds[lIdx] = null;
        task.videoUrls = task.videoUrls || [];
        task.videoUrls[lIdx] = null;
        task.mediaBindings[lIdx] = {
          schema: 2,
          submissionId,
          taskId: task.taskId,
          mediaIds: [],
          readyIds: [],
          downloadPath: targetDownloadPath
        };
        await saveState();

        try {
          updateLineStatus(rIdx, lIdx, "generating", "正在填入提示词并点击生成...");
          await fillVidsPromptAndSubmit(finalPrompt);
          updateLineStatus(rIdx, lIdx, "generating", "已提交到 Google Vids，等待视频生成完成...");
          showToast(`🚀 [Vids ${rIdx + 1}/${state.tasks.length}] 已提交生成，正在等待视频渲染完成...`, 4000);
        } catch (subErr) {
          console.error("[Vids] 提交任务失败:", subErr);
          updateLineStatus(rIdx, lIdx, "failed", `提交失败: ${subErr.message}`);
          continue;
        }

        // Step F: 轮询等待新视频出现并下载完成
        const maxWaitSec = Math.max(180, Number(state.settings.maxWaitTime) || 360);
        const waitStartTime = Date.now();
        let isTaskCompleted = false;
        let downloadTriggered = false;

        while ((Date.now() - waitStartTime) / 1000 < maxWaitSec) {
          if (isStopRequested) break;
          const waitedSec = Math.round((Date.now() - waitStartTime) / 1000);

          // 1. 检查是否已有下载任务完成
          if (task.downloadIds?.[lIdx] && !task.downloaded[lIdx]) {
            const dlState = await sendToExtension("getDownloadStatus", { downloadId: task.downloadIds[lIdx] });
            if (dlState?.state === "complete") {
              task.downloaded[lIdx] = true;
              updateLineStatus(rIdx, lIdx, "success", `自动下载成功: ${targetDownloadPath}`);
              isTaskCompleted = true;
              break;
            } else if (dlState?.state === "interrupted") {
              updateLineStatus(rIdx, lIdx, "failed", `下载中断: ${dlState.error || "未知原因"}`);
              break;
            }
          }

          if (task.status[lIdx] === "success" && task.downloaded?.[lIdx]) {
            isTaskCompleted = true;
            break;
          }
          if (task.status[lIdx] === "failed") {
            break;
          }

          // 2. 检查是否新增了生成失败提示卡片（如违反条款拦截）
          if (!downloadTriggered) {
            const currentFailedEls = Array.from(document.querySelectorAll(".appsDocsAiGenerativeaiVideoUiSidebarWizFailedvideogenerationthumbnailContainer"));
            const newFailedEl = currentFailedEls.find(el => !existingFailedEls.has(el));
            if (newFailedEl) {
              const errMsgEl = newFailedEl.querySelector(".appsDocsAiGenerativeaiVideoUiSidebarWizFailedvideogenerationthumbnailErrorMessage");
              const errMsg = (errMsgEl ? errMsgEl.textContent : newFailedEl.textContent || "视频生成被拦截或失败").trim();
              console.warn(`[Vids] ❌ 检测到 Vids 生成失败卡片: ${errMsg}`);
              updateLineStatus(rIdx, lIdx, "failed", `Vids 生成失败: ${errMsg}`);
              showToast(`⚠️ [Vids ${rIdx + 1}/${state.tasks.length}] 生成失败: ${errMsg.substring(0, 45)}`, 5000);
              break;
            }
          }

          // 3. 扫描侧边栏视频列表，寻找新生成的 <video>
          if (!downloadTriggered) {
            let foundVideoUrl = null;
            let foundGenId = null;

            const thumbContainers = Array.from(document.querySelectorAll(
              ".appsDocsAiGenerativeaiVideoUiSidebarWizSuccessfulvideogenerationthumbnailVideoGenerationThumbnailWithPromptContainer[data-generation-id], " +
              ".appsDocsAiGenerativeaiVideoUiSidebarWizVideogenerationthumbnailsContainer [data-generation-id]"
            ));

            for (const c of thumbContainers) {
              const gId = c.getAttribute("data-generation-id") || "";
              const v = c.querySelector("video");
              const rawSrc = v ? (v.getAttribute("src") || v.currentSrc || v.src || "") : "";
              const cleanSrc = rawSrc.trim().replace(/&amp;/g, "&");
              if (cleanSrc && cleanSrc.startsWith("https://")) {
                if ((gId && !existingGenIds.has(gId)) || !existingVideoUrls.has(cleanSrc)) {
                  foundVideoUrl = cleanSrc;
                  foundGenId = gId || `vids_${Date.now()}`;
                  break;
                }
              }
            }

            // 兜底：直接扫描侧边栏内所有 video 标签
            if (!foundVideoUrl) {
              const allVideos = Array.from(document.querySelectorAll(
                ".appsDocsAiGenerativeaiVideoUiSidebarWizVideogenerationthumbnailsContainer video, " +
                "video.appsDocsAiGenerativeaiVideoUiSidebarWizSuccessfulvideogenerationthumbnailVideoGenerationThumbnail"
              ));
              for (const v of allVideos) {
                const rawSrc = v.getAttribute("src") || v.currentSrc || v.src || "";
                const cleanSrc = rawSrc.trim().replace(/&amp;/g, "&");
                if (cleanSrc && cleanSrc.startsWith("https://") && !existingVideoUrls.has(cleanSrc) && !downloadedUrlsSet.has(cleanSrc)) {
                  const parentGenId = v.closest("[data-generation-id]")?.getAttribute("data-generation-id");
                  foundVideoUrl = cleanSrc;
                  foundGenId = parentGenId || `vids_${Date.now()}`;
                  break;
                }
              }
            }

            if (foundVideoUrl && foundGenId) {
              console.log(`[Vids] 🎯 检测到新生成的视频! generationId=${foundGenId}, URL=${foundVideoUrl.substring(0, 100)}`);
              downloadedUrlsSet.add(foundVideoUrl);
              existingVideoUrls.add(foundVideoUrl);
              existingGenIds.add(foundGenId);

              const binding = task.mediaBindings[lIdx];
              binding.mediaIds = [foundGenId];
              binding.readyIds = [foundGenId];
              binding.urls = { [foundGenId]: foundVideoUrl };
              task.videoUrls[lIdx] = foundVideoUrl;
              await saveState();

              const dlRes = await sendToExtension("download", {
                url: foundVideoUrl,
                filename: targetDownloadPath,
                task: {
                  rowIndex: rIdx,
                  lineIndex: lIdx,
                  taskId: task.taskId,
                  submissionId: binding.submissionId,
                  mediaId: foundGenId,
                  projectId: getStorageKey(),
                  download_path: targetDownloadPath,
                  isVids: true
                }
              });

              if (dlRes?.success) {
                downloadTriggered = true;
                task.downloadIds[lIdx] = dlRes.downloadId;
                updateLineStatus(rIdx, lIdx, "generating", `视频已生成，正在下载保存至 ${targetDownloadPath}...`);
                showToast(`📥 [Vids ${rIdx + 1}/${state.tasks.length}] 视频生成完成，正在下载: ${targetDownloadPath}`, 3500);
                await saveState();
              } else {
                updateLineStatus(rIdx, lIdx, "failed", `视频下载失败: ${dlRes?.error || "未知错误"}`);
                break;
              }
            } else {
              updateLineStatus(rIdx, lIdx, "generating", `Google Vids 正在生成视频 (${waitedSec}s)...`);
            }
          }

          await delay(2000);
        }

        if (!isTaskCompleted && !isStopRequested && task.status[lIdx] !== "failed") {
          updateLineStatus(rIdx, lIdx, "failed", `Vids 生成或下载超时 (已等待 ${maxWaitSec} 秒)`);
        }

        state.currentLineIndex = 0;
        await saveState();

        if (isStopRequested) {
          showToast("🎬 用户中断了 Vids 批量任务！");
          onBatchFinished();
          return;
        }

        if (isSingle) {
          showToast(`🎬 [Vids] 单项任务 #${rIdx + 1} 执行完成！`, 4000);
          onBatchFinished();
          return;
        }

        // 任务间隔等待 (严格遵循软件规则设置或面板设置，支持 0 秒及任意秒数)
        const rawInterval = (task.interval !== undefined && task.interval !== null) ? Number(task.interval) : Number(state.settings.interval);
        const intervalSec = (Number.isFinite(rawInterval) && rawInterval >= 0) ? rawInterval : 5;
        const intervalRand = (task.interval !== undefined && task.interval !== null) ? 0 : Math.max(0, Number(state.settings.intervalRandom) || 0);
        const waitTime = Math.round(intervalSec + Math.random() * intervalRand);
        if (waitTime > 0) {
          const targetEndTime = Date.now() + waitTime * 1000;
          while (Date.now() < targetEndTime) {
            if (isStopRequested) break;
            const rem = Math.max(1, Math.round((targetEndTime - Date.now()) / 1000));
            showToast(`✅ [Vids ${rIdx + 1}/${state.tasks.length}] 已完成！${rem} 秒后自动展开清空并开始下一项...`, 1500);
            await delay(1000);
          }
        }
      }
    }

    showToast("🎉 [Vids] 所有队列任务的逐个生成与自动下载已全部完成！", 6000);
    onBatchFinished();
  }

  async function runBatch(singleRowIndex = null) {
    if (isVidsPage()) {
      return await runVidsBatch(singleRowIndex);
    }
    state.isSuspended = false;
    if (alarmDialogEl) alarmDialogEl.style.setProperty("display", "none", "important");
    if (alarmTimer) {
      clearInterval(alarmTimer);
      alarmTimer = null;
    }
    
    // 激活后台防休眠引擎，保证失焦/后台平稳高频运行
    enableTabKeepAlive();

    // 启动安全限制监测
    startActivityCheck();

    // 校验页面生成组件是否就绪 (ProseMirror 富文本框与生成按钮)
    let editor = document.querySelector("flow-rich-text-editor div.ProseMirror") || document.querySelector("div.ProseMirror[contenteditable='true']");
    let genBtn = document.querySelector("flow-generate-icon-button button") || document.querySelector("button.generate-icon-button");

    if (!editor || !genBtn) {
      console.log("[FlowUI] 正在等待页面 ProseMirror 提示词框及生成按钮就绪...");
      for (let w = 0; w < 6; w++) {
        await delay(500);
        editor = document.querySelector("flow-rich-text-editor div.ProseMirror") || document.querySelector("div.ProseMirror[contenteditable='true']");
        genBtn = document.querySelector("flow-generate-icon-button button") || document.querySelector("button.generate-icon-button");
        if (editor && genBtn) break;
      }
    }

    if (!editor || !genBtn) {
      if (!location.href.includes("/project/")) {
        alert("请先进入具体的 Flow 项目页面 (例如 https://flow.google.com/project/...) 再启动批量生成！");
        return;
      }
      console.warn("[FlowUI] 提示词框或生成按钮未完全定位，将在执行时进行动态查找...");
    }

    const validTasks = state.tasks.filter(t => splitTextToLines(t.text).length > 0);
    if (!validTasks.length) {
      alert("无可执行生成任务！(任务列表为空或提示词未填)");
      return;
    }

    if (isStopRequested) return;

    // 生成前自动把缺失的本地图片上传到 Flow（已存在的图片会自动跳过）
    try {
      const isSingleRun = singleRowIndex !== null && typeof singleRowIndex === "number";
      const needUpload = getTasksNeedingUpload(isSingleRun ? singleRowIndex : null);
      if (needUpload.length) {
        console.log(`[Batch] 检测到 ${needUpload.length} 张图片尚未上传到 Flow，先执行原生拖放上传`);
        const up = await uploadLocalImagesToFlow({ rowFilter: isSingleRun ? singleRowIndex : null, silent: true });
        if (!up.ok && up.uploaded === 0 && up.missing.length) {
          showToast(`⚠️ 图片未能上传到 Flow，相关任务可能失败：${up.missing.slice(0, 3).join("、")}`, 6000);
        }
      }
    } catch (upErr) {
      console.warn("[Batch] 自动上传本地图片异常（继续执行生成）:", upErr);
    }
    if (isStopRequested) return;
    state.isRunning = true;
    
    document.getElementById("btn-start-batch").style.setProperty("display", "none", "important");
    document.getElementById("btn-stop-batch").style.setProperty("display", "inline-flex", "important");
    
    const isSingle = singleRowIndex !== null && typeof singleRowIndex === "number";
    showToast(isSingle ? `开始执行单项任务 #${singleRowIndex + 1}...` : "开始自动化批量生成队列...");
    
    const intervalSec = state.settings.interval;
    const intervalRand = state.settings.intervalRandom;

    const startRow = isSingle ? singleRowIndex : (state.currentIndex || 0);
    const endRow = isSingle ? (singleRowIndex + 1) : state.tasks.length;

    // 读取存储中的断点索引继续运行，实现断点续跑
    for (let rIdx = startRow; rIdx < endRow; rIdx++) {
      state.currentIndex = rIdx;
      await saveState();

      const task = state.tasks[rIdx];
      const lines = splitTextToLines(task.text);
      if (!lines.length) continue;
      if (!task.image) task.image = { displayName: `任务_${rIdx + 1}`, primaryMediaKey: "" };

      for (let lIdx = state.currentLineIndex || 0; lIdx < lines.length; lIdx++) {
        state.currentLineIndex = lIdx;
        await saveState();

        if (isStopRequested) {
          showToast("用户中断了批量任务！");
          onBatchFinished();
          return;
        }

        // 跳过已经成功的行
        if (task.status[lIdx] === "success" || (Array.isArray(task.downloaded) && task.downloaded[lIdx])) continue;

        state.activeTasksQueue = [];
        state.taskRecord = {};
        window.currentProcess = null;
        document.querySelectorAll("video").forEach(v => {
          const src = v.getAttribute("src") || v.currentSrc || v.src;
          if (src) downloadedUrlsSet.add(src);
        });
        const lineText = lines[lIdx];
        // 允许单个任务有设定好的 duration，否则动态计算
        const duration = normalizeDuration(task.duration, calculateDuration(lineText));
        const preset = state.presets.find(p => p.name === task.preset);
        const parsedPreset = parsePreset(preset?.content);

        updateLineStatus(rIdx, lIdx, "pending", "排队准备提交...");
        
        let submitOk = false;
        if (task.mediaBindings?.[lIdx]?.schema === 2) {
          submitOk = await retrySavedVideo(task, rIdx, lIdx);
        }
        for (let subTry = 0; task.mediaBindings?.[lIdx]?.schema !== 2 && subTry < 2; subTry++) {
          try {
            if (isStopRequested) return;
            console.log(`[Batch] 自动提交: Row=${rIdx}, Line=${lIdx}, Text=${lineText}, Duration=${duration}`);
            
            await submitTaskToPage({
              image: task.image,
              lineText: lineText,
              presetBefore: parsedPreset.before,
              presetAfter: parsedPreset.after,
              footageType: task.footageType,
              count: task.count,
              duration: duration,
              rowIndex: rIdx,
              lineIndex: lIdx,
              download_path: task.download_path,
              resolution: task.resolution,
              aspectRatio: task.aspectRatio,
              videoModel: task.videoModel
            });

            if (!task.downloaded[lIdx] && !isStopRequested) updateLineStatus(rIdx, lIdx, "generating", "已提交到 Flow，等待对应媒体 ID 生成完成...");
            state.retryCount = 0;
            await saveState();
            submitOk = true;
            break;
            
          } catch (err) {
            console.error(`[Batch] 第 ${subTry + 1} 次提交触发异常:`, err);
            if (err.configurationError) {
              updateLineStatus(rIdx, lIdx, "failed", `未提交生成：${err.message}`);
              break;
            }
            if (subTry === 0) {
              updateLineStatus(rIdx, lIdx, "pending", `提交受阻: ${err.message}，正在等待 3 秒后重试...`);
              await delay(3000);
            } else {
              updateLineStatus(rIdx, lIdx, "failed", "提交失败: " + err.message);
              await saveState();
            }
          }
        }

        if (!submitOk) {
          console.warn(`[Batch] 任务 (Row=${rIdx}, Line=${lIdx}) 提交失败，自动流转至下一项`);
          continue;
        }

        // ====================================================
        // 核心等待逻辑：高精度状态检测 + 视频生成完毕后立刻自动下载 + 严格下载完成后再倒计时流转
        // ====================================================
        const maxWaitSec = Math.max(120, Number(state.settings.maxWaitTime) || 300);
        let waitedSec = 0;
        let isTaskCompleted = false;
        let downloadTriggered = false;
        const waitStartTime = Date.now();
        while ((Date.now() - waitStartTime) / 1000 < maxWaitSec) {
          if (isStopRequested) break;
          if (state.isSuspended) { await delay(500); continue; }

          const binding = task.mediaBindings?.[lIdx];
          console.log(`[Batch] ⏳ 等待中 (${Math.round(waitedSec)}s/${maxWaitSec}s): Row=${rIdx}, Line=${lIdx}, status=${task.status[lIdx]}, downloaded=${task.downloaded[lIdx]}, downloadId=${task.downloadIds?.[lIdx] || '无'}, mediaIds=${JSON.stringify(binding?.mediaIds || [])}, readyIds=${JSON.stringify(binding?.readyIds || [])}`);

          if (task.downloadIds?.[lIdx] && !task.downloaded[lIdx]) {
            console.log(`[Batch] 🔍 正在查询后台下载状态: downloadId=${task.downloadIds[lIdx]}...`);
            const downloadState = await sendToExtension("getDownloadStatus", { downloadId: task.downloadIds[lIdx] });
            console.log(`[Batch] 📥 后台下载状态返回: downloadId=${task.downloadIds[lIdx]}, state=${downloadState?.state}, error=${downloadState?.error || '无'}`);
            if (downloadState?.state === "complete") {
              task.downloaded[lIdx] = true;
              updateLineStatus(rIdx, lIdx, "success", "视频下载已完成");
            } else if (downloadState?.state === "interrupted") {
              updateLineStatus(rIdx, lIdx, "failed", `视频已生成，下载中断: ${downloadState.error || "未知原因"}。可重试下载。`);
            }
          }
          if (task.status[lIdx] === "failed") {
            console.warn(`[Batch] ⚠️ 当前行状态已为 failed，退出等待循环: Row=${rIdx}, Line=${lIdx}, message=${task.message[lIdx]}`);
            break;
          }
          // 1. 检查该任务行是否已经完成下载 (status 变为 success 或 downloaded[lIdx] 变为 true)
          if (task.status[lIdx] === "success" && (Array.isArray(task.downloaded) && task.downloaded[lIdx])) {
            isTaskCompleted = true;
            console.log(`[Batch] 任务已确认生成并下载成功！(Row=${rIdx}, Line=${lIdx}, 耗时=${Math.round(waitedSec)}s)`);
            break;
          }

          let isVideoGenerated = false;

          const boundMediaIds = binding?.mediaIds || [];
          const readyMediaIds = binding?.readyIds || [];

          // 2. 检查是否有已就绪的本任务媒体直链 (优先来自 flow-proxy RPC 拦截或 DOMWatcher)
          let targetVideoUrl = null;
          for (const mId of boundMediaIds) {
            if (binding.urls?.[mId]) {
              targetVideoUrl = binding.urls[mId];
              isVideoGenerated = true;
              console.log(`[Batch] 🎯 找到当前任务已绑定的直链 (mediaId=${mId}): ${targetVideoUrl.substring(0, 80)}`);
              break;
            }
          }

          // 3. 定位属于当前任务行的批次容器并悬停唤醒懒加载视频
          const targetBatchContainer = findCurrentBatchContainer(task, lIdx);
          const currentBatchTiles = targetBatchContainer ? 
            Array.from(targetBatchContainer.querySelectorAll("flow-video-tile")) : 
            Array.from(document.querySelectorAll("flow-video-tile"));

          if (currentBatchTiles.length > 0) {
            for (const tile of currentBatchTiles) {
              triggerTileHover(tile);
            }
          }

          // 4. 严格校验：只有视频 mediaId 明确匹配当前任务的 boundMediaIds 时，才认领为本任务视频！
          // 绝对不盲目认领未绑定 ID 的旧视频，防止误判导致连续提前提交后续任务！
          if (!isVideoGenerated && boundMediaIds.length > 0) {
            const candidateVideos = targetBatchContainer ? 
              Array.from(targetBatchContainer.querySelectorAll("video")) : 
              Array.from(document.querySelectorAll("flow-video-tile video, video"));

            for (const v of candidateVideos) {
              const src = (typeof v.getAttribute === "function" ? v.getAttribute("src") : null) || v.currentSrc || v.src;
              if (src && !isStaticShowcaseAsset(src)) {
                const vidId = mediaIdFromVideoUrl(src);
                if (vidId && boundMediaIds.includes(vidId)) {
                  console.log(`[Batch] 🎯 DOM 视频匹配到当前任务 boundMediaId=${vidId}: ${src.substring(0, 80)}`);
                  isVideoGenerated = true;
                  targetVideoUrl = src;
                  if (!binding.readyIds.includes(vidId)) binding.readyIds.push(vidId);
                  binding.urls = binding.urls || {};
                  binding.urls[vidId] = src;
                  break;
                }
              }
            }
          }

          // 5. 视频生成就绪后，调度自动下载
          if (isVideoGenerated && targetVideoUrl) {
            if (!downloadTriggered && !(Array.isArray(task.downloaded) && task.downloaded[lIdx])) {
              console.log("[Batch] 🚀 当前任务视频已就绪，发起自动下载:", targetVideoUrl.substring(0, 80));
              const dlOk = await triggerAutoDownload(targetVideoUrl, mediaIdFromVideoUrl(targetVideoUrl));
              console.log("[Batch] triggerAutoDownload 执行结果:", dlOk);
              if (dlOk) {
                downloadTriggered = true;
                updateLineStatus(rIdx, lIdx, "generating", `视频已就绪，已发起下载，正在等待保存文件 (${Math.round(waitedSec)}s)...`);
              }
            }
          } else {
            if (!task.downloaded[lIdx]) {
              const waitHint = boundMediaIds.length > 0 ? 
                `已分配服务端 ID [${boundMediaIds.join(', ')}]，渲染生成中 (${Math.round(waitedSec)}s)...` : 
                `正在生成中，已等待 ${Math.round(waitedSec)}s (完成后将自动下载)...`;
              updateLineStatus(rIdx, lIdx, "generating", waitHint);
            }
          }

          await delay(2000);
          waitedSec = (Date.now() - waitStartTime) / 1000;

          // 4. 下载完成严格校验
          if (task.status[lIdx] === "success" && (Array.isArray(task.downloaded) && task.downloaded[lIdx])) {
            isTaskCompleted = true;
            break;
          }
        }



        if (!isTaskCompleted && !isStopRequested && task.status[lIdx] !== "failed") {
          console.warn(`[Batch] 任务生成等待超时 (${maxWaitSec}s)`);
          updateLineStatus(rIdx, lIdx, "failed", `生成或下载超时 (等待超过 ${maxWaitSec} 秒)`);
        }

        window.currentProcess = null;
        state.activeTasksQueue = [];
        state.taskRecord = {};
        // 清理行内继续的指针，方便下一个任务从 0 行开始跑
        state.currentLineIndex = 0;
        await saveState();

        if (isStopRequested) {
          showToast("用户中断了批量任务！");
          onBatchFinished();
          return;
        }

        // 如果是单任务生成模式，该任务生成并下载完成后立即停止，不等待间隔，不进入下一项
        if (singleRowIndex !== null && typeof singleRowIndex === "number") {
          showToast(`单项任务 #${rIdx + 1} 生成与下载已完成！`);
          onBatchFinished();
          return;
        }

        // 任务下载完成后的批量间隔延时 (严格按照规则设置或当前设定执行停顿，基于绝对时间戳保证失焦/后台准确走完)
        const baseInterval = (task.interval !== undefined && task.interval !== null && !isNaN(Number(task.interval)))
          ? Number(task.interval)
          : (state.settings.interval !== undefined ? Number(state.settings.interval) : 5);
        const intervalSec = Math.max(0, baseInterval);
        const intervalRand = (task.interval !== undefined && task.interval !== null)
          ? 0
          : Math.max(0, Number(state.settings.intervalRandom) || 0);
        const waitTime = Math.round(intervalSec + Math.random() * intervalRand);
        if (waitTime > 0) {
          const targetEndTime = Date.now() + waitTime * 1000;
          console.log(`[Batch] 当前任务已完成，等待间隔延迟: ${waitTime} 秒后进入下一项`);

          while (Date.now() < targetEndTime) {
            if (isStopRequested) break;
            const remainingSec = Math.max(1, Math.round((targetEndTime - Date.now()) / 1000));
            showToast(`当前视频已完成！将在 ${remainingSec} 秒后开始下一个任务...`, 1500);
            await delay(1000);
          }
        } else {
          console.log(`[Batch] 当前任务已完成，间隔设置为 0 秒，立即进入下一项`);
        }

        // 倒计时结束，在流转进入下一项前清理可能残留的遮罩与弹窗
        await cleanupPageOverlays();
      }
    }

    if (singleRowIndex !== null && typeof singleRowIndex === "number") {
      showToast(`单项任务执行已完成！`);
    } else {
      showToast("所有队列任务的批量生成提交已完成！");
    }
    onBatchFinished();
  }

  function stopBatch() {
    isStopRequested = true;
    stopActivityCheck();
    disableTabKeepAlive();
    state.isRunning = false;
    if (alarmTimer) { clearInterval(alarmTimer); alarmTimer = null; }
    saveState();
    showToast("正在停止队列，已提交到 Flow 的生成不会取消...");
  }

  function onBatchFinished() {
    stopActivityCheck();
    disableTabKeepAlive();
    
    state.isRunning = false;
    state.currentIndex = 0;
    state.currentLineIndex = 0;
    state.retryCount = 0;
    
    document.getElementById("btn-start-batch").style.setProperty("display", "inline-flex", "important");
    document.getElementById("btn-stop-batch").style.setProperty("display", "none", "important");
    
    window.currentProcess = null;
    state.activeTasksQueue = [];
    state.taskRecord = {};
    sendToExtension("clearActiveTask", {});
    saveState();
  }

  // ----------------------------------------------------
  // 自动化参数同步：模式、视频类型(帧/素材)、尺寸比例、分辨率、输出数量、时长
  // ----------------------------------------------------
  function durationError(message) {
    const error = new Error(message);
    error.configurationError = true;
    return error;
  }

  function findDurationGroup() {
    const overlay = document.querySelector(".cdk-overlay-pane flow-prompt-box-settings, flow-prompt-box-settings, .settings-content-overlay");
    if (!overlay) return null;
    const groups = Array.from(overlay.querySelectorAll("flow-toggles[aria-label], [role='radiogroup'][aria-label], select[aria-label], flow-toggles"));
    return groups.find(group => /时长|時長|秒数|秒數|长度|長度|duration|length/i.test(group.getAttribute("aria-label") || "")) ||
           groups.find(group => {
             const btns = Array.from(group.querySelectorAll("mat-button-toggle, [role='radio'], option"));
             return btns.length >= 2 && btns.some(b => /^\s*\d+\s*(秒|s|sec|seconds)\s*$/i.test(b.textContent || ""));
           }) || null;
  }

  async function applyDurationSetting(value) {
    const target = normalizeDuration(value);
    if (target == null) return;
    let group;
    for (let attempt = 0; attempt < 10; attempt++) {
      group = findDurationGroup();
      if (group) break;
      if (isStopRequested) throw durationError("任务已停止");
      await delay(200);
    }
    if (!group) {
      const panelOpen = document.querySelector(".cdk-overlay-pane flow-prompt-box-settings, flow-prompt-box-settings, .settings-content-overlay");
      if (panelOpen) {
        console.warn(`[FlowUI] 当前模型设置面板中无时长选项（可能为固定时长模型），跳过 ${target} 秒设置`);
        return;
      }
      throw durationError(`找不到视频时长选项，无法确认 ${target} 秒；请检查当前模型的设置面板`);
    }
    const options = () => Array.from(group.querySelectorAll("mat-button-toggle, [role='radio'], option"));
    const secondsOf = option => {
      try { return normalizeDuration(option.textContent.trim()); } catch (_) { return null; }
    };
    const selected = option => option.selected === true || option.classList.contains("mat-button-toggle-checked") ||
      option.getAttribute("aria-checked") === "true" || option.querySelector("button")?.getAttribute("aria-checked") === "true" ||
      option.querySelector("button")?.getAttribute("aria-pressed") === "true";

    let effectiveTarget = target;
    let option = options().find(item => secondsOf(item) === effectiveTarget);
    if (!option) {
      const availableOpts = options().map(item => ({ item, sec: secondsOf(item) })).filter(x => x.sec != null);
      if (availableOpts.length > 0) {
        availableOpts.sort((a, b) => Math.abs(a.sec - target) - Math.abs(b.sec - target));
        option = availableOpts[0].item;
        effectiveTarget = availableOpts[0].sec;
        console.warn(`[FlowUI] 当前模型不支持 ${target} 秒，已自动匹配最接近的可用时长: ${effectiveTarget} 秒`);
      } else {
        throw durationError(`当前模型不支持 ${target} 秒；可选时长：${options().map(secondsOf).filter(v => v != null).join("、") || "未识别"}`);
      }
    }
    if (!selected(option)) {
      if (group.tagName === "SELECT") {
        group.value = option.value;
        group.dispatchEvent(new Event("change", { bubbles: true }));
      } else {
        const button = option.querySelector("button") || option;
        if (button.disabled || button.getAttribute("aria-disabled") === "true") throw durationError(`${effectiveTarget} 秒选项不可用`);
        button.click();
      }
    }
    for (let attempt = 0; attempt < 10; attempt++) {
      group = findDurationGroup();
      if (group && options().some(item => secondsOf(item) === effectiveTarget && selected(item))) return;
      if (isStopRequested) throw durationError("任务已停止");
      await delay(200);
    }
    throw durationError(`点击后未确认选中 ${effectiveTarget} 秒，已阻止生成`);
  }

  // ----------------------------------------------------
  // 自动切换生成模型 (在设置面板内部操作)
  // ----------------------------------------------------
  const MODEL_DISPLAY_NAMES = {
    "omni_1_1_flash": "Omni 1.1 Flash",
    "veo_3_1_lite": "Veo 3.1 - Lite",
    "veo_3_1_fast": "Veo 3.1 - Fast",
    "veo_3_1_quality": "Veo 3.1 - Quality",
    "veo_3_1_lite_low_priority": "Veo 3.1 - Lite [Lower Priority]",
    "veo_fast": "Veo 3.1 - Fast",
    "veo_2": "Veo 2",
    "VIDEO_REFERENCES": "VIDEO_REFERENCES"
  };

  function isModelNameMatch(candidateText, targetDisplayName, targetModelId) {
    if (!candidateText || !targetDisplayName) return false;
    const candLower = candidateText.toLowerCase();
    const targLower = targetDisplayName.toLowerCase();
    // 严格区分普通版与 [Lower Priority] 低优先级版本
    const candIsLowPrio = /lower\s*priority|low\s*priority|低优先级|低優先/i.test(candLower);
    const targIsLowPrio = targetModelId === "veo_3_1_lite_low_priority" || /lower\s*priority|low\s*priority|低优先级|低優先/i.test(targLower);
    if (candIsLowPrio !== targIsLowPrio) return false;

    const stripTags = (s) => s
      .replace(/\[.*?\]/g, "")
      .replace(/测试版|測試版|beta|arrow_drop_down|check/gi, "")
      .replace(/[\s\-_.]+/g, "")
      .trim();

    const candNorm = stripTags(candLower);
    const targNorm = stripTags(targLower);
    if (!candNorm || !targNorm) return false;
    return candNorm === targNorm || candNorm.includes(targNorm) || targNorm.includes(candNorm);
  }

  // 在设置面板内部切换模型 (overlay = flow-prompt-box-settings 面板元素，兼容简中/繁中/英文)
  async function switchModelInPanel(overlay, targetModelId) {
    const targetDisplayName = MODEL_DISPLAY_NAMES[targetModelId] || targetModelId;
    console.log(`[FlowUI] 🔄 面板内模型切换: 目标="${targetDisplayName}" (ID=${targetModelId})`);

    const modelBtnSelector = 'button[aria-label="选择模型系列"], button[aria-label="選取模型系列"], button[aria-label*="模型"], button[aria-label*="model" i], button.mat-mdc-menu-trigger';

    // 1. 在设置面板内查找模型选择器按钮
    let triggerBtn = overlay.querySelector(modelBtnSelector);
    if (!triggerBtn) {
      // 回退: 通过 .model-select-trigger-content 子元素
      const triggerContent = overlay.querySelector('.model-select-trigger-content');
      triggerBtn = triggerContent?.closest('button');
      if (triggerBtn) console.log("[FlowUI] 通过 .model-select-trigger-content 回退找到模型按钮");
    }
    if (!triggerBtn) {
      // 回退: 在整个页面中查找 (可能在 overlay 外层)
      triggerBtn = document.querySelector('flow-prompt-box-settings ' + modelBtnSelector) ||
                   document.querySelector('button[aria-label="选择模型系列"], button[aria-label="選取模型系列"], button[aria-label*="model family" i]');
      if (!triggerBtn) {
        const triggerContent = document.querySelector('.model-select-trigger-content');
        triggerBtn = triggerContent?.closest('button');
      }
      if (triggerBtn) console.log("[FlowUI] 在页面全局找到模型按钮");
    }

    if (!triggerBtn) {
      console.warn("[FlowUI] ❌ 未找到模型选择按钮，跳过模型切换");
      return false;
    }

    // 2. 读取当前模型名称
    const currentModelSpan = triggerBtn.querySelector('.model-select-trigger-content');
    const currentModelText = (currentModelSpan?.textContent || triggerBtn.textContent || "")
      .replace(/arrow_drop_down/gi, "").trim();
    console.log(`[FlowUI] 当前页面模型: "${currentModelText}"`);

    // 3. 判断是否需要切换
    if (isModelNameMatch(currentModelText, targetDisplayName, targetModelId)) {
      console.log(`[FlowUI] ✅ 当前模型已经是 "${currentModelText}"，无需切换`);
      return false; // 没有切换
    }

    console.log(`[FlowUI] ⚠️ 当前模型 "${currentModelText}" ≠ 目标 "${targetDisplayName}"，正在自动切换...`);

    // 4. 点击触发按钮打开下拉菜单
    console.log("[FlowUI] 点击模型选择器按钮...");
    triggerBtn.click();
    await delay(800);

    // 5. 在下拉菜单中查找目标模型选项
    let targetMenuItem = null;

    // 策略 A: 查找 span.label 文本
    const labelElements = document.querySelectorAll('.cdk-overlay-container span.label, .cdk-overlay-container .item-text .label, .cdk-overlay-container [role="menuitem"] span');
    console.log(`[FlowUI] 下拉菜单中找到 ${labelElements.length} 个 label 元素`);
    for (const label of labelElements) {
      const labelText = (label.textContent || "").trim();
      if (isModelNameMatch(labelText, targetDisplayName, targetModelId)) {
        // 向上查找可点击的按钮
        targetMenuItem = label.closest('button') || label.closest('flow-menu-item')?.querySelector('button') || label.closest('[role="menuitem"]') || label;
        console.log(`[FlowUI] ✅ 找到目标: "${labelText}" -> ${targetMenuItem.tagName}`);
        break;
      }
    }

    // 策略 B: 遍历菜单按钮
    if (!targetMenuItem) {
      const allMenuBtns = document.querySelectorAll('.cdk-overlay-container button, .cdk-overlay-container [role="menuitem"]');
      for (const btn of allMenuBtns) {
        const btnText = (btn.textContent || "").trim();
        if (isModelNameMatch(btnText, targetDisplayName, targetModelId)) {
          targetMenuItem = btn;
          console.log(`[FlowUI] ✅ 策略 B 找到: "${btnText.substring(0, 50)}"`);
          break;
        }
      }
    }

    if (targetMenuItem) {
      console.log(`[FlowUI] 🎯 正在点击目标模型...`);
      targetMenuItem.click();
      await delay(1500); // 等待模型切换后页面/面板更新
      console.log(`[FlowUI] ✅ 模型切换完成!`);
      return true; // 模型已切换
    } else {
      console.warn(`[FlowUI] ❌ 下拉菜单中未找到 "${targetDisplayName}"，关闭菜单`);
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", code: "Escape", bubbles: true }));
      await delay(300);
      return false;
    }
  }

  async function syncPageVideoSettings(settings) {
    const { resolution, aspectRatio, videoModel, footageType, count, duration } = settings;
    const targetCount = count || 1;
    const targetRes = resolution || "VIDEO_RESOLUTION_720P";
    const targetAspect = aspectRatio || "ASPECT_RATIO_9_16";
    const targetFootage = footageType || "VIDEO_FRAMES";

    console.log(`[FlowUI] 开始同步视频设置: 模式=${targetFootage}, 比例=${targetAspect}, 分辨率=${targetRes}, 数量=${targetCount}, 时长=${duration || '默认'}, 模型=${videoModel || '默认'}`);

    // 0-B. 尝试全局 store 兜底设置
    try {
      if (window.promptBoxStore && typeof window.promptBoxStore.setState === "function") {
        window.promptBoxStore.setState({
          videoResolution: targetRes,
          selectedVideoResolution: targetRes,
          resolution: targetRes,
          aspectRatio: targetAspect === "ASPECT_RATIO_9_16" ? "PORTRAIT" : (targetAspect === "ASPECT_RATIO_1_1" ? "SQUARE" : "LANDSCAPE"),
          outputsPerPrompt: targetCount,
          videoModelFamilyId: videoModel || "omni_1_1_flash",
          mode: targetFootage
        });
      }
    } catch (storeErr) {
      console.warn("[FlowUI] promptBoxStore 兜底更新提示:", storeErr);
    }

    const findSettingsTriggerBtn = () =>
      document.querySelector("button.settings-trigger-button") ||
      document.querySelector("div.submit-controls button:not(.generate-icon-button)") ||
      document.querySelector("button[aria-label*='设置'], button[aria-label*='設定'], button[aria-label*='Settings' i]");

    // 1. 定位页面底部的设置按钮 (模型切换后页面可能重新渲染，需要重试)
    let settingsBtn = null;
    for (let retry = 0; retry < 8; retry++) {
      settingsBtn = findSettingsTriggerBtn();
      if (settingsBtn) break;
      console.log(`[FlowUI] 等待设置按钮出现... (${retry + 1}/8)`);
      await delay(500);
    }
    
    if (!settingsBtn) {
      throw durationError("未找到 Flow 设置按钮，无法确认任务秒数");
    }

    // 检查按钮文本摘要是否已经完全符合预期（兼容简中/繁中/英文，如 `x 1` vs `x1`）
    const summaryText = (settingsBtn.textContent || "").toLowerCase();
    const summaryCompact = summaryText.replace(/\s+/g, "");
    const resKey = targetRes.includes("360") ? "360p" : (targetRes.includes("1080") ? "1080p" : "720p");
    const aspectKey = targetAspect.includes("9_16") ? "crop_9_16" : (targetAspect.includes("1_1") ? "crop_1_1" : "crop_16_9");
    const aspectTextKey = targetAspect.includes("9_16") ? "9:16" : (targetAspect.includes("1_1") ? "1:1" : "16:9");
    const countKey = `x${targetCount}`;

    const resMatched = summaryCompact.includes(resKey);
    const aspectMatched = summaryCompact.includes(aspectKey) || summaryCompact.includes(aspectTextKey);
    const countMatched = summaryCompact.includes(countKey);
    const modelMatched = !videoModel || isModelNameMatch(summaryText, MODEL_DISPLAY_NAMES[videoModel] || videoModel, videoModel);
    const footageMatched = targetFootage === "VIDEO_FRAMES"
      ? /(帧|影格|frame|crop_free)/i.test(summaryText)
      : /(素材|原料|ingredient|reference|chrome_extension)/i.test(summaryText);

    // 如果摘要已经完美满足（分辨率、比例、数量、模型、模式全部一致且无强制秒数校验），才跳过设置弹窗
    if (duration == null && resMatched && aspectMatched && countMatched && modelMatched && footageMatched) {
      console.log(`[FlowUI] 当前设置摘要 (${settingsBtn.textContent.trim()}) 已满足要求，无需重复开启设置弹窗`);
      return;
    }

    // 2. 点击设置按钮弹出 CDK Overlay 设置面板 (带重试)
    let overlay = null;
    for (let retry = 0; retry < 3; retry++) {
      console.log(`[FlowUI] 正在点击设置按钮弹出设置面板... (尝试 ${retry + 1}/3)`);
      // 每次重试都重新查找按钮（防止 DOM 被替换）
      const freshBtn = findSettingsTriggerBtn() || settingsBtn;
      freshBtn.click();
      
      // 等待面板出现
      for (let wait = 0; wait < 8; wait++) {
        await delay(400);
        overlay = document.querySelector(".cdk-overlay-pane flow-prompt-box-settings, flow-prompt-box-settings, .settings-content-overlay");
        if (overlay) break;
      }
      if (overlay) break;
      console.warn(`[FlowUI] 第 ${retry + 1} 次点击后设置面板未出现，重试...`);
      await delay(500);
    }
    
    if (!overlay) {
      throw durationError("未打开 Flow 设置面板，无法设置任务秒数");
    }

    // 3. 通用切换助手：支持简中/繁中/英文多语言 aria-label 列表，并自带图标/文字全组扫描兜底
    function setToggle(ariaLabels, matcher) {
      const labelList = Array.isArray(ariaLabels) ? ariaLabels : [ariaLabels];
      let toggleGroup = null;
      for (const lbl of labelList) {
        toggleGroup = overlay.querySelector(`flow-toggles[aria-label="${lbl}"]`) ||
                      overlay.querySelector(`flow-toggles[aria-label*="${lbl}" i]`);
        if (toggleGroup) break;
      }

      // 兜底：若 aria-label 因界面语言未知未命中，扫描面板内所有 flow-toggles 寻找包含匹配项的组
      const candidateGroups = toggleGroup
        ? [toggleGroup]
        : Array.from(overlay.querySelectorAll("flow-toggles, mat-button-toggle-group"));

      for (const grp of candidateGroups) {
        const toggles = grp.querySelectorAll("mat-button-toggle");
        for (const t of toggles) {
          const clone = t.cloneNode(true);
          clone.querySelectorAll("mat-icon").forEach(ic => ic.remove());
          const pureText = (clone.textContent || "").trim();
          const fullText = (t.textContent || "").trim();
          const icon = (t.querySelector("mat-icon")?.textContent || "").trim();
          const isChecked = t.classList.contains("mat-button-toggle-checked") ||
                            t.querySelector("button")?.getAttribute("aria-checked") === "true";

          const isMatch = typeof matcher === "function"
            ? (matcher(pureText, icon, t) || matcher(fullText, icon, t))
            : (pureText.includes(matcher) || fullText.includes(matcher) || icon.includes(matcher));
          if (isMatch) {
            if (!isChecked) {
              const btn = t.querySelector("button.mat-button-toggle-button") || t.querySelector("button") || t;
              console.log(`[FlowUI] 切换设置 [${labelList[0]}] -> ${pureText || icon}`);
              btn.click();
            } else {
              console.log(`[FlowUI] 设置 [${labelList[0]}] 已经是目标状态: ${pureText || icon}`);
            }
            return true;
          }
        }
      }
      console.warn(`[FlowUI] 设置面板内未找到切换组: [${labelList.join(" / ")}]`);
      return false;
    }

    // 3.1 先确保顶层模式是“视频 / 影片 / Video”，这样模型选择器才会显示视频生成模型
    setToggle(["模式", "Mode"], (text, icon) => /(视频|影片|video)/i.test(text) || icon === "videocam");
    await delay(150);

    // 3.2 在设置面板内部自动切换模型 (模型选择器在面板里)
    if (videoModel) {
      const modelSwitched = await switchModelInPanel(overlay, videoModel);
      if (modelSwitched) {
        // 模型切换后设置面板可能已经关闭或重新渲染，需要重新打开
        console.log("[FlowUI] 模型已切换，检查设置面板是否需要重新打开...");
        overlay = document.querySelector(".cdk-overlay-pane flow-prompt-box-settings, flow-prompt-box-settings, .settings-content-overlay");
        if (!overlay) {
          console.log("[FlowUI] 设置面板已关闭，重新打开...");
          for (let retry = 0; retry < 3; retry++) {
            const freshBtn = findSettingsTriggerBtn();
            if (freshBtn) freshBtn.click();
            for (let wait = 0; wait < 8; wait++) {
              await delay(400);
              overlay = document.querySelector(".cdk-overlay-pane flow-prompt-box-settings, flow-prompt-box-settings, .settings-content-overlay");
              if (overlay) break;
            }
            if (overlay) break;
            await delay(500);
          }
          if (!overlay) {
            throw durationError("模型切换后无法重新打开设置面板");
          }
        }
        console.log("[FlowUI] 设置面板已就绪，继续配置其他参数...");
      }
    }

    // (a) 模式: 再次确认切换为“视频 / 影片 / Video”
    setToggle(["模式", "Mode"], (text, icon) => /(视频|影片|video)/i.test(text) || icon === "videocam");
    await delay(150);

    // (b) 视频类型: 切换为“帧 / 影格 / Frames”或“素材 / Ingredients”
    if (targetFootage === "VIDEO_FRAMES") {
      setToggle(["视频类型", "影片類型", "Video type", "Type"], (text, icon) => /(帧|影格|frame)/i.test(text) || icon === "crop_free");
    } else {
      setToggle(["视频类型", "影片類型", "Video type", "Type"], (text, icon) => /(素材|原料|ingredient|reference)/i.test(text) || icon === "chrome_extension");
    }
    await delay(150);

    // (c) 宽高比 / 顯示比例 / Aspect ratio: 切换为“9:16”或“16:9”
    if (targetAspect.includes("9_16")) {
      setToggle(["宽高比", "顯示比例", "長寬比", "Aspect ratio"], (text, icon) => text.includes("9:16") || icon === "crop_9_16");
    } else if (targetAspect.includes("1_1")) {
      setToggle(["宽高比", "顯示比例", "長寬比", "Aspect ratio"], (text, icon) => text.includes("1:1") || icon === "crop_1_1");
    } else {
      setToggle(["宽高比", "顯示比例", "長寬比", "Aspect ratio"], (text, icon) => text.includes("16:9") || icon === "crop_16_9");
    }
    await delay(150);

    // (d) 视频分辨率 / 影片解析度 / Video resolution: 切换为 720p 或 360p
    setToggle(["视频分辨率", "影片解析度", "解析度", "分辨率", "Video resolution", "Resolution"], (text) => text.toLowerCase().includes(resKey));
    await delay(150);

    // (e) 输出数量 / 生成數量 / Outputs: 强制切换为目标数量 (兼容 `x1` 与 `x 1`)
    setToggle(["输出数量", "生成數量", "輸出數量", "Outputs", "Count"], (text) => text.replace(/\s+/g, "").toLowerCase() === `x${targetCount}`);
    await delay(150);

    // 选择时长（若当前模型不支持目标秒数则自动匹配最近可用秒数）
    try {
      await applyDurationSetting(duration);
    } catch (err) {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", code: "Escape", bubbles: true }));
      throw err;
    }

    // 4. 关闭设置面板
    console.log("[FlowUI] 完成设置配置，关闭设置弹窗...");
    try {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", code: "Escape", bubbles: true }));
      await delay(150);
      if (document.querySelector(".settings-content-overlay")) {
        settingsBtn.click();
      }
    } catch (e) {}

    await delay(300);
  }

  // 模拟真实的用户单击操作（仅执行一次完整的 down/up/click 流程，杜绝重复连击）
  function simulateClick(el) {
    if (!el) return;
    try { if (typeof el.focus === "function") el.focus(); } catch (_) {}
    try {
      if (typeof PointerEvent !== "undefined") {
        el.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, cancelable: true, view: window }));
        el.dispatchEvent(new PointerEvent("pointerup", { bubbles: true, cancelable: true, view: window }));
      }
    } catch (_) {}
    // 关键：严格只触发一次真实的 click，避免多次提交！
    if (typeof el.click === "function") {
      el.click();
    } else {
      el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, view: window }));
    }
  }

  // 安全派发鼠标/指针事件（避免 click 事件被二次重复触发）
  function safeDispatchMouse(el, type) {
    if (!el) return;
    if (type === "click") {
      simulateClick(el);
      return;
    }
    try {
      if (typeof PointerEvent !== "undefined" && type.startsWith("pointer")) {
        el.dispatchEvent(new PointerEvent(type, { bubbles: true, cancelable: true, view: window }));
      } else if (typeof MouseEvent !== "undefined") {
        el.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, view: window }));
      }
    } catch (_) {}
  }

  // ----------------------------------------------------
  // 自动化关联素材原料：首帧注入 (帧模式) 或素材模式
  // ----------------------------------------------------
  async function attachImageToPage(image, footageType) {
    if (!image) return;
    const imgName = image.displayName || "";
    const imgSrc = image.src || "";
    const imgKey = image.primaryMediaKey || image.id || "";
    const isFrameMode = footageType === "VIDEO_FRAMES";

    console.log(`[FlowUI] 正在关联素材: Name="${imgName}", Key="${imgKey}", Mode="${footageType}"`);

    // 0. 尝试全局 store 注入兜底 (兼容 Flow 早先架构)
    try {
      if (window.promptBoxStore && typeof window.promptBoxStore.getState === "function") {
        const store = window.promptBoxStore.getState();
        if (store.actions && typeof store.actions.addImageIngredient === "function") {
          console.log("[FlowUI] 通过 promptBoxStore.addImageIngredient 注入素材原料");
          store.actions.addImageIngredient({
            imageId: imgKey || imgName,
            preferredIngredientType: isFrameMode ? "FIRST_FRAME" : "REFERENCE",
            source: "PLUS_BUTTON"
          });
          await delay(300);
          return;
        }
      }
    } catch (storeErr) {
      console.warn("[FlowUI] promptBoxStore.addImageIngredient 失败:", storeErr);
    }

    // 1. 核心通道：通过 flow-ingredient-bar 的“开始”帧槽位注入 (帧模式)
    const ingredientBar = document.querySelector("flow-ingredient-bar.prompt-ingredient-bar, .prompt-ingredient-bar, flow-ingredient-bar");
    if (ingredientBar) {
      const startTrigger = ingredientBar.querySelector(".frame-trigger:first-of-type, .frame-trigger");
      if (startTrigger) {
        // 如果首帧已有内容且匹配当前图片，无需重复添加
        const triggerImg = startTrigger.querySelector("img");
        const triggerTitle = extractTileDisplayName(startTrigger, triggerImg);
        const triggerText = startTrigger.textContent || "";
        if (imgName && (isImageNameMatch(imgName, triggerTitle) || isImageNameMatch(imgName, triggerText))) {
          console.log("[FlowUI] 首帧槽位中已存在匹配图片，无需重复注入:", imgName);
          return;
        }

        // 点击“开始”按钮（button.empty-chip 或 button）打开媒体选择面板
        const startBtn = startTrigger.querySelector("button.empty-chip") || startTrigger.querySelector("button");
        if (startBtn) {
          console.log("[FlowUI] 点击首帧触发器按钮 [开始] 弹出媒体选择面板...");
          simulateClick(startBtn);

          // 轮询等待媒体弹窗展开 (最多等待 3 秒)
          let overlayPanel = null;
          for (let w = 0; w < 20; w++) {
            await delay(150);
            const panels = Array.from(document.querySelectorAll(
              ".cdk-overlay-pane:not(:empty), .cdk-overlay-container .cdk-overlay-pane, [role='dialog'], [role='menu'], mat-dialog-container"
            )).filter(p => p.offsetWidth > 0 && p.offsetHeight > 0);
            if (panels.length) {
              overlayPanel = panels[panels.length - 1];
              const items = overlayPanel.querySelectorAll("flow-grid-tile-container, flow-image-tile, flow-tile, flow-media-tile, button:has(img), img");
              if (items.length > 0) break;
            }
          }

          if (overlayPanel) {
            console.log("[FlowUI] 成功检测到素材选择弹层面板，开始匹配素材...");

            // 在弹层中查找匹配的图片素材卡片
            const candidateItems = Array.from(overlayPanel.querySelectorAll(
              "flow-grid-tile-container, flow-image-tile, flow-tile, flow-media-tile, " +
              "[data-tile-id], [data-media-id], .media-item, [role='option'], mat-option, " +
              ".tile-row > div, button:has(img), div:has(> img)"
            ));

            let matchedCard = null;
            for (const item of candidateItems) {
              const itemImg = item.querySelector("img");
              const itemDisplayName = extractTileDisplayName(item, itemImg);
              const itemTitle = item.getAttribute("title") || item.querySelector("[title]")?.getAttribute("title") || "";
              const itemAlt = itemImg?.getAttribute("alt") || "";
              const itemAria = item.getAttribute("aria-label") || "";
              const itemText = item.textContent || "";
              const itemId = itemImg?.dataset?.mediaId || item.dataset?.mediaId || item.dataset?.tileId || "";

              if (imgKey && itemId && (imgKey === itemId || itemId.includes(imgKey) || imgKey.includes(itemId))) {
                matchedCard = item;
                break;
              }
              if (imgName && (isImageNameMatch(imgName, itemDisplayName) || isImageNameMatch(imgName, itemTitle) || isImageNameMatch(imgName, itemAlt) || isImageNameMatch(imgName, itemAria) || isImageNameMatch(imgName, itemText))) {
                matchedCard = item;
                break;
              }
            }

            // 如果名字未精确匹配，尝试在所有带 img 的卡片中寻找文件名子串
            if (!matchedCard) {
              const allImgTiles = Array.from(overlayPanel.querySelectorAll("flow-grid-tile-container, flow-image-tile, button:has(img), div:has(> img)"));
              for (const tile of allImgTiles) {
                const tName = extractTileDisplayName(tile, tile.querySelector("img"));
                if (imgName && tName && isImageNameMatch(imgName, tName)) {
                  matchedCard = tile;
                  break;
                }
              }
            }

            // 如果仍未匹配，且弹窗中只有少量图片，兜底选取第一张图片素材
            if (!matchedCard && candidateItems.length > 0) {
              const firstTile = overlayPanel.querySelector("flow-grid-tile-container:has(img), flow-image-tile, button:has(img)");
              if (firstTile && candidateItems.length <= 2) {
                console.log("[FlowUI] 弹窗中候选较少，选用第一张素材:", firstTile);
                matchedCard = firstTile;
              }
            }

            if (matchedCard) {
              console.log(`[FlowUI] 🎯 在首帧媒体面板中匹配到素材 [${imgName}]，触发选中点击！`);
              const clickTarget = matchedCard.querySelector("button, img, .container") || matchedCard;
              simulateClick(clickTarget);

              await delay(400);

              // 关键！自动检测并点击弹层中的“确认”、“确定”、“选择”、“添加”、“完成”按钮（彻底解放用户手动点击！）
              const allButtons = Array.from(document.querySelectorAll(
                ".cdk-overlay-container button, mat-dialog-actions button, .mat-mdc-dialog-actions button, .cdk-overlay-pane button"
              )).filter(btn => {
                if (btn.disabled || btn.getAttribute("aria-disabled") === "true") return false;
                const t = (btn.textContent || "").trim();
                const aria = (btn.getAttribute("aria-label") || "").trim();
                if (/^(取消|关闭|關閉|Cancel|Close|Dismiss)$/i.test(t) || /^(取消|关闭|關閉|Cancel|Close|Dismiss)$/i.test(aria)) return false;
                if (/(确认|确定|確認|確定|选择|選取|選擇|添加|新增|完成|使用|插入|首帧|初始影格|Confirm|Select|Add|Done|OK|Apply|Insert)/i.test(t) ||
                    /(确认|确定|確認|確定|选择|選取|選擇|添加|新增|完成|使用|插入|首帧|初始影格|Confirm|Select|Add|Done|OK|Apply|Insert)/i.test(aria)) return true;
                if (btn.closest("mat-dialog-actions, .mat-mdc-dialog-actions") && (btn.classList.contains("primary") || btn.classList.contains("flow-button-primary") || btn.classList.contains("mat-mdc-unelevated-button") || btn.classList.contains("mat-primary"))) return true;
                return false;
              });

              if (allButtons.length > 0) {
                const actionBtn = allButtons.find(b => /(确认|确定|確認|確定|选择|選取|選擇|添加|新增|完成|使用|首帧|初始影格|Confirm|Select|Add|Done|OK|Apply)/i.test((b.textContent || "") + (b.getAttribute("aria-label") || ""))) || allButtons[allButtons.length - 1];
                console.log(`[FlowUI] 🎯 自动点击媒体选择弹窗确认按钮: "${(actionBtn.textContent || actionBtn.getAttribute('aria-label') || '').trim()}"`);
                simulateClick(actionBtn);
                await delay(500);
              }

              await delay(300);
              if (verifyImageAttached(image, footageType)) {
                console.log("[FlowUI] ✅ 首帧素材挂载成功！");
                return;
              }
            }

            // 如果弹窗仍未关闭，按 Escape 关闭弹层
            const stillOpen = !!document.querySelector(".cdk-overlay-pane:not(:empty) [role='dialog'], mat-dialog-container");
            if (stillOpen) {
              document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", code: "Escape", bubbles: true }));
              await delay(250);
            }
          }
        }
      }
    }

    // 2. 备选通道：输入框左下角加号菜单 (flow-add-menu)
    const addMenuBtn = document.querySelector("flow-add-menu button.add-menu-trigger, flow-add-menu button, button.add-menu-trigger, button.add-ingredient-button");
    if (addMenuBtn) {
      console.log("[FlowUI] 尝试点击输入框左下角加号菜单添加素材...");
      simulateClick(addMenuBtn);
      await delay(350);

      const menuPanels = Array.from(document.querySelectorAll(".cdk-overlay-pane, .flow-add-menu-dropdown-panel, .mat-mdc-menu-panel, [role='menu']"));
      for (const panel of menuPanels) {
        const options = Array.from(panel.querySelectorAll("button, [role='menuitem'], [role='option'], .flow-add-menu-dropdown-option-text, span"));
        let clickedOpt = false;
        for (const opt of options) {
          const optText = opt.textContent || "";
          if (imgName && isImageNameMatch(imgName, optText)) {
            console.log(`[FlowUI] 在素材菜单中找到匹配素材: ${optText.trim()}，点击添加`);
            simulateClick(opt);
            clickedOpt = true;
            await delay(300);
            break;
          }
        }
        if (clickedOpt) {
          await delay(300);
          return;
        }
      }
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", code: "Escape", bubbles: true }));
      await delay(200);
    }

    // 3. 备选策略：Base64 图片文件拖拽/粘贴注入
    if (imgSrc && imgSrc.startsWith("data:image/")) {
      try {
        console.log("[FlowUI] 尝试通过原生 Clipboard/Paste 事件注入图片 File...");
        const targetEditor = document.querySelector(".prompt-ingredient-bar .frame-trigger:first-of-type") ||
                             document.querySelector("flow-rich-text-editor div.ProseMirror") || 
                             document.querySelector("div.ProseMirror[contenteditable='true']");
        if (targetEditor) {
          const byteString = atob(imgSrc.split(",")[1]);
          const mimeString = imgSrc.split(",")[0].split(":")[1].split(";")[0];
          const ab = new ArrayBuffer(byteString.length);
          const ia = new Uint8Array(ab);
          for (let i = 0; i < byteString.length; i++) {
            ia[i] = byteString.charCodeAt(i);
          }
          const blob = new Blob([ab], { type: mimeString });
          const file = new File([blob], imgName || "ingredient.png", { type: mimeString });

          const dt = new DataTransfer();
          dt.items.add(file);

          const dropEvent = new DragEvent("drop", { bubbles: true, cancelable: true, dataTransfer: dt });
          targetEditor.dispatchEvent(dropEvent);

          const pasteEvent = new ClipboardEvent("paste", { bubbles: true, cancelable: true, clipboardData: dt });
          targetEditor.dispatchEvent(pasteEvent);
          console.log("[FlowUI] 已向目标区域派发 File 注入事件");
          await delay(400);
        }
      } catch (fileErr) {
        console.warn("[FlowUI] File drop/paste 注入异常:", fileErr);
      }
    }
  }

  // 校验当前页面输入区域是否已成功挂载所要求的素材图片
  function verifyImageAttached(image, footageType) {
    if (!image || (!image.displayName && !image.src && !image.primaryMediaKey)) {
      return true; // 未指定图片（纯文本生成任务），直接放行
    }

    const isFrameMode = footageType === "VIDEO_FRAMES";

    // 1. 优先检查 flow.promptBoxStore 全局状态（如可用）
    try {
      if (window.promptBoxStore && typeof window.promptBoxStore.getState === "function") {
        const store = window.promptBoxStore.getState();
        if (store) {
          const ingredients = store.ingredients || store.imageIngredients || store.frames || [];
          if (Array.isArray(ingredients) && ingredients.length > 0) {
            return true;
          }
          if (store.startFrame || store.firstFrame || (store.frames && (store.frames.start || store.frames.first))) {
            return true;
          }
        }
      }
    } catch (e) {
      console.warn("[FlowUI] 检查 promptBoxStore 异常:", e);
    }

    // 2. 检查 DOM: flow-ingredient-bar / .prompt-ingredient-bar
    const ingredientBar = document.querySelector("flow-ingredient-bar.prompt-ingredient-bar, .prompt-ingredient-bar, flow-ingredient-bar");
    if (ingredientBar) {
      // 帧模式下检查首帧槽位 (.frame-trigger)
      if (isFrameMode) {
        const startTrigger = ingredientBar.querySelector(".frame-trigger:first-of-type, .frame-trigger");
        if (startTrigger) {
          const emptyBtn = startTrigger.querySelector("button.empty-chip");
          // 如果首帧中存在 img 标签或已不是 empty-chip，或者内容包含图片名称，则认为已挂载
          const hasImg = !!startTrigger.querySelector("img, flow-tile, flow-media-tile, [role='img']");
          const hasNonEmptyButton = !!startTrigger.querySelector("button:not(.empty-chip)");
          const triggerTitle = extractTileDisplayName(startTrigger, startTrigger.querySelector("img"));
          const triggerText = startTrigger.textContent || "";
          const matchesName = image.displayName && (isImageNameMatch(image.displayName, triggerTitle) || isImageNameMatch(image.displayName, triggerText));

          if (hasImg || hasNonEmptyButton || (!emptyBtn && triggerText.trim() !== "" && !triggerText.includes("开始") && !triggerText.includes("開始") && !/start/i.test(triggerText)) || matchesName) {
            return true;
          }
          // 如果首帧明确包含 empty-chip，且没有缩略图，则说明首帧尚未挂上
          if (emptyBtn) {
            return false;
          }
        }
      }

      // 素材模式或通用检查：查看是否存在素材芯片、缩略图或移除按钮
      const hasChipOrImg = !!ingredientBar.querySelector(
        "img, flow-ingredient-chip, .ingredient-chip, mat-chip, .chip-container, button[aria-label*='移除'], button[aria-label*='删除'], button[aria-label*='刪除'], button[aria-label*='Remove' i], button[aria-label*='Clear' i], .clear-button"
      );
      if (hasChipOrImg) return true;

      const barTitle = extractTileDisplayName(ingredientBar, ingredientBar.querySelector("img"));
      const barText = ingredientBar.textContent || "";
      if (image.displayName && (isImageNameMatch(image.displayName, barTitle) || isImageNameMatch(image.displayName, barText))) {
        return true;
      }
    }

    // 3. 检查富文本编辑器 (flow-rich-text-editor) 是否内嵌素材胶囊
    const editorChips = document.querySelectorAll("flow-rich-text-editor [data-chip-type], flow-rich-text-editor .ingredient-chip, flow-rich-text-editor img");
    if (editorChips.length > 0) {
      return true;
    }

    return false;
  }

  // 注入提示词至 ProseMirror 并触发 Angular 提交
  async function submitTaskToPage(params) {
    const { image, lineText, presetBefore, presetAfter, footageType, count, duration, rowIndex, lineIndex, resolution, aspectRatio, videoModel } = params;
    
    // 0. 同步视频尺寸比例、分辨率、视频类型(帧/素材)、输出数量与生成模型
    const targetRes = resolution || state.settings.resolution || "VIDEO_RESOLUTION_720P";
    const targetAspect = aspectRatio || state.settings.aspectRatio || "ASPECT_RATIO_9_16";
    const targetModel = (videoModel && videoModel !== "VIDEO_REFERENCES" ? videoModel : null) || state.settings.videoModel || "omni_1_1_flash";
    const targetFootage = footageType || state.settings.footageType || "VIDEO_FRAMES";
    const targetCount = count || state.settings.defaultCount || 1;

    // 关键修复 1：先同步页面设置（切换到目标模式如“帧”模式），确保 flow-ingredient-bar 显示出首帧槽位，且设置切换不会清除刚挂载的图片！
    try {
      await syncPageVideoSettings({
        resolution: targetRes,
        aspectRatio: targetAspect,
        videoModel: targetModel,
        footageType: targetFootage,
        count: targetCount,
        duration: duration
      });
    } catch (settErr) {
      throw settErr;
    }

    // 提交前清理历史弹窗与遮罩，确保输入框与按钮处于可交互视口
    await cleanupPageOverlays();

    // 关键修复 2：在目标模式设置好后，再挂载参考图片/首帧素材原料！
    if (image && (image.displayName || image.src || image.primaryMediaKey)) {
      try {
        await attachImageToPage(image, targetFootage);
      } catch (imgErr) {
        console.warn("[FlowUI] 注入图片原料异常 (继续执行):", imgErr);
      }
    }

    // 3. 定位 ProseMirror 输入框
    let editor = document.querySelector("flow-rich-text-editor div.ProseMirror") || 
                 document.querySelector("div.ProseMirror[contenteditable='true']");
    if (!editor) {
      for (let i = 0; i < 10; i++) {
        await delay(300);
        editor = document.querySelector("flow-rich-text-editor div.ProseMirror") || 
                 document.querySelector("div.ProseMirror[contenteditable='true']");
        if (editor) break;
      }
    }

    if (!editor) {
      throw new Error("页面上未找到提示词输入框 (flow-rich-text-editor ProseMirror)");
    }

    // 4. 拼装拼接后的提示词
    const finalPrompt = `${presetBefore || ""}
${lineText || ""}
${presetAfter || ""}`.trim();
    params.finalPrompt = finalPrompt;
    console.log(`[FlowUI] 正在填入提示词 (第 ${rowIndex + 1} 个任务, 子行 ${lineIndex + 1}): "${finalPrompt.substring(0, 60)}..."`);

    // 5. 注入文本到 ProseMirror 编辑器 (支持多行段落，绝不让 ProseMirror 报错)
    try {
      editor.focus();
    } catch (e) {}

    let textInjected = false;

    // 策略 A: ProseMirror View 原生多行段落事务注入
    if (editor.pmViewDesc && editor.pmViewDesc.view) {
      try {
        const view = editor.pmViewDesc.view;
        const schema = view.state.schema;
        const lines = finalPrompt.split("\n");
        const pType = schema.nodes.paragraph;
        const paragraphs = lines.map(line => {
          return line ? pType.create(null, schema.text(line)) : pType.create();
        });
        const docNode = schema.nodes.doc.create(null, paragraphs);
        const tr = view.state.tr.replaceWith(0, view.state.doc.content.size, docNode.content);
        view.dispatch(tr);
        textInjected = true;
        console.log("[FlowUI] 已通过 ProseMirror EditorView.dispatch 原生注入多行段落文本");
      } catch (pmErr) {
        console.warn("[FlowUI] ProseMirror View dispatch 异常，转入 DOM 注入:", pmErr);
      }
    }

    // 策略 B: DOM 原生选中与 execCommand
    if (!textInjected) {
      try {
        const sel = window.getSelection();
        const range = document.createRange();
        range.selectNodeContents(editor);
        sel.removeAllRanges();
        sel.addRange(range);
        textInjected = document.execCommand("insertText", false, finalPrompt);
      } catch (domErr) {
        console.warn("[FlowUI] execCommand 注入失败:", domErr);
      }
    }

    // 策略 C: 结构化段落替换
    if (!textInjected || editor.textContent.trim() !== finalPrompt) {
      if (typeof editor.replaceChildren === "function") {
        const paragraphs = finalPrompt.split("\n").map(l => {
          const p = document.createElement("p");
          p.textContent = l || "";
          return p;
        });
        editor.replaceChildren(...paragraphs);
      } else if (typeof editor.appendChild === "function") {
        editor.innerHTML = "";
        const lines = finalPrompt.split("\n");
        lines.forEach(l => {
          const p = document.createElement("p");
          p.textContent = l || "";
          editor.appendChild(p);
        });
      } else {
        editor.textContent = finalPrompt;
      }
    }

    // 派发全面的事件确保 Angular 表单状态更新为 valid
    editor.dispatchEvent(new InputEvent("input", { bubbles: true, cancelable: true, inputType: "insertFromPaste", data: finalPrompt }));
    editor.dispatchEvent(new Event("input", { bubbles: true }));
    editor.dispatchEvent(new Event("change", { bubbles: true }));
    window.promptBoxStore?.getState?.().actions?.setText?.(finalPrompt);
    window.promptBoxStore?.getState?.().actions?.setPrompt?.(finalPrompt);

    // 6. 提交前图片挂载状态二次复核与补救
    if (image && (image.displayName || image.src || image.primaryMediaKey)) {
      let isMounted = verifyImageAttached(image, targetFootage);
      if (!isMounted) {
        console.warn(`[FlowUI] ⚠️ 提交前首次检查发现素材 [${image.displayName || "图片"}] 尚未挂载，等待后复检...`);
        await delay(400);
        isMounted = verifyImageAttached(image, targetFootage);
      }
      if (!isMounted) {
        console.warn(`[FlowUI] ⚠️ 正在执行二次挂载素材重试...`);
        await attachImageToPage(image, targetFootage);
        await delay(600);
        isMounted = verifyImageAttached(image, targetFootage);
      }
      if (isMounted) {
        console.log(`[FlowUI] ✅ 提交前图片挂载校验通过: [${image.displayName || "素材图片"}] 已正确挂载到输入框！`);
      } else {
        console.warn(`[FlowUI] ⚠️ 挂载检测未直接捕获到芯片，继续执行发送...`);
      }
    }

    // 7. 查找生成按钮并确保可点击发送
    const findButton = () => document.querySelector(
      "flow-generate-icon-button button, button.generate-icon-button, button[aria-label*='生成'], button[aria-label*='產生'], button[aria-label*='开始'], button[aria-label*='開始'], button[aria-label*='建立'], button[aria-label*='Generate' i], button[aria-label*='Create' i]"
    );
    let button;
    for (let i = 0; i < 40; i++) {
      if (isStopRequested) throw new Error("用户已停止任务");
      button = findButton();
      if (!state.isSuspended && button && !button.disabled && !button.hasAttribute("disabled") && button.getAttribute("aria-disabled") !== "true") break;
      // 若按钮仍 disabled，尝试重新派发输入事件激活
      if (button && (button.disabled || button.getAttribute("aria-disabled") === "true")) {
        editor.dispatchEvent(new Event("input", { bubbles: true }));
        editor.dispatchEvent(new Event("change", { bubbles: true }));
      }
      button = null;
      await delay(500);
    }
    if (!button) {
      button = findButton();
      if (button) {
        console.warn("[FlowUI] ⚠️ 生成按钮超时未就绪，强制解除 disabled 限制触发点击");
        button.removeAttribute("disabled");
        button.disabled = false;
        button.setAttribute("aria-disabled", "false");
      } else {
        throw new Error("Flow 生成按钮尚未就绪，请检查页面提示");
      }
    }

    await sendToExtension("setActiveTask", {
      download_path: resolveDownloadPath(params.download_path, params),
      rowIndex, lineIndex, projectId: getStorageKey()
    });
    if (isStopRequested) throw new Error("用户已停止任务");
    params.submissionId = crypto.randomUUID();
    const task = state.tasks[rowIndex];
    task.taskId = task.taskId || crypto.randomUUID();
    task.mediaBindings = task.mediaBindings || [];
    task.downloadIds = task.downloadIds || [];
    task.downloadIds[lineIndex] = null;
    task.videoUrls = task.videoUrls || [];
    task.videoUrls[lineIndex] = null;
    task.mediaBindings[lineIndex] = {
      schema: 2, submissionId: params.submissionId, taskId: task.taskId,
      mediaIds: [], readyIds: [], downloadPath: resolveDownloadPath(params.download_path, params)
    };

    await saveState();
    if (isStopRequested) throw new Error("用户已停止任务");
    window.currentProcess = params;
    state.activeTasksQueue = [params];

    console.log("[FlowUI] 🚀 正在触发生成按钮点击发送 (严格单次原生单击):", button);
    simulateClick(button);
    await delay(500);
  }

  function getProjectTiles() {
    return Array.from(document.querySelectorAll("flow-grid-tile-container:has(flow-video-tile video)"));
  }

  function isFlowCurrentlyGenerating() {
    return !!document.querySelector("flow-generate-icon-button mat-spinner, flow-generate-icon-button .mat-mdc-progress-spinner");
  }


  function resolveDownloadPath(downloadPath, processInfo = {}) {
    if (typeof downloadPath === "string" && downloadPath.trim()) {
      const parts = downloadPath.trim().replace(/\\/g, "/").replace(/^[a-zA-Z]:\//, "").split("/").filter(Boolean);
      const filename = sanitizePathName(parts.pop());
      const downloadsIndex = parts.indexOf("downloads");
      const folder = downloadsIndex > 0 ? parts[downloadsIndex - 1] : parts[parts.length - 1];
      return `Flow/${sanitizePathName(folder || getProjectName())}/${filename}`;
    }
    const name = sanitizePathName((processInfo.image?.displayName || `task_${(processInfo.rowIndex || 0) + 1}`).replace(/\.\w*$/, ""));
    return `Flow/${sanitizePathName(getProjectName())}/${name}-${(processInfo.lineIndex || 0) + 1}.mp4`;
  }

  function isStaticShowcaseAsset(url) {
    return !url || /\/website\/flow\/|\/flow_camera\/|\/showcase\/|gstatic\.com|recaptcha|(?:left|right|center|high)\.mp4/i.test(url);
  }

  function videoIdentity(url) {
    try {
      const parsed = new URL(url);
      if (parsed.hostname === "flow-content.google" && parsed.pathname.startsWith("/video/")) return parsed.origin + parsed.pathname;
      if (parsed.hostname === "flow.google.com" && parsed.pathname.startsWith("/asb/")) return parsed.origin + parsed.pathname;
    } catch (_) {}
    return url;
  }

  function mediaIdFromVideoUrl(value) {
    try {
      const url = new URL(value);
      if (url.hostname === "flow-content.google") return url.pathname.match(/^\/video\/([a-zA-Z0-9_-]+)$/)?.[1] || null;
      if (url.hostname === "flow.google.com" && url.pathname.startsWith("/asb/")) {
        return url.pathname.match(/^\/asb\/([a-zA-Z0-9_-]+)/)?.[1] || null;
      }
      if (url.hostname === "labs.google" && url.pathname === "/fx/api/trpc/media.getMediaUrlRedirect") {
        const name = url.searchParams.get("name") || "";
        return name.match(/(?:^|\/)media\/([a-zA-Z0-9_-]+)$/)?.[1] || (/^[a-zA-Z0-9_-]+$/.test(name) ? name : null);
      }
    } catch (_) {}
    return null;
  }

  function wasVideoSeen(url) {
    const identity = videoIdentity(url);
    return Array.from(downloadedUrlsSet).some(seen => videoIdentity(seen) === identity);
  }

  function findMediaBinding(mediaId) {
    if (!mediaId) return null;
    for (let rowIndex = 0; rowIndex < state.tasks.length; rowIndex++) {
      const task = state.tasks[rowIndex];
      for (let lineIndex = 0; lineIndex < (task.mediaBindings || []).length; lineIndex++) {
        const binding = task.mediaBindings[lineIndex];
        if (binding?.schema === 2 && binding.mediaIds.includes(mediaId)) return { task, binding, rowIndex, lineIndex };
      }
    }
    return null;
  }

  // 定位属于当前任务行的批次容器 (基于 mediaId 强绑定与提示词特征双向匹配，绝不盲目回退)
  function findCurrentBatchContainer(activeTask, lineIndex) {
    const activeProcess = window.currentProcess;
    const binding = activeTask?.mediaBindings?.[lineIndex];
    const boundIds = binding?.mediaIds || [];
    const containers = Array.from(document.querySelectorAll(".batch-container, .virtual-item-container"));
    if (!containers.length) return null;

    // 优先策略 1: 如果容器内的 video 包含当前任务绑定的 mediaId，100% 确认为本任务容器！
    if (boundIds.length > 0) {
      for (const container of containers) {
        const videos = Array.from(container.querySelectorAll("video"));
        for (const v of videos) {
          const src = (typeof v.getAttribute === "function" ? v.getAttribute("src") : null) || v.currentSrc || v.src;
          const vId = mediaIdFromVideoUrl(src);
          if (vId && boundIds.includes(vId)) {
            console.log(`[FlowUI] 🎯 [findCurrentBatchContainer] 根据 mediaId (${vId}) 精准锁定当前任务批次容器`);
            return container;
          }
        }
      }
    }

    // 优先策略 2: 提示词专属特征比对 (中段与结尾关键词比对，防止前缀模板词导致误匹配旧批次)
    const targetPrompt = (activeProcess?.finalPrompt || activeProcess?.lineText || activeTask?.lines?.[lineIndex] || "").trim();
    if (targetPrompt) {
      const cleanTarget = targetPrompt.replace(/\s+/g, "");
      const midPoint = Math.floor(cleanTarget.length / 2);
      const midSnippet = cleanTarget.substring(Math.max(0, midPoint - 15), Math.min(cleanTarget.length, midPoint + 15));
      const endSnippet = cleanTarget.slice(-25);

      for (const container of containers) {
        const promptEl = container.querySelector(".prompt-text, flow-expandable-prompt");
        const domText = (promptEl ? (promptEl.innerText || promptEl.textContent || "") : "").replace(/\s+/g, "");
        if (domText) {
          const isFullMatch = domText.includes(cleanTarget) || cleanTarget.includes(domText);
          const isSnippetMatch = (midSnippet && domText.includes(midSnippet)) || (endSnippet && domText.includes(endSnippet));
          if (isFullMatch || isSnippetMatch) {
            console.log("[FlowUI] 🎯 [findCurrentBatchContainer] 根据提示词特征精准锁定当前任务批次容器");
            return container;
          }
        }
      }
    }

    // 严禁盲目返回 containers[0]，若当前任务的新批次尚未生成，必须返回 null 继续等待！
    return null;
  }

  async function triggerDownloadFromNewestTile() {
    console.log("[FlowUI] 🔍 triggerDownloadFromNewestTile 开始扫描当前任务批次 video 元素...");
    const activeTask = state.tasks[state.currentIndex];
    const targetBatchContainer = findCurrentBatchContainer(activeTask, state.currentLineIndex);

    const targetTiles = targetBatchContainer ? 
      Array.from(targetBatchContainer.querySelectorAll("flow-video-tile")) : 
      Array.from(document.querySelectorAll("flow-video-tile"));
    if (targetTiles.length > 0) {
      triggerTileHover(targetTiles[0]);
      await delay(300);
    }
    const videoList = targetBatchContainer ? 
      Array.from(targetBatchContainer.querySelectorAll("video")) : 
      Array.from(document.querySelectorAll("flow-video-tile video, video"));
    console.log(`[FlowUI] triggerDownloadFromNewestTile 找到 ${videoList.length} 个 video 元素`);
    for (const video of videoList) {
      const src = (typeof video.getAttribute === "function" ? video.getAttribute("src") : null) || video.currentSrc || video.src;
      console.log(`[FlowUI] 尝试对 video 触发下载: src=${(src || '').substring(0, 80)}`);
      if (src && await triggerAutoDownload(src)) return true;
    }

    // 备用通道: 点击当前批次专属的原生批量下载按钮
    const dlSelector = "button[aria-label='批量下载'], button[aria-label='批次下載'], button[aria-label*='下载'], button[aria-label*='下載'], button[aria-label*='Download' i]";
    const newestDownloadBtn = targetBatchContainer ? 
      targetBatchContainer.querySelector(dlSelector) : 
      document.querySelector(`.batch-container ${dlSelector}, flow-batch-info ${dlSelector}, ${dlSelector}`);
    if (newestDownloadBtn && !newestDownloadBtn.disabled) {
      console.log("[FlowUI] 备用通道: 尝试点击当前批次专属的 [批量下载] 按钮...");
      newestDownloadBtn.click();
      return true;
    }
    return false;
  }

  async function retrySavedVideo(task, rowIndex, lineIndex) {
    const binding = task.mediaBindings?.[lineIndex];
    console.log(`[FlowUI] [retrySavedVideo] 开始重试任务行: Row=${rowIndex}, Line=${lineIndex}, binding=`, binding);
    if (binding?.schema !== 2 || !binding.mediaIds.length) {
      console.warn(`[FlowUI] [retrySavedVideo] 无法重试: binding.schema=${binding?.schema}, mediaIds.length=${binding?.mediaIds?.length || 0}`);
      updateLineStatus(rowIndex, lineIndex, "failed", "未取得服务端媒体 ID，已禁止自动下载和重新生成。需要检查生成接口响应。");
      isStopRequested = true;
      return false;
    }
    binding.downloading = false;
    if (task.downloadIds?.[lineIndex]) {
      const existing = await sendToExtension("getDownloadStatus", { downloadId: task.downloadIds[lineIndex] });
      console.log(`[FlowUI] [retrySavedVideo] 检查已有 downloadId=${task.downloadIds[lineIndex]} 状态:`, existing);
      if (existing?.state === "complete") {
        task.downloaded[lineIndex] = true;
        updateLineStatus(rowIndex, lineIndex, "success", "对应视频下载已完成");
        return true;
      }
      if (existing?.state === "in_progress") {
        updateLineStatus(rowIndex, lineIndex, "generating", "等待对应 ID 的下载完成...");
        return true;
      }
      task.downloadIds[lineIndex] = null;
    }
    const mediaId = binding.readyIds[0];
    let url = binding.urls?.[mediaId];
    console.log(`[FlowUI] [retrySavedVideo] readyMediaId=${mediaId}, boundUrl=${url}`);
    if (!mediaId || !url) {
      console.warn(`[FlowUI] [retrySavedVideo] 缺少就绪 mediaId 或 url (mediaId=${mediaId}, url=${url})，等待成功状态`);
      updateLineStatus(rowIndex, lineIndex, "generating", "已取得媒体 ID，等待该 ID 的成功状态...");
      return true;
    }
    for (const video of document.querySelectorAll("flow-video-tile video")) {
      const candidate = video.getAttribute("src") || video.currentSrc || video.src;
      if (mediaIdFromVideoUrl(candidate) === mediaId) {
        console.log(`[FlowUI] [retrySavedVideo] 从 DOM flow-video-tile 找到更新的 URL 签名: ${candidate.substring(0, 80)}`);
        url = candidate;
      }
    }
    updateLineStatus(rowIndex, lineIndex, "generating", "重试下载已确认完成的媒体 ID...");
    return triggerAutoDownload(url, mediaId);
  }

  async function triggerAutoDownload(videoUrl, mediaName) {
    if (!state.isRunning) {
      console.warn("[FlowUI] [AutoDownload] 🚫 拒绝下载: state.isRunning 为 false (批量任务已停止)");
      return false;
    }
    if (typeof videoUrl !== "string") {
      console.warn("[FlowUI] [AutoDownload] 🚫 拒绝下载: videoUrl 不是有效字符串", videoUrl);
      return false;
    }
    const cleanUrl = videoUrl.trim().replace(/&amp;/g, "&");
    const mediaId = mediaIdFromVideoUrl(cleanUrl);
    console.log(`[FlowUI] [AutoDownload] 🔍 尝试自动下载: videoUrl=${cleanUrl.substring(0, 100)}, mediaId=${mediaId}, 传入mediaName=${mediaName || '未指定'}`);
    if (!mediaId) {
      console.warn(`[FlowUI] [AutoDownload] 🚫 拒绝下载: 无法从 URL 解析出有效的 mediaId! URL: ${cleanUrl}`);
      return false;
    }
    if (mediaName && mediaName !== mediaId) {
      console.warn(`[FlowUI] [AutoDownload] 🚫 拒绝下载: 传入的 mediaName (${mediaName}) 与从 URL 解析出的 mediaId (${mediaId}) 不一致!`);
      return false;
    }
    let match = findMediaBinding(mediaId);
    if (!match && state.isRunning) {
      const activeTask = state.tasks[state.currentIndex];
      const activeBinding = activeTask?.mediaBindings?.[state.currentLineIndex];
      const isGenerating = activeTask?.status?.[state.currentLineIndex] === "generating" && !activeTask?.downloaded?.[state.currentLineIndex];
      if (isGenerating && activeBinding && (!activeBinding.mediaIds || activeBinding.mediaIds.length === 0) && !wasVideoSeen(cleanUrl) && !isStaticShowcaseAsset(cleanUrl)) {
        // 确保该 video 在 DOM 的视频图块中
        const matchingVideoEl = Array.from(document.querySelectorAll("flow-video-tile video, flow-grid-tile-container video, video")).find(v => {
          if (!v) return false;
          const vSrc = (typeof v.getAttribute === "function" ? v.getAttribute("src") : null) || v.currentSrc || v.src;
          const hasTileParent = typeof v.closest === "function" ? !!(v.closest("flow-video-tile") || (v.closest("flow-grid-tile-container") && !v.closest("flow-image-tile"))) : true;
          return mediaIdFromVideoUrl(vSrc) === mediaId && hasTileParent;
        });
        if (matchingVideoEl) {
          console.log(`[FlowUI] 🎯 [AutoDownload] 从 DOM 视频图块中验证属于当前生成任务! 自动建立绑定: mediaId=${mediaId}, Row=${state.currentIndex}, Line=${state.currentLineIndex}`);
          activeBinding.mediaIds = [mediaId];
          if (!activeBinding.readyIds.includes(mediaId)) activeBinding.readyIds.push(mediaId);
          activeBinding.urls = activeBinding.urls || {};
          activeBinding.urls[mediaId] = cleanUrl;
          await saveState();
          match = { task: activeTask, binding: activeBinding, rowIndex: state.currentIndex, lineIndex: state.currentLineIndex };
        }
      }
    }
    if (!match) {
      console.warn(`[FlowUI] [AutoDownload] 🚫 拒绝下载: 未在任何任务行中找到已绑定 mediaId=${mediaId} 的记录! 当前任务绑定列表:`, state.tasks.map((t, i) => ({ rowIndex: i, bindings: t.mediaBindings })));
      return false;
    }
    const { task, binding, rowIndex, lineIndex } = match;
    console.log(`[FlowUI] [AutoDownload] 🎯 匹配到任务行: Row=${rowIndex}, Line=${lineIndex}, 关联图片=[${task.image?.displayName || '未命名'}], 目标文件名=${binding.downloadPath}`);
    if (rowIndex !== state.currentIndex || lineIndex !== state.currentLineIndex) {
      console.log(`[FlowUI] [AutoDownload] ℹ️ 提示: 此就绪视频属于任务 Row=${rowIndex}, Line=${lineIndex} (当前队列处理指针为 Row=${state.currentIndex}, Line=${state.currentLineIndex})，继续为该任务行独立执行下载保存，绝不丢弃！`);
    }
    if (!binding.readyIds.includes(mediaId)) {
      console.warn(`[FlowUI] [AutoDownload] 🚫 拒绝下载: mediaId (${mediaId}) 尚未就绪 (不在 readyIds 中)! 当前 readyIds:`, binding.readyIds);
      return false;
    }
    if (binding.downloading) {
      console.warn(`[FlowUI] [AutoDownload] 🚫 拒绝下载: 任务当前正在下载中 (binding.downloading=true)`);
      return false;
    }
    if (task.downloaded?.[lineIndex]) {
      console.warn(`[FlowUI] [AutoDownload] 🚫 拒绝下载: 任务行已被标记为已下载完成 (downloaded=true)`);
      return false;
    }
    if (task.downloadIds?.[lineIndex]) {
      console.warn(`[FlowUI] [AutoDownload] 🚫 拒绝下载: 任务行已有活跃下载 ID (${task.downloadIds[lineIndex]})`);
      return false;
    }
    if (!binding.downloadPath) {
      console.error(`[FlowUI] [AutoDownload] ❌ 失败: 此任务缺少已绑定的下载文件名 (downloadPath 为空)`);
      updateLineStatus(rowIndex, lineIndex, "failed", "此任务缺少已绑定的下载文件名，已停止下载");
      return false;
    }
    binding.downloading = true;
    try {
      task.videoUrls = task.videoUrls || [];
      task.videoUrls[lineIndex] = cleanUrl;
      await saveState();
      console.log(`[FlowUI] [AutoDownload] 🚀 发送下载请求到后台: URL=${cleanUrl}, Filename=${binding.downloadPath}, MediaId=${mediaId}`);
      const result = await sendToExtension("download", {
        url: cleanUrl, filename: binding.downloadPath,
        task: { rowIndex, lineIndex, taskId: task.taskId, submissionId: binding.submissionId,
          mediaId, projectId: getStorageKey(), download_path: binding.downloadPath }
      });
      console.log("[FlowUI] [AutoDownload] 后台下载响应结果:", result);
      if (!result?.success) {
        console.error(`[FlowUI] [AutoDownload] ❌ 对应视频下载失败: ${result?.error || "无下载响应"}`);
        updateLineStatus(rowIndex, lineIndex, "failed", `对应视频下载失败: ${result?.error || "无下载响应"}`);
        return false;
      }
      task.downloadIds = task.downloadIds || [];
      task.downloadIds[lineIndex] = result.downloadId;
      console.log(`[FlowUI] [AutoDownload] ✅ 下载成功启动! downloadId=${result.downloadId}`);
      if (!task.downloaded?.[lineIndex] && task.status?.[lineIndex] !== "failed") updateLineStatus(rowIndex, lineIndex, "generating", `正在下载 ${binding.downloadPath}`);
      await saveState();
      return true;
    } finally { binding.downloading = false; }
  }

  // 模拟真实用户鼠标悬停，唤醒 Google Flow 视频卡片的懒加载预览机制 (严禁点击与聚焦)
  function triggerTileHover(tile) {
    if (!tile) return;
    // 严禁触碰任何图片卡片
    if (tile.tagName === "FLOW-IMAGE-TILE" || (tile.querySelector && tile.querySelector("flow-image-tile")) || (typeof tile.closest === "function" && tile.closest("flow-image-tile"))) {
      return;
    }

    try {
      if (typeof tile.scrollIntoView === "function") {
        tile.scrollIntoView({ block: "nearest", behavior: "instant" });
      }
    } catch (_) {}

    const videoTile = tile.tagName === "FLOW-VIDEO-TILE" ? tile : ((tile.querySelector && tile.querySelector("flow-video-tile")) || tile);

    const elementsToTrigger = [
      videoTile,
      videoTile.querySelector && videoTile.querySelector(".container"),
      videoTile.querySelector && videoTile.querySelector(".pre-hover-overlay"),
      videoTile.querySelector && videoTile.querySelector(".hover-overlay-has-progress-bar"),
      videoTile.querySelector && videoTile.querySelector(".type-icon-container")
    ].filter(Boolean);

    let clientX = 100, clientY = 100;
    try {
      const rect = videoTile.getBoundingClientRect();
      if (rect.width > 0 && rect.height > 0) {
        clientX = Math.round(rect.left + rect.width / 2);
        clientY = Math.round(rect.top + rect.height / 2);
      }
    } catch (_) {}

    const eventInit = {
      bubbles: true,
      cancelable: true,
      composed: true,
      view: window,
      clientX,
      clientY,
      screenX: clientX,
      screenY: clientY,
      buttons: 0
    };

    const pointerInit = {
      ...eventInit,
      pointerId: 1,
      width: 1,
      height: 1,
      pressure: 0,
      isPrimary: true,
      pointerType: "mouse"
    };

    const createEvt = (type, init) => {
      try {
        if (type.startsWith("pointer") && typeof PointerEvent === "function") {
          return new PointerEvent(type, init);
        }
        if (typeof MouseEvent === "function") {
          return new MouseEvent(type, init);
        }
      } catch (_) {}
      return { type, bubbles: true, cancelable: true, ...init };
    };

    for (const el of elementsToTrigger) {
      try {
        if (typeof PointerEvent === "function" || (typeof window !== "undefined" && typeof window.PointerEvent === "function")) {
          el.dispatchEvent(createEvt("pointerover", pointerInit));
          el.dispatchEvent(createEvt("pointerenter", pointerInit));
          el.dispatchEvent(createEvt("pointermove", pointerInit));
        }
        el.dispatchEvent(createEvt("mouseover", eventInit));
        el.dispatchEvent(createEvt("mouseenter", eventInit));
        el.dispatchEvent(createEvt("mousemove", eventInit));
      } catch (_) {}
    }
  }

  // DOM 视频观察器：监听页面 <video> 标签及属性渲染
  function setupDomVideoWatcher() {
    console.log("[FlowUI] 启动 DOM 级视频渲染观察器...");

    function checkVideoElement(videoEl) {
      if (!videoEl || !state.isRunning) return;
      const renderedUrl = videoEl.getAttribute("src") || videoEl.currentSrc || videoEl.src;
      const renderedId = mediaIdFromVideoUrl(renderedUrl);
      let bound = findMediaBinding(renderedId);
      // 如果该任务视频已经下载完成，直接忽略，避免生命周期事件造成重复日志
      if (bound && bound.task?.downloaded?.[bound.lineIndex]) return;

      const inTile = !!(videoEl.closest("flow-video-tile") || videoEl.closest("flow-grid-tile-container"));

      // 核心救砖兜底：若网络 RPC 未能提取绑定 mediaIds (binding.mediaIds 为空)，
      // 但 DOM 中新渲染出了未见过的 flow-video-tile 视频卡片：
      if (!bound && state.isRunning && renderedId && inTile && renderedUrl) {
        const cleanUrl = renderedUrl.trim().replace(/&amp;/g, "&");
        if (!isStaticShowcaseAsset(cleanUrl) && !wasVideoSeen(cleanUrl)) {
          const activeTask = state.tasks[state.currentIndex];
          const activeBinding = activeTask?.mediaBindings?.[state.currentLineIndex];
          const isGenerating = activeTask?.status?.[state.currentLineIndex] === "generating" && !activeTask?.downloaded?.[state.currentLineIndex];

          if (isGenerating && activeBinding && (!activeBinding.mediaIds || activeBinding.mediaIds.length === 0)) {
            // 校验 DOM 提示词容器
            const batchContainer = videoEl.closest(".batch-container, .virtual-item-container") || videoEl.closest("flow-batch-info")?.parentElement;
            const promptTextEl = batchContainer ? batchContainer.querySelector(".prompt-text, flow-expandable-prompt") : null;
            const domPrompt = promptTextEl ? (promptTextEl.innerText || promptTextEl.textContent || "").trim() : "";
            const activeProcess = window.currentProcess;
            const targetPrompt = (activeProcess?.finalPrompt || activeProcess?.lineText || activeTask.lines?.[state.currentLineIndex] || "").trim();

            const isPromptMatch = !domPrompt || !targetPrompt ||
              domPrompt.includes(targetPrompt.substring(0, 20)) ||
              targetPrompt.includes(domPrompt.substring(0, 20)) ||
              domPrompt.slice(-20) === targetPrompt.slice(-20);

            if (isPromptMatch) {
              console.log(`[FlowUI] 🎯 [DOMWatcher] 识别到当前生成任务对应的新视频图块! 自动建立绑定: mediaId=${renderedId}, Row=${state.currentIndex}, Line=${state.currentLineIndex}`);
              activeBinding.mediaIds = [renderedId];
              if (!activeBinding.readyIds.includes(renderedId)) activeBinding.readyIds.push(renderedId);
              activeBinding.urls = activeBinding.urls || {};
              activeBinding.urls[renderedId] = cleanUrl;
              saveState();
              bound = { task: activeTask, binding: activeBinding, rowIndex: state.currentIndex, lineIndex: state.currentLineIndex };
            }
          }
        }
      }

      console.log(`[FlowUI] [DOMWatcher] 检查 video 元素: src=${(renderedUrl || '').substring(0, 80)}, renderedId=${renderedId}, readyState=${videoEl.readyState}, inTile=${inTile}, isBound=${!!bound}`);
      if (bound && (videoEl.readyState >= 1 || videoEl.currentTime > 0) && !videoEl.error && inTile) {
        console.log(`[FlowUI] [DOMWatcher] 视频元素已就绪 (readyState=${videoEl.readyState})，更新 readyId 并启动下载: renderedId=${renderedId}`);
        if (!bound.binding.readyIds.includes(renderedId)) bound.binding.readyIds.push(renderedId);
        bound.binding.urls = bound.binding.urls || {};
        bound.binding.urls[renderedId] = renderedUrl;
        triggerAutoDownload(renderedUrl, renderedId);
      } else if (bound && videoEl.readyState < 1) {
        console.log(`[FlowUI] [DOMWatcher] 视频元素匹配到任务 (Row=${bound.rowIndex}, Line=${bound.lineIndex})，但 readyState=${videoEl.readyState} < 1，等待 loadedmetadata...`);
      }

      const src = videoEl.getAttribute("src") || videoEl.currentSrc || videoEl.src;
      if (src && (src.startsWith("http://") || src.startsWith("https://"))) {
        if (!isStaticShowcaseAsset(src) && !wasVideoSeen(src)) {
          const hasActiveWork = (state.activeTasksQueue && state.activeTasksQueue.length > 0) ||
                                (state.tasks && state.tasks.some(t => t.status && t.status.some(s => s === "generating")));
          if (hasActiveWork) {
            console.log("[FlowUI] DOM 观察器嗅探到新生成的视频元素:", src.substring(0, 100));
            triggerAutoDownload(src);
          }
        }
      }
    }

    for (const eventName of ["loadedmetadata", "loadeddata", "canplay"]) {
      document.addEventListener(eventName, event => {
        if (event.target?.tagName === "VIDEO") {
          console.log(`[FlowUI] [DOMWatcher] 监听到视频事件 [${eventName}], src=${(event.target.currentSrc || event.target.src || '').substring(0, 80)}`);
          checkVideoElement(event.target);
        }
      }, true);
    }
    // 监听 DOM 树变化
    const observer = new MutationObserver((mutations) => {
      if (!state.isRunning) return;
      for (const m of mutations) {
        if (m.addedNodes) {
          for (const node of m.addedNodes) {
            if (node.nodeType === Node.ELEMENT_NODE) {
              if (node.tagName === "VIDEO") {
                checkVideoElement(node);
              } else {
                if (node.tagName === "FLOW-VIDEO-TILE") {
                  triggerTileHover(node);
                }
                if (node.querySelectorAll) {
                  node.querySelectorAll("flow-video-tile").forEach(triggerTileHover);
                  node.querySelectorAll("flow-video-tile video, video").forEach(checkVideoElement);
                }
              }
            }
          }
        }
        if (m.type === "attributes" && m.target && m.target.tagName === "VIDEO") {
          checkVideoElement(m.target);
        }
      }
    });

    observer.observe(document.documentElement || document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["src", "currentSrc"]
    });

    // 周期性主动扫描保底 (每 2 秒，仅在任务运行中，优先锁定当前批次)
    setInterval(() => {
      if (!state.isRunning) return;
      const hasActiveWork = (state.activeTasksQueue && state.activeTasksQueue.length > 0) ||
                            (state.tasks && state.tasks.some(t => t.status && t.status.some(s => s === "generating")));
      if (hasActiveWork) {
        const activeTask = state.tasks[state.currentIndex];
        const targetBatchContainer = findCurrentBatchContainer(activeTask, state.currentLineIndex);
        if (targetBatchContainer) {
          targetBatchContainer.querySelectorAll("flow-video-tile").forEach(triggerTileHover);
          targetBatchContainer.querySelectorAll("video").forEach(checkVideoElement);
        } else {
          document.querySelectorAll("flow-video-tile").forEach(triggerTileHover);
          document.querySelectorAll("flow-video-tile video").forEach(checkVideoElement);
        }
      }
    }, 2000);
  }

  function setupEvents() {
    window.addEventListener("flow-task-media-bound", event => {
      const { submissionId, mediaIds } = event.detail || {};
      const process = window.currentProcess;
      console.log("[FlowUI] 📥 收到 flow-task-media-bound 事件:", { submissionId, mediaIds, currentProcessSubId: process?.submissionId, isRunning: state.isRunning });
      if (!state.isRunning) {
        console.warn("[FlowUI] [media-bound] 忽略: state.isRunning 为 false");
        return;
      }
      if (!process) {
        console.warn("[FlowUI] [media-bound] 忽略: window.currentProcess 为空");
        return;
      }
      if (process.submissionId !== submissionId) {
        console.warn(`[FlowUI] [media-bound] 忽略: submissionId 不匹配 (当前=${process.submissionId}, 事件=${submissionId})`);
        return;
      }
      const binding = state.tasks[process.rowIndex]?.mediaBindings?.[process.lineIndex];
      if (binding?.submissionId !== submissionId) {
        console.warn(`[FlowUI] [media-bound] 忽略: 存储的 binding.submissionId (${binding?.submissionId}) 与事件 (${submissionId}) 不匹配`);
        return;
      }
      binding.mediaIds = [...new Set(mediaIds.filter(id => typeof id === "string" && /^[a-zA-Z0-9_-]+$/.test(id)))];
      console.log(`[FlowUI] ✅ [media-bound] 成功绑定媒体 ID 到任务: Row=${process.rowIndex}, Line=${process.lineIndex}, mediaIds=`, binding.mediaIds);
      saveState();
    });
    window.addEventListener("flow-task-binding-missing", event => {
      const process = window.currentProcess;
      console.warn("[FlowUI] ⚠️ 收到 flow-task-binding-missing 事件:", event.detail);
      if (!state.isRunning || !process || process.submissionId !== event.detail?.submissionId) {
        console.log("[FlowUI] [binding-missing] 忽略: 不属于当前活跃任务");
        return;
      }
      const binding = state.tasks[process.rowIndex]?.mediaBindings?.[process.lineIndex];
      if (binding?.mediaIds.length) {
        console.log("[FlowUI] [binding-missing] 忽略: 当前任务已有已绑定的 mediaIds:", binding.mediaIds);
        return;
      }
      console.error(`[FlowUI] ❌ [binding-missing] 生成响应未解析到可验证的媒体 ID，停止批量任务！Row=${process.rowIndex}, Line=${process.lineIndex}`);
      updateLineStatus(process.rowIndex, process.lineIndex, "failed", "生成响应未解析到可验证的媒体 ID，队列已停止，未下载其他视频。需要检查生成接口响应。");
      stopBatch();
    });
    window.addEventListener("flow-task-media-ready", async event => {
      const { mediaId, url } = event.detail || {};
      console.log(`[FlowUI] 📥 收到 flow-task-media-ready 事件: mediaId=${mediaId}, url=${url?.substring(0, 100)}`);
      const match = findMediaBinding(mediaId);
      if (!match) {
        console.warn(`[FlowUI] [media-ready] 未找到匹配的任务绑定! mediaId=${mediaId}. 当前各行绑定快照:`, state.tasks.map((t, i) => ({ rowIndex: i, bindings: t.mediaBindings })));
        return;
      }
      const parsedId = mediaIdFromVideoUrl(url);
      if (parsedId !== mediaId) {
        console.warn(`[FlowUI] [media-ready] URL 解析出的 ID (${parsedId}) 与 mediaId (${mediaId}) 不一致! 忽略此事件`);
        return;
      }
      console.log(`[FlowUI] 🎯 [media-ready] 匹配到行 Row=${match.rowIndex}, Line=${match.lineIndex}, 添加至 readyIds 并触发下载...`);
      if (!match.binding.readyIds.includes(mediaId)) match.binding.readyIds.push(mediaId);
      match.binding.urls = match.binding.urls || {};
      match.binding.urls[mediaId] = url;
      await saveState();
      await triggerAutoDownload(url, mediaId);
    });
    setupDomVideoWatcher();
  }

  // ----------------------------------------------------
  // 9. 辅助工具方法
  // ----------------------------------------------------
  function splitTextToLines(text) {
    return text ? text.split("\n").map(l => l.trim()).filter(Boolean) : [];
  }

  function calculateDuration(text) {
    const len = text.length;
    if (len <= state.settings.maxLetterFor4s) return 4;
    if (len <= state.settings.maxLetterFor6s) return 6;
    return 8;
  }

  function parsePreset(presetContent) {
    if (!presetContent) return { before: "", after: "" };
    const matches = [...presetContent.matchAll(/\n+/g)];
    if (matches.length === 0) return { before: presetContent, after: "" };
    const longest = matches.reduce((max, curr) => curr[0].length > max[0].length ? curr : max);
    const index = longest.index;
    return {
      before: presetContent.substring(0, index).trim(),
      after: presetContent.substring(index + longest[0].length).trim()
    };
  }

  function getProjectName() {
    if (isVidsPage()) {
      try {
        const titleInput = document.querySelector("input.docs-title-input");
        if (titleInput && titleInput.value && titleInput.value.trim()) return titleInput.value.trim();
        const titleLabel = document.querySelector("#docs-title-input-label-inner");
        if (titleLabel && titleLabel.textContent && titleLabel.textContent.trim()) return titleLabel.textContent.trim();
        const vidsMatch = location.pathname.match(/\/videos\/d\/([a-zA-Z0-9_-]+)/);
        if (vidsMatch) return vidsMatch[1];
      } catch (e) {}
      return "Vids_Project";
    }

    try {
      const inputEl = document.querySelector("flow-editable-text input.editable-text-input");
      if (inputEl && inputEl.value) return inputEl.value.trim();
    } catch (e) {}

    const el = document.querySelector("flow-editable-text");
    if (el && el.textContent.trim()) return el.textContent.trim();

    const match = location.pathname.match(/\/project\/([a-zA-Z0-9_-]+)/);
    if (match) return match[1];

    if (document.title) {
      const t = document.title.replace(/ - Google Flow.*/i, "").trim();
      if (t && !t.includes("Google Flow")) return t;
    }

    return "Flow_Project";
  }

  function sanitizePathName(name) {
    return name.replace(/[\\/:*?"<>|]/g, "_").trim();
  }

  function delay(ms) {
    return new Promise(r => setTimeout(r, ms));
  }

  function extendArray(arr, size, fillValue) {
    const res = [...(arr || [])];
    while (res.length < size) res.push(fillValue);
    if (res.length > size) res.length = size;
    return res;
  }

  // 全局托管模式：桥接模块在运行托管批次时设置此回调，把每行状态变化实时上报给桌面软件
  let hostedStatusHook = null;

  function updateLineStatus(rowIndex, lineIndex, status, message) {
    const task = state.tasks[rowIndex];
    if (task) {
      task.status[lineIndex] = status;
      task.message[lineIndex] = message;
      saveState();
      
      const rows = document.querySelectorAll("#flow-tasks-table tbody tr");
      if (rows && rows[rowIndex]) {
        renderTableStatusCell(rows[rowIndex], task, rowIndex);
      }
      if (typeof hostedStatusHook === "function") {
        try { hostedStatusHook(rowIndex, lineIndex, status, message); } catch (_) {}
      }
    }
  }

  // ----------------------------------------------------
  // 9. 异常活动（安全限制）监测与声光报警逻辑
  // ----------------------------------------------------
  let alarmTimer = null;
  let alarmCountdown = 45;
  let activityCheckInterval = null;

  function checkForUnusualActivity() {
    const text = document.body.innerText || "";
    return text.includes("异常活动") || text.includes("異常活動") || text.includes("不尋常的活動") || text.includes("Unusual activity") || text.includes("unusual activity");
  }

  function playAlarmSound() {
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const playBeep = (freq, startTime, duration) => {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = "sine";
        osc.frequency.setValueAtTime(freq, startTime);
        gain.gain.setValueAtTime(0.35, startTime);
        gain.gain.exponentialRampToValueAtTime(0.01, startTime + duration);
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.start(startTime);
        osc.stop(startTime + duration);
      };
      playBeep(880, ctx.currentTime, 0.15);
      playBeep(880, ctx.currentTime + 0.25, 0.15);
    } catch (e) {
      console.warn("[FlowUI] 无法播放报警提示音:", e);
    }
  }

  function startActivityCheck() {
    if (activityCheckInterval) clearInterval(activityCheckInterval);
    activityCheckInterval = setInterval(() => {
      if (state.isRunning && !state.isSuspended) {
        if (checkForUnusualActivity()) {
          handleUnusualActivityDetected();
        }
      }
    }, 1500);
  }

  function stopActivityCheck() {
    if (activityCheckInterval) {
      clearInterval(activityCheckInterval);
      activityCheckInterval = null;
    }
  }

  function handleUnusualActivityDetected() {
    console.warn("[FlowUI] 🚨 触发安全限制警告 (检测到异常活动)！已挂起任务。");
    state.isSuspended = true;
    saveState();
    
    if (alarmDialogEl) {
      alarmDialogEl.style.display = "flex";
    }
    
    playAlarmSound();
    
    alarmCountdown = 45;
    const msgEl = document.getElementById("flow-alarm-message");
    if (msgEl) {
      msgEl.style.color = "#f59e0b";
      msgEl.innerText = `系统将在 ${alarmCountdown} 秒后自动刷新网页以尝试恢复，您也可以立即进行手动处理...`;
    }
    
    if (alarmTimer) clearInterval(alarmTimer);
    alarmTimer = setInterval(() => {
      alarmCountdown--;
      if (alarmCountdown <= 0) {
        clearInterval(alarmTimer);
        console.log("[FlowUI] 安全倒计时结束，执行网页刷新恢复...");
        saveState().then(() => {
          location.reload();
        });
      } else {
        if (msgEl) {
          msgEl.innerText = `系统将在 ${alarmCountdown} 秒后自动刷新网页以尝试恢复，您也可以立即进行手动处理...`;
        }
        if (alarmCountdown % 3 === 0) {
          playAlarmSound();
        }
      }
    }, 1000);
  }

  function pauseAlarmCountdown() {
    if (alarmTimer) {
      clearInterval(alarmTimer);
      alarmTimer = null;
    }
    const msgEl = document.getElementById("flow-alarm-message");
    if (msgEl) {
      msgEl.innerText = "倒计时已暂停。请手动消除网页弹窗限制，消除后点击下方“继续运行”。";
      msgEl.style.color = "#10b981";
    }
    showToast("自动刷新倒计时已暂停，等待您的手动处理。");
  }

  function resumeFromAlarm() {
    if (alarmTimer) {
      clearInterval(alarmTimer);
      alarmTimer = null;
    }
    if (alarmDialogEl) {
      alarmDialogEl.style.setProperty("display", "none", "important");
    }
    state.isSuspended = false;
    saveState();
    showToast("安全限制挂起解除，继续批量生成...");
    
    if (state.isRunning && !batchPromise) {
      startBatch();
    }
  }

  // ----------------------------------------------------
  // 10. 初始化与断点重载自启动运行
  // ----------------------------------------------------
  async function init() {
    console.log("[FlowUI] DOMContentLoaded 触发，开始正式初始化 init()...");
    createUI();

    // 如果之前在 document_start 时挂在 documentElement 上，移入正式的 document.body
    if (document.body) {
      if (fabEl && fabEl.parentNode !== document.body) {
        document.body.appendChild(fabEl);
      }
      if (overlayEl && overlayEl.parentNode !== document.body) {
        document.body.appendChild(overlayEl);
      }
    }

    setupEvents();

    // 拍摄页面已有展示视频基线快照：把页面初始自带的样例或历史视频全部登记为已存在，严防误下载
    function snapshotExistingVideos() {
      const videos = document.querySelectorAll("video");
      videos.forEach(v => {
        const src = v.getAttribute("src") || v.currentSrc || v.src || v.getAttribute("src");
        if (src) downloadedUrlsSet.add(src);
      });
      console.log(`[FlowUI] 拍摄初始视频快照完成，隔离保护 ${videos.length} 个页面已有视频`);
    }
    snapshotExistingVideos();
    window.addEventListener("load", () => snapshotExistingVideos());

    // 立即启动单页应用保活检查：防止 Google Flow 路由二次重绘冲掉挂载在 body 上的 FAB
    setInterval(() => {
      createUI();
    }, 1500);

    // 加载先前保存的状态
    await loadState();
    
    // 如果网页刚才由于刷新中断且处于 Running 状态，则自动断点续跑启动批量任务
    if (state.isRunning) {
      console.log("[FlowUI] 检测到批量运行状态为 TRUE，自动恢复运行断点续传。任务索引:", state.currentIndex, "子行索引:", state.currentLineIndex);
      showToast("正在自动恢复未完成的生成任务，请保持浏览器窗口在前台...");
      
      // 启动安全监测
      startActivityCheck();
      
      // 等待 2.5 秒，保证页面 NextJS 初始化以及 trpc Webpack 完成，然后自启
      setTimeout(() => {
        startBatch();
      }, 2500);
    }
  }

  // 多时机激进挂载：保证在任何阶段都能立即渲染悬浮按钮
  try {
    createUI();
  } catch (e) {
    console.warn("[FlowUI] 首次即时挂载暂缓:", e);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
  window.addEventListener("load", () => createUI());

  console.log("%c[FlowUI] 界面控制器加载完毕！", "background: #8b5cf6; color: white; padding: 2px 6px; border-radius: 4px;");

  // ====================================================================
  // 轻量账号桥接 (用于桌面软件的「全局托管模式」通信)
  // - 支持 Google Flow 与 Google Vids (docs.google.com/videos/*)
  // - 只保持一个 WebSocket 连接，不做任何定时 DOM 读取
  // ====================================================================
  (function initAccountBridge() {
    const host = location.hostname;
    if (!(host.endsWith("labs.google") || host.endsWith("flow.google.com") || isVidsPage())) return;
    if (window.__flowAccountBridgeLoaded) return;
    window.__flowAccountBridgeLoaded = true;

    const WS_URL = "ws://127.0.0.1:18188";
    const clientId = "flow_ext_" + Math.random().toString(36).substring(2, 9);
    let socket = null;
    let retryDelay = 3000;          // 断线重连：3s 起步，最长 10s（本机连接失败几乎无开销，软件后启动也能很快连上）
    const MAX_RETRY = 10000;
    let cachedPoints = null;
    let cachedEmail = "";
    let lastProbeAt = 0;
    let probing = null;

    const log = (...a) => console.log("[FlowAccount]", ...a);
    const sleep = (ms) => new Promise(r => setTimeout(r, ms));
    const EMAIL_RE = /([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})/;

    function readEmailCheap() {
      if (cachedEmail) return cachedEmail;
      try {
        // Google Vids 页面在 head meta[name="og-profile-acct"] 中直接带有登录邮箱
        const metaAcct = document.querySelector('meta[name="og-profile-acct"]');
        if (metaAcct && metaAcct.content) {
          const m = metaAcct.content.match(EMAIL_RE);
          if (m) return (cachedEmail = m[1]);
        }
        const panel = document.querySelector("flow-account-panel");
        if (panel) {
          const m = panel.textContent.match(EMAIL_RE);
          if (m) return (cachedEmail = m[1]);
        }
        const els = document.querySelectorAll("[aria-label*='@']");
        for (const el of els) {
          const m = (el.getAttribute("aria-label") || "").match(EMAIL_RE);
          if (m) return (cachedEmail = m[1]);
        }
      } catch (e) {}
      return "";
    }

    function readPointsFromDom() {
      if (isVidsPage()) return 9999; // Google Vids 无 50 积分限制
      try {
        const span = document.querySelector("span.credits-count");
        if (span) {
          const m = span.textContent.trim().match(/(\d+)/);
          if (m) return parseInt(m[1], 10);
        }
        const link = document.querySelector("a.credits-link");
        if (link) {
          const m = link.textContent.trim().match(/(\d+)/);
          if (m) return parseInt(m[1], 10);
        }
        const panel = document.querySelector("flow-account-panel");
        if (panel) {
          for (const el of panel.querySelectorAll("span, div, a, p")) {
            if (el.children.length > 2) continue;
            const t = (el.textContent || "").trim();
            if (t.includes("点数") || t.includes("點數") || t.includes("积分") || t.includes("積分") || /credits|points/i.test(t) || /\b\d+\s*點\b/.test(t)) {
              const m = t.match(/(\d+)/);
              if (m) {
                const n = parseInt(m[1], 10);
                if (n >= 0 && n < 100000) return n;
              }
            }
          }
        }
      } catch (e) {}
      return null;
    }

    async function doProbe() {
      if (isVidsPage()) {
        readEmailCheap();
        return 9999; // Google Vids 无积分上限限制
      }
      // 菜单已打开时直接读
      let pts = readPointsFromDom();
      if (pts !== null) { readEmailCheap(); return pts; }

      const avatarBtn = document.querySelector('div.header-user-button[role="button"]') ||
                        document.querySelector("div.header-user-button") ||
                        document.querySelector('[aria-label="账号详情"], [aria-label="帳戶詳細資料"], [aria-label*="账号"], [aria-label*="帳戶"], [aria-label*="帳號"], [aria-label*="Account" i]') ||
                        document.querySelector('flow-header-user-icon [role="button"]');
      if (!avatarBtn) { log("未找到头像按钮"); return null; }

      avatarBtn.click();
      // 等待菜单渲染（最多约 3 秒）
      for (let i = 0; i < 10 && pts === null; i++) {
        await sleep(300);
        pts = readPointsFromDom();
      }
      const panel = document.querySelector("flow-account-panel");
      if (panel) {
        const m = panel.textContent.match(EMAIL_RE);
        if (m) cachedEmail = m[1];
      }
      // 关闭菜单
      await sleep(100);
      const closer = document.querySelector("flow-account-panel button.close-button") ||
                     document.querySelector(".cdk-overlay-backdrop");
      if (closer) closer.click();
      else document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
      return pts;
    }

    async function probePoints() {
      // 3 秒内重复请求直接返回缓存，避免频繁点击
      if (Date.now() - lastProbeAt < 3000 && cachedPoints !== null) return cachedPoints;
      if (probing) return probing;
      probing = (async () => {
        try {
          const pts = await doProbe();
          if (pts !== null) cachedPoints = pts;
          lastProbeAt = Date.now();
          log("积分:", cachedPoints, "账号:", cachedEmail || readEmailCheap());
          return cachedPoints;
        } catch (e) {
          log("读取积分失败", e);
          return cachedPoints;
        } finally {
          probing = null;
        }
      })();
      return probing;
    }

    function countMediaTiles() {
      const main = document.querySelector("main") || document.body;
      const imgs = Array.from(main.querySelectorAll("img")).filter(i => {
        const r = i.getBoundingClientRect();
        return r.width > 60 && r.height > 60 && !i.closest("#flow-batch-overlay");
      });
      const vids = Array.from(main.querySelectorAll("video")).filter(v => !v.closest("#flow-batch-overlay"));
      return imgs.length + vids.length;
    }

    function fireKey(type, key, code, keyCode, ctrl) {
      const ev = new KeyboardEvent(type, { key, code, ctrlKey: !!ctrl, bubbles: true, cancelable: true, composed: true, view: window });
      try {
        Object.defineProperty(ev, "keyCode", { get: () => keyCode });
        Object.defineProperty(ev, "which", { get: () => keyCode });
      } catch (e) {}
      document.body.dispatchEvent(ev);
    }

    function findConfirmDeleteButton() {
      const btns = Array.from(document.querySelectorAll(
        "[role='dialog'] button, mat-dialog-container button, .cdk-overlay-pane button, [role='alertdialog'] button"));
      return btns.find(b => {
        const t = (b.textContent || "").trim();
        return b.offsetParent && /^(删除|刪除|永久删除|永久刪除|移至回收站|移到回收站|移至垃圾桶|移到垃圾桶|确定|確定|确认|確認|Delete|Move to trash|Confirm)/i.test(t);
      });
    }

    async function clearFlowMedia() {
      // 关闭插件面板，避免焦点在面板/输入框里（否则 Ctrl+A 会选中文字）
      try { if (typeof closePanel === "function") closePanel(); } catch (e) {}
      try { if (document.activeElement && document.activeElement !== document.body) document.activeElement.blur(); } catch (e) {}
      window.focus();
      await sleep(300);

      const before = countMediaTiles();
      if (before === 0) return { success: true, before: 0, after: 0, note: "当前页面没有媒体" };

      fireKey("keydown", "a", "KeyA", 65, true);
      fireKey("keyup", "a", "KeyA", 65, true);
      await sleep(800);
      fireKey("keydown", "Delete", "Delete", 46, false);
      fireKey("keyup", "Delete", "Delete", 46, false);

      // 若弹出确认框，自动点击确认
      let confirmed = false;
      for (let i = 0; i < 10; i++) {
        await sleep(300);
        const b = findConfirmDeleteButton();
        if (b) { b.click(); confirmed = true; break; }
      }

      // 等待媒体消失
      let after = countMediaTiles();
      for (let i = 0; i < 15 && after > 0; i++) {
        await sleep(400);
        after = countMediaTiles();
      }
      log(`清空媒体: 删除前 ${before} 个, 删除后 ${after} 个, 确认框=${confirmed}`);
      return { success: after < before, before, after, confirmed,
               error: after >= before ? "模拟 Ctrl+A / Delete 未生效" : "" };
    }

    function send(obj) {
      try {
        if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(obj));
      } catch (e) {}
    }

    async function handleMessage(msg) {
      const action = msg.action || msg.type;
      if (action === "ping") { send({ type: "pong" }); return; }

      if (action === "get_points") {
        const pts = await probePoints();
        send({
          action: "get_points_response",
          request_id: msg.request_id,
          success: pts !== null,
          client_id: clientId,
          email: cachedEmail || readEmailCheap(),
          data: {
            remaining_points: pts,
            email: cachedEmail || readEmailCheap(),
            client_id: clientId,
            mode: isVidsPage() ? "vids" : "flow",
            unlimited: isVidsPage()
          }
        });
        return;
      }

      if (action === "clear_tasks") {
        let ok = true, err = "";
        try {
          if (typeof batchPromise !== "undefined" && batchPromise) {
            ok = false; err = "插件队列正在运行，请先停止";
          } else {
            const n = (state.tasks || []).length;
            state.tasks = [];
            state.taskRecord = {};
            state.activeTasksQueue = [];
            state.currentIndex = 0;
            state.currentLineIndex = 0;
            state.retryCount = 0;
            try { renderTable(); } catch (e) {}
            await saveState();
            try { showToast("已由桌面软件清空全部任务列表"); } catch (e) {}
            log("已清空任务列表, 原任务数:", n);
            err = String(n);
          }
        } catch (e) { ok = false; err = String(e && e.message || e); }
        send({ action: "clear_tasks_response", request_id: msg.request_id, success: ok,
               error: ok ? "" : err, data: { cleared: ok ? parseInt(err, 10) || 0 : 0 } });
        return;
      }

      if (action === "clear_media") {
        let result = { success: false };
        try { result = await clearFlowMedia(); } catch (e) { result = { success: false, error: String(e && e.message || e) }; }
        send({ action: "clear_media_response", request_id: msg.request_id, success: !!result.success,
               error: result.error || "", data: result });
        return;
      }

      // ===== 全局托管模式 =====
      if (action === "upload_images") {
        const p = msg.params || {};
        let data;
        if (isVidsPage()) {
          // Google Vids 模式下无需预先批量上传图片，而是在执行任务时逐个上传到「添加动画」输入框
          data = { uploaded: p.paths || [], skipped: [], failed: [], errors: {}, mode: "vids" };
        } else {
          try {
            data = await uploadPathsToFlow(p.paths || [], { timeoutMs: Math.max(10, Number(p.timeout_seconds) || 60) * 1000 });
          } catch (e) {
            data = { uploaded: [], skipped: [], failed: p.paths || [], errors: { _all: String(e && e.message || e) } };
          }
        }
        send({ action: "upload_images_response", request_id: msg.request_id, success: !data.failed.length,
               client_id: clientId, data: { ...data, upload_id: p.upload_id || "" } });
        return;
      }

      if (action === "run_tasks") {
        const p = msg.params || {};
        const batchId = p.batch_id || "";
        const reply = (ok, error, extra = {}) => send({ action: "run_tasks_response", request_id: msg.request_id, success: ok,
                                                       error: error || "", client_id: clientId, data: { batch_id: batchId, ...extra } });
        if (typeof batchPromise !== "undefined" && batchPromise) { reply(false, "插件队列正在运行，请先停止"); return; }
        if (!location.href.includes("/project/") && !isVidsPage()) { reply(false, "浏览器当前不在 Flow 或 Google Vids 项目页面"); return; }
        let count = 0;
        try {
          if (p.clear_existing !== false) {
            state.tasks = []; state.taskRecord = {}; state.activeTasksQueue = [];
            state.currentIndex = 0; state.currentLineIndex = 0; state.retryCount = 0;
          }
          count = importTaskList(Array.isArray(p.tasks) ? p.tasks : []);
          try { renderTable(); } catch (_) {}
          await saveState();
        } catch (e) { reply(false, "导入任务失败：" + String(e && e.message || e)); return; }
        if (!count) { reply(false, "没有可导入的任务"); return; }
        reply(true, "", { count });
        try { showToast(`🤖 托管模式：已接收 ${count} 个任务，开始生成`, 4000); } catch (_) {}

        hostedStatusHook = (r, l, status, message) => {
          if (status !== "success" && status !== "failed") return;
          const t = state.tasks[r] || {};
          send({ type: "hosted_task_status", batch_id: batchId, client_id: clientId, row: r, line: l, status, message: message || "",
                 download_path: t.download_path || "", image_name: t.image?.displayName || "" });
        };
        try { await startBatch(); } catch (e) { log("托管批次异常", e); }
        hostedStatusHook = null;

        const results = state.tasks.map((t, i) => {
          const st = Array.isArray(t.status) ? t.status : [];
          const ok = st.length > 0 && st.every(s => s === "success");
          const msgs = (Array.isArray(t.message) ? t.message : []).filter(Boolean);
          return { row: i, download_path: t.download_path || "", image_name: t.image?.displayName || "",
                   status: ok ? "success" : "failed", message: ok ? "" : (msgs[msgs.length - 1] || "未完成") };
        });
        send({ type: "hosted_batch_finished", batch_id: batchId, client_id: clientId, results,
               stopped: typeof isStopRequested !== "undefined" && !!isStopRequested });
        return;
      }

      if (action === "stop_tasks") {
        try { if (typeof batchPromise !== "undefined" && batchPromise) stopBatch(); } catch (_) {}
        send({ action: "stop_tasks_response", request_id: msg.request_id, success: true, client_id: clientId });
        return;
      }

      if (action === "close_browser") {
        const token = (msg.params && msg.params.token) || "";
        log("收到桌面软件指令：关闭浏览器, token=", token);
        if (token) {
          // 在标题中写入唯一标记，桌面软件据此找到本浏览器窗口并关闭整个浏览器进程
          const marker = `[${token}] `;
          const applyMarker = () => {
            if (!document.title.startsWith(marker)) document.title = marker + document.title.replace(/^\[FLOWCLOSE-[^\]]*\]\s*/, "");
          };
          applyMarker();
          const iv = setInterval(applyMarker, 200);
          setTimeout(() => clearInterval(iv), 15000);
        }
        send({ action: "close_browser_response", request_id: msg.request_id, success: true, client_id: clientId, token });
        
        // 插件优先自己关闭所有窗口（精确且安全）
        setTimeout(() => { sendToExtension("closeBrowser", {}); }, 200);
        return;
      }
    }

    function connect() {
      try {
        socket = new WebSocket(WS_URL);
      } catch (e) {
        scheduleReconnect();
        return;
      }
      socket.onopen = () => {
        retryDelay = 3000;
        log("已连接桌面软件");
        send({ type: "online", client_id: clientId, email: readEmailCheap(), url: location.href });
        // 检测插件后台是否为新版本（旧后台没有拖放上传/关闭浏览器等能力）
        sendToExtension("getBgVersion", {}).then(r => {
          const ok = !!(r && r.version);
          send({ type: "bg_status", client_id: clientId, ok, version: (r && r.version) || "",
                 native_drag: !!(r && r.nativeDrag), error: ok ? "" : String((r && r.error) || "插件后台无响应") });
          if (!ok) log("⚠️ 插件后台不是最新版本，请在扩展管理页点击「刷新」重新加载插件");
        });
      };
      socket.onmessage = (ev) => {
        let msg;
        try { msg = JSON.parse(ev.data); } catch (e) { return; }
        handleMessage(msg);
      };
      socket.onclose = () => { socket = null; scheduleReconnect(); };
      socket.onerror = () => { /* onclose 会负责重连 */ };
    }

    function scheduleReconnect() {
      setTimeout(connect, retryDelay);
      retryDelay = Math.min(retryDelay * 2, MAX_RETRY);
    }

    // 页面加载完成后再连接，避免影响页面初始化
    setTimeout(connect, 3000);
  })();

})();
