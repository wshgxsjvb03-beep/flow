// ==UserScript==
// @name         Flow Desktop Browser Auto-Automation Adapter
// @namespace    http://tampermonkey.net/
// @version      1.1
// @description  Flow 桌面端无缝浏览器自动化适配器 (支持积分回传、Base64图片自动上传、Prompt自动填充)
// @author       Flow Team
// @match        *://*/*
// @grant        none
// ==UserScript==

(function () {
    'use strict';

    const WS_URL = "ws://127.0.0.1:18188";
    let socket = null;
    let clientId = "Browser_Worker_" + Math.floor(Math.random() * 1000);

    // ==========================================
    // 1. 网页 DOM 工具库 (图片合成 / 上传 / 提示词填入)
    // ==========================================

    /**
     * 将 Base64 Data URL 转换为原生 JavaScript File 二进制对象
     */
    function dataURLtoFile(dataurl, filename) {
        if (!dataurl || !dataurl.startsWith("data:")) return null;
        const arr = dataurl.split(',');
        const mime = arr[0].match(/:(.*?);/)[1];
        const bstr = atob(arr[1]);
        let n = bstr.length;
        const u8arr = new Uint8Array(n);
        while (n--) {
            u8arr[n] = bstr.charCodeAt(n);
        }
        return new File([u8arr], filename || "image.png", { type: mime });
    }

    /**
     * 自动将 File 对象绑定并挂载到目标 HTML 上传控件 (Input 或 Dropzone 拖拽区域)
     */
    function uploadFileToElement(targetElem, file) {
        if (!targetElem || !file) return false;

        try {
            // 构造标准 HTML5 DataTransfer 容器
            const dataTransfer = new DataTransfer();
            dataTransfer.items.add(file);

            if (targetElem.tagName === "INPUT" && targetElem.type === "file") {
                targetElem.files = dataTransfer.files;
                targetElem.dispatchEvent(new Event('change', { bubbles: true }));
                targetElem.dispatchEvent(new Event('input', { bubbles: true }));
                console.log("[Flow Adapter] Attached file to <input type='file'> successfully.");
                return true;
            } else {
                // 针对 React / Vue 类的自定义 Drag & Drop 区域派发 drop 事件
                const dropEvent = new DragEvent('drop', {
                    bubbles: true,
                    cancelable: true,
                    dataTransfer: dataTransfer
                });
                targetElem.dispatchEvent(dropEvent);
                console.log("[Flow Adapter] Dispatched drop event with file to target element.");
                return true;
            }
        } catch (e) {
            console.error("[Flow Adapter] Upload file failed:", e);
            return false;
        }
    }

    /**
     * 自动填入提示词 (支持原生与 React/Vue 受控 Input/Textarea)
     */
    function fillPromptText(inputElem, text) {
        if (!inputElem) return false;
        inputElem.focus();
        inputElem.value = text;

        // 针对 React/Vue 的 value setter 挂钩
        const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value")?.set
            || Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set;

        if (nativeSetter) {
            nativeSetter.call(inputElem, text);
        }

        inputElem.dispatchEvent(new Event('input', { bubbles: true }));
        inputElem.dispatchEvent(new Event('change', { bubbles: true }));
        return true;
    }

    let cachedRemainingPoints = 50;
    let isProbingPoints = false;

    function readPointsFromDom() {
        try {
            // 1. 优先定位 Flow 专属头像菜单链接
            const creditLinks = Array.from(document.querySelectorAll("a[href*='flow_ai_credits_page'], a[href*='utm_campaign=flow_ai_credits_page'], [class*='bgEUcQ']"));
            for (const link of creditLinks) {
                const txt = link.textContent.trim();
                const match = txt.match(/(\d+)\s*(?:Google Flow\s*)?点数/i) || txt.match(/(\d+)/);
                if (match) {
                    const num = parseInt(match[1], 10);
                    if (!isNaN(num) && num >= 0 && num < 100000) {
                        return num;
                    }
                }
            }

            // 2. 传统通用类名选择器
            const selectors = [".user-points", "#points", ".credit-count", "[data-points]", ".balance"];
            for (const sel of selectors) {
                const elem = document.querySelector(sel);
                if (elem) {
                    const pts = parseInt(elem.innerText.replace(/[^0-9]/g, ""), 10);
                    if (!isNaN(pts)) return pts;
                }
            }

            // 3. 通用文本匹配
            const textNodes = Array.from(document.querySelectorAll("span, div, button, p, a"));
            for (const el of textNodes) {
                if (el.children.length <= 1 && el.textContent) {
                    const txt = el.textContent.trim();
                    const match = txt.match(/(\d+)\s*(?:Google Flow\s*)?点数/i) || txt.match(/⚡\s*(\d+)|(\d+)\s*(?:积分|credits|points)/i);
                    if (match) {
                        const num = parseInt(match[1] || match[2], 10);
                        if (!isNaN(num) && num >= 0 && num < 100000) return num;
                    }
                }
            }
        } catch (e) {
            console.warn("[Flow Adapter] Read points error:", e);
        }
        return null;
    }

    async function probePointsByClickingAvatar() {
        if (isProbingPoints) return cachedRemainingPoints;
        isProbingPoints = true;
        try {
            const immediatePts = readPointsFromDom();
            if (immediatePts !== null) {
                cachedRemainingPoints = immediatePts;
                isProbingPoints = false;
                return immediatePts;
            }

            const avatarBtn = document.querySelector("button:has(img[alt='用户头像']), button:has(img[alt*='头像']), img[alt='用户头像'], img[alt*='头像'], button.LfOBo, button[class*='LfOBo']")?.closest("button")
                           || document.querySelector("img[alt='用户头像']")?.parentElement
                           || document.querySelector("img[alt*='头像']");

            if (avatarBtn) {
                console.log("[Flow Adapter] 正在模拟点击头像以探测真实点数...");
                avatarBtn.click();
                await new Promise(r => setTimeout(r, 200));

                const probedPts = readPointsFromDom();
                if (probedPts !== null) {
                    cachedRemainingPoints = probedPts;
                    console.log("[Flow Adapter] 探测到真实点数:", probedPts);
                }

                await new Promise(r => setTimeout(r, 50));
                avatarBtn.click();

                if (probedPts !== null && socket && socket.readyState === WebSocket.OPEN) {
                    socket.send(JSON.stringify({
                        type: "status_update",
                        client_id: clientId,
                        remaining_points: probedPts,
                        status: "idle"
                    }));
                    return probedPts;
                }
            }
        } catch (e) {
            console.warn("[Flow Adapter] 点击头像探测点数失败:", e);
        } finally {
            isProbingPoints = false;
        }
        return cachedRemainingPoints;
    }

    /**
     * 读取网页上的账户剩余积分
     */
    function getRemainingPoints() {
        const domPts = readPointsFromDom();
        if (domPts !== null) {
            cachedRemainingPoints = domPts;
            return domPts;
        }
        probePointsByClickingAvatar().catch(() => {});
        return cachedRemainingPoints;
    }


    // ==========================================
    // 2. WebSocket 长连接通信与任务驱动引擎
    // ==========================================

    function connect() {
        console.log("[Flow Adapter] Connecting to Flow Server: " + WS_URL);
        socket = new WebSocket(WS_URL);

        socket.onopen = function () {
            console.log("[Flow Adapter] WebSocket Connected!");
            socket.send(JSON.stringify({
                type: "online",
                client_id: clientId,
                name: "浏览器插件 (" + window.location.host + ")",
                remaining_points: getRemainingPoints()
            }));

            setTimeout(() => {
                probePointsByClickingAvatar();
            }, 1200);
        };

        socket.onmessage = function (event) {
            try {
                const msg = JSON.parse(event.data);
                console.log("[Flow Adapter] Message received:", msg);

                if (msg.type === "execute_tasks") {
                    runBatchTasks(msg.batch_id, msg.tasks);
                }
            } catch (err) {
                console.error("[Flow Adapter] Message handler error:", err);
            }
        };

        socket.onclose = function () {
            console.log("[Flow Adapter] Disconnected. Reconnecting in 3s...");
            setTimeout(connect, 3000);
        };

        socket.onerror = function (err) {
            console.error("[Flow Adapter] Socket error:", err);
        };
    }

    /**
     * 自动批次任务执行引擎
     */
    async function runBatchTasks(batchId, tasks) {
        console.log(`[Flow Adapter] Starting Batch ${batchId} with ${tasks.length} tasks...`);
        const executionReport = [];

        for (const task of tasks) {
            console.log(`[Flow Adapter] Task [Index ${task.index}]: ${task.prompt}`);

            // 1. 如果任务包含首帧图片，自动合成并挂载图片上传
            if (task.image_data_url) {
                const file = dataURLtoFile(task.image_data_url, task.image_name || "upload.png");
                if (file) {
                    // 请将 '.file-upload-input' 替换为您网页目标上传控件的选择器
                    const uploadInput = document.querySelector('input[type="file"]') || document.querySelector('.file-upload-input');
                    if (uploadInput) {
                        uploadFileToElement(uploadInput, file);
                    }
                }
            }

            // 1.1 如果任务包含尾帧图片，同样支持自动合成挂载上传
            if (task.end_image_data_url) {
                const endFile = dataURLtoFile(task.end_image_data_url, task.end_image_name || "end_upload.png");
                if (endFile) {
                    const endUploadInput = document.querySelector('.end-frame-upload-input') || document.querySelector('input[type="file"].end-frame');
                    if (endUploadInput) {
                        uploadFileToElement(endUploadInput, endFile);
                    }
                }
            }

            // 2. 自动填入提示词
            // 请将 '.prompt-textarea' 替换为您网页提示词输入框的选择器
            const promptInput = document.querySelector('textarea') || document.querySelector('.prompt-textarea');
            if (promptInput) {
                fillPromptText(promptInput, task.prompt);
            }

            // 3. 模拟等待与点击生成按钮（TODO: 替换为网页上实际的提交按钮 selector）
            // const generateBtn = document.querySelector('.btn-generate');
            // if (generateBtn) generateBtn.click();
            await new Promise(res => setTimeout(res, 1000)); // 演示等待 1 秒

            // 记录成功状态
            executionReport.push({
                index: task.index,
                prompt: task.prompt,
                status: "success",
                download_path: task.download_path || ""
            });
        }

        // 回传报告与最新积分给 Flow 桌面端
        socket.send(JSON.stringify({
            type: "execution_report",
            batch_id: batchId,
            remaining_points: getRemainingPoints(),
            data: executionReport
        }));
        console.log("[Flow Adapter] Batch complete! Execution report sent back.");
    }

    // 启动长连接
    connect();
})();
