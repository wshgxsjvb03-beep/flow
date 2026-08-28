# Google Labs Flow 浏览器插件开放对接接口规范 (Open API Specification)

> **版本**：v2.0.0  
> **通信协议**：WebSocket + JSON-RPC 2.0 规范  
> **服务端口**：`ws://127.0.0.1:18188` (备用端口: `8000`, `8765`)  
> **适用场景**：任何第三方客户端（Python、Node.js、Go、C#、桌面端或 Web 服务）与 Google Labs Flow 浏览器插件进行全自动对接与无缝控制。

---

## 目录
1. [系统架构与双线设计](#1-系统架构与双线设计)
2. [通用通信协议规范](#2-通用通信协议规范)
3. [原子接口详细定义](#3-原子接口详细定义)
   - [3.1 查询账号真实点数 (`get_points`)](#31-查询账号真实点数-get_points)
   - [3.2 上传图片原料素材 (`upload_image`)](#32-上传图片原料素材-upload_image)
   - [3.3 提交视频生成并同步等待完成 (`generate_video`)](#33-提交视频生成并同步等待完成-generate_video)
   - [3.4 获取当前网页环境与素材列表 (`get_environment`)](#34-获取当前网页环境与素材列表-get_environment)
   - [3.5 批量任务排队下发 (`execute_batch_tasks`)](#35-批量任务排队下发-execute_batch_tasks)
   - [3.6 中断/停止当前任务 (`stop_current`)](#36-中断停止当前任务-stop_current)
   - [3.7 触发扩展后台静默下载 (`trigger_download`)](#37-触发扩展后台静默下载-trigger_download)
4. [插件主动推送事件 (Events)](#4-插件主动推送事件-events)
5. [多语言客户端对接示例 (Python / Node.js)](#5-多语言客户端对接示例)
6. [错误码与排错指南](#6-错误码与排错指南)

---

## 1. 系统架构与双线设计

整个 Flow 助手系统采用 **“双线分离”** 架构：

```
+-------------------------------------------------------------------------------+
|                             Google Labs Flow 浏览器插件                       |
+---------------------------------------+---------------------------------------+
|        【线一：半自动独立 UI 面板】     |      【线二：开放接口引擎 (Open API)】   |
|  - 悬浮 FAB 按钮呼出控制面板          |  - Background Service Worker WS 长连接|
|  - 支持手动粘贴 JSON 数组配置         |  - 标准 JSON-RPC 消息调度器与状态机   |
|  - 本地表格可视化任务进度             |  - 原子操作驱动 (上传/注入/生成/拦截) |
|  - 手动导出执行报告到剪贴板           |  - 支持任意外部程序 RPC 即时调用      |
+---------------------------------------+---------------------------------------+
                                                            ▲
                                                            │ WebSocket (Port 18188)
                                                            ▼
+-------------------------------------------------------------------------------+
|                      第三方客户端 (Python 桌面端 / 自研后台服务 / 脚本)          |
+-------------------------------------------------------------------------------+
```

- **半自动线**：完全保留在网页端悬浮面板上，供单机人工排查、断网或手动操作。
- **开放接口线**：浏览器插件蜕变为底层的 **Flow 自动化驱动器 (Browser Agent Driver)**，对外暴露标准 WebSocket JSON-RPC 接口。

---

## 2. 通用通信协议规范

### 2.1 客户端请求报文格式 (Request)

客户端发送到插件的所有请求均为标准 JSON 格式，必须包含唯一的 `request_id`：

```json
{
  "action": "接口名称",
  "request_id": "唯一请求标识（如 UUID 或时间戳字符串）",
  "params": {
    /* 接口特定参数对象 */
  }
}
```

### 2.2 插件响应报文格式 (Response)

插件处理完操作后，原样带回 `request_id`：

```json
{
  "action": "接口名称_response",
  "request_id": "与请求一致的 request_id",
  "success": true,
  "data": {
    /* 接口返回的具体数据 */
  },
  "error": null
}
```

若发生异常，`success` 为 `false`，`error` 包含具体错误信息：

```json
{
  "action": "接口名称_response",
  "request_id": "req_12345",
  "success": false,
  "data": null,
  "error": "错误描述信息 (如：图片上传超时，缺失 MediaKey)"
}
```

---

## 3. 原子接口详细定义

### 3.1 查询账号真实点数 (`get_points`)

* **功能说明**：主动模拟点击用户头像展开菜单，探测 Google Flow 账号最新的真实剩余点数（如 50 点），并静默关闭菜单。
* **适用场景**：第三方软件初始化连接、任务分批前查询预算、生成后实时核对余额。

#### 请求参数 (Params)
*无需必填参数*

```json
{
  "action": "get_points",
  "request_id": "req_points_001",
  "params": {}
}
```

#### 成功响应 (Data)
| 字段名 | 类型 | 说明 |
| :--- | :--- | :--- |
| `remaining_points` | `integer` | 当前账号真实剩余点数 (例如 `50`) |
| `account_email` | `string` | 当前登录的 Google 邮箱 (若未获取到则返回 `""`) |
| `is_probed` | `boolean` | 是否是通过模拟点击头像成功探测所得 |

```json
{
  "action": "get_points_response",
  "request_id": "req_points_001",
  "success": true,
  "data": {
    "remaining_points": 50,
    "account_email": "user@gmail.com",
    "is_probed": true
  },
  "error": null
}
```

---

### 3.2 上传图片原料素材 (`upload_image`)

* **功能说明**：将外部客户端传输的 Base64 图片数据或 URL，通过原生 `DataTransfer` 与 `Dropzone` 注入到 Google Flow 网页素材库，并执行严格的 DOM 校验（等待缩略图渲染且遮罩消失），确保 100% 成功上传后返回 `media_key`。
* **适用场景**：视频生成前，精准上载特定的分镜首帧/参考图。

#### 请求参数 (Params)
| 字段名 | 类型 | 必填 | 说明 |
| :--- | :--- | :--- | :--- |
| `image_name` | `string` | 是 | 素材文件名，例如 `"scene_01.png"` |
| `image_data_url` | `string` | 是 | 图片的 Base64 Data URL (如 `"data:image/png;base64,..."`) |
| `timeout_seconds` | `integer` | 否 | 上传等待超时时间 (默认 `30` 秒) |

```json
{
  "action": "upload_image",
  "request_id": "req_upload_002",
  "params": {
    "image_name": "character_intro.png",
    "image_data_url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA...",
    "timeout_seconds": 30
  }
}
```

#### 成功响应 (Data)
| 字段名 | 类型 | 说明 |
| :--- | :--- | :--- |
| `image_name` | `string` | 原始图片名 |
| `media_key` | `string` | Google Flow 内部素材唯一 Key (例如 `"fe_id_66c4a89f92b74b88849b49b2"`) |
| `media_id` | `string` | 内部素材 ID |
| `upload_duration_ms` | `integer` | 上传与 DOM 校验耗时 (毫秒) |

```json
{
  "action": "upload_image_response",
  "request_id": "req_upload_002",
  "success": true,
  "data": {
    "image_name": "character_intro.png",
    "media_key": "fe_id_66c4a89f92b74b88849b49b2",
    "media_id": "66c4a89f92b74b88849b49b2",
    "upload_duration_ms": 11500
  },
  "error": null
}
```

---

### 3.3 提交视频生成并同步等待完成 (`generate_video`)

* **功能说明**：设置视频参数、注入提示词和参考图片素材，触发生成。随后由底层的 `flow-proxy.js` Hook 拦截生成请求并轮询监听状态。当视频生成成功后，直接在浏览器端提取生成的 MP4 字节并转为 Base64，同时触发静默下载，最后将完整产物与直链回传给客户端。
* **适用场景**：第三方软件单条/多条视频生成调度的核心接口。

#### 请求参数 (Params)
| 字段名 | 类型 | 必填 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| `prompt` | `string` | 是 | - | 视频生成提示词文本 |
| `image_name` | `string` | 否 | `""` | 关联素材图片名称 (用于比对匹配) |
| `media_key` | `string` | 否 | `""` | 显式指定的图片素材 `media_key` (若提供则无需匹配) |
| `duration` | `integer` | 否 | `6` | 视频时长，单位秒 (支持 `4`, `6`, `8`, `10`) |
| `mode` | `string` | 否 | `"VIDEO_FRAMES"` | 生成模式：`"VIDEO_FRAMES"` (首尾帧) 或 `"VIDEO_REFERENCES"` (参考素材) |
| `model` | `string` | 否 | `"veo_3_1_lite_low_priority"` | 视频模型名称 |
| `aspect_ratio` | `string` | 否 | `"PORTRAIT"` | 画面画幅比例：`"PORTRAIT"` (9:16) 或 `"LANDSCAPE"` (16:9) |
| `count` | `integer` | 否 | `1` | 单次生成数量 (通常为 `1`) |
| `download_path` | `string` | 否 | `""` | 外部软件指定的本地绝对下载路径 (用于自动子目录规划) |
| `return_base64` | `boolean` | 否 | `true` | 是否在响应中返回视频的 Base64 字节数据 |

```json
{
  "action": "generate_video",
  "request_id": "req_gen_003",
  "params": {
    "prompt": "A cinematic close-up of a smiling boy in rainy Tokyo, 4k photorealistic.",
    "media_key": "fe_id_66c4a89f92b74b88849b49b2",
    "image_name": "boy.png",
    "duration": 6,
    "mode": "VIDEO_FRAMES",
    "model": "veo_3_1_lite_low_priority",
    "aspect_ratio": "PORTRAIT",
    "count": 1,
    "download_path": "D:\\Projects\\Flow\\downloads\\videos\\01.mp4",
    "return_base64": true
  }
}
```

#### 成功响应 (Data)
| 字段名 | 类型 | 说明 |
| :--- | :--- | :--- |
| `status` | `string` | 生成状态 (`"success"`) |
| `media_name` | `string` | 生成的视频产物唯一识别名 |
| `download_url` | `string` | Google Cloud Storage 真实直连下载 URL |
| `target_filename` | `string` | 格式化后的规范文件名 (例如 `"Project_01.mp4"`) |
| `download_path` | `string` | 客户端原始传入的保存路径 |
| `base64_data` | `string` | 视频 MP4 完整二进制数据的 Base64 字符串 (`return_base64` 为 `true` 时返回) |
| `duration` | `integer` | 视频实际秒数 |
| `cost_points` | `integer` | 本次生成预计消耗的点数 (4s=7, 6s=10, 8s=12, 10s=15) |

```json
{
  "action": "generate_video_response",
  "request_id": "req_gen_003",
  "success": true,
  "data": {
    "status": "success",
    "media_name": "media_batch_9921_generated_01",
    "download_url": "https://storage.googleapis.com/labs-flow-prod/video/xxx.mp4",
    "target_filename": "01.mp4",
    "download_path": "D:\\Projects\\Flow\\downloads\\videos\\01.mp4",
    "base64_data": "AAAAIGZ0eXBpc29tAAACAGlzb21pc28yYXZjMW1wNDE...",
    "duration": 6,
    "cost_points": 10
  },
  "error": null
}
```

---

### 3.4 获取当前网页环境与素材列表 (`get_environment`)

* **功能说明**：获取 Google Flow 网页当前的健康状态、所属项目名称、已加载的所有图片素材资产列表以及剩余点数。
* **适用场景**：客户端开始任务前自检。

#### 请求参数 (Params)
*无需参数*

```json
{
  "action": "get_environment",
  "request_id": "req_env_004",
  "params": {}
}
```

#### 成功响应 (Data)
```json
{
  "action": "get_environment_response",
  "request_id": "req_env_004",
  "success": true,
  "data": {
    "project_name": "01_车里，已检查-flow",
    "project_id": "proj_12345",
    "is_store_ready": true,
    "remaining_points": 50,
    "loaded_images": [
      {
        "id": "fe_id_img1",
        "primaryMediaKey": "fe_id_img1",
        "displayName": "01.png"
      },
      {
        "id": "fe_id_img2",
        "primaryMediaKey": "fe_id_img2",
        "displayName": "02.png"
      }
    ]
  },
  "error": null
}
```

---

### 3.5 批量任务排队下发 (`execute_batch_tasks`)

* **功能说明**：一次性下发一个批次的多条任务（数组）。插件将按顺序逐一上传图片、逐条生成，每完成一条实时通过 `video_completed` 事件回传，全部完成后响应总报告。
* **适用场景**：兼容桌面端现有的分批下发调度模式。

#### 请求参数 (Params)
```json
{
  "action": "execute_batch_tasks",
  "request_id": "req_batch_005",
  "params": {
    "batch_id": "batch_20260820_01",
    "tasks": [
      {
        "index": 0,
        "prompt": "Prompt 1...",
        "image_name": "img1.png",
        "image_data_url": "data:image/png;base64,...",
        "duration": 6,
        "mode": "VIDEO_FRAMES",
        "download_path": "D:\\videos\\01.mp4"
      },
      {
        "index": 1,
        "prompt": "Prompt 2...",
        "image_name": "img2.png",
        "image_data_url": "data:image/png;base64,...",
        "duration": 4,
        "mode": "VIDEO_FRAMES",
        "download_path": "D:\\videos\\02.mp4"
      }
    ]
  }
}
```

---

### 3.6 中断/停止当前任务 (`stop_current`)

* **功能说明**：立即中断当前正在排队或生成的批量任务队列。

```json
{
  "action": "stop_current",
  "request_id": "req_stop_006",
  "params": {}
}
```

---

### 3.7 触发扩展后台静默下载 (`trigger_download`)

* **功能说明**：直接利用 Chrome `chrome.downloads` API 将远端视频静默下载并归档到指定子路径（如 `Flow/Project/01.mp4`）。

#### 请求参数 (Params)
```json
{
  "action": "trigger_download",
  "request_id": "req_dl_007",
  "params": {
    "url": "https://storage.googleapis.com/...",
    "filename": "Flow/01_Project/01.mp4"
  }
}
```

---

## 4. 插件主动推送事件 (Events)

除了针对请求的应答外，插件在运行过程中会主动向客户端发送事件推送（Push Notifications）：

### 4.1 插件上线与心跳注册 (`online`)
当浏览器标签页打开或插件连上桌面端时自动推送：
```json
{
  "event": "online",
  "client_id": "Browser_Worker_8892",
  "name": "Flow 批量助手 (项目名)",
  "remaining_points": 50
}
```

### 4.2 单条视频生成完成事件 (`video_completed`)
在批处理模式下，每刷完一条视频即时推送（包含 Base64 数据）：
```json
{
  "event": "video_completed",
  "client_id": "Browser_Worker_8892",
  "batch_id": "batch_01",
  "segment_index": 0,
  "prompt": "...",
  "download_url": "https://...",
  "download_path": "D:\\videos\\01.mp4",
  "base64_data": "AAAAIGZ0eXB...",
  "status": "success"
}
```

### 4.3 检测到 Google 安全风控拦截 (`alarm_detected`)
当 Google Flow 网页出现“异常活动/Unusual activity”弹窗时，插件自动挂起并向客户端告警：
```json
{
  "event": "alarm_detected",
  "client_id": "Browser_Worker_8892",
  "message": "检测到 Google 安全限制（异常活动），任务已自动挂起，将在 45 秒后刷新恢复。"
}
```

---

## 5. 多语言客户端对接示例

### 5.1 Python 异步客户端封装 (`flow_client.py`)

以下是一段开箱即用的 Python 对接类：

```python
import asyncio
import json
import uuid
import websockets
from pathlib import Path

class FlowPluginClient:
    def __init__(self, ws_url="ws://127.0.0.1:18188"):
        self.ws_url = ws_url
        self.ws = None
        self.pending_requests = {}

    async def connect(self):
        """连接到 Flow 插件 WebSocket"""
        self.ws = await websockets.connect(self.ws_url)
        asyncio.create_task(self._listen_loop())
        print(f"Connected to Flow Plugin at {self.ws_url}")

    async def _listen_loop(self):
        """监听插件响应与推送事件"""
        try:
            async for message in self.ws:
                data = json.loads(message)
                req_id = data.get("request_id")
                if req_id and req_id in self.pending_requests:
                    self.pending_requests[req_id].set_result(data)
                elif "event" in data:
                    print(f"[Event Received]: {data['event']}", data)
        except Exception as e:
            print("Connection closed:", e)

    async def call_action(self, action: str, params: dict = None, timeout: float = 60.0):
        """发送 JSON-RPC 请求并异步等待应答"""
        req_id = f"req_{uuid.uuid4().hex[:8]}"
        payload = {
            "action": action,
            "request_id": req_id,
            "params": params or {}
        }
        future = asyncio.get_event_loop().create_future()
        self.pending_requests[req_id] = future
        await self.ws.send(json.dumps(payload, ensure_ascii=False))
        
        return await asyncio.wait_for(future, timeout=timeout)

    # 1. 查点数
    async def get_points(self):
        res = await self.call_action("get_points", {}, timeout=10.0)
        return res["data"]["remaining_points"]

    # 2. 上传图片
    async def upload_image(self, image_path: str):
        p = Path(image_path)
        import base64
        with open(p, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        data_url = f"data:image/png;base64,{b64}"
        
        res = await self.call_action("upload_image", {
            "image_name": p.name,
            "image_data_url": data_url
        }, timeout=45.0)
        return res["data"]["media_key"]

    # 3. 刷视频
    async def generate_video(self, prompt: str, media_key: str, duration: int = 6):
        res = await self.call_action("generate_video", {
            "prompt": prompt,
            "media_key": media_key,
            "duration": duration,
            "mode": "VIDEO_FRAMES"
        }, timeout=180.0)
        return res["data"]

# === 使用演示 ===
async def main():
    client = FlowPluginClient()
    await client.connect()
    
    # 查点数
    points = await client.get_points()
    print(f"当前账户剩余点数: {points}")
    
    # 上传图片
    media_key = await client.upload_image("test.png")
    print(f"图片上传成功，MediaKey: {media_key}")
    
    # 刷视频
    result = await client.generate_video("A cute cat playing piano", media_key, duration=6)
    print("视频生成成功！URL:", result["download_url"])

if __name__ == "__main__":
    asyncio.run(main())
```

---

### 5.2 Node.js 客户端对接示例 (`flow-client.js`)

```javascript
const WebSocket = require('ws');
const fs = require('fs');

class FlowClient {
  constructor(url = 'ws://127.0.0.1:18188') {
    this.ws = new WebSocket(url);
    this.callbacks = new Map();

    this.ws.on('message', (data) => {
      const res = JSON.parse(data.toString());
      if (res.request_id && this.callbacks.has(res.request_id)) {
        this.callbacks.get(res.request_id)(res);
        this.callbacks.delete(res.request_id);
      }
    });
  }

  call(action, params = {}) {
    return new Promise((resolve) => {
      const requestId = 'req_' + Math.random().toString(36).substring(2, 9);
      this.callbacks.set(requestId, resolve);
      this.ws.send(JSON.stringify({ action, request_id: requestId, params }));
    });
  }
}
```

---

## 6. 错误码与排错指南

| 错误信息关键字 | 原因分析 | 推荐解决方案 |
| :--- | :--- | :--- |
| `WebSocket connection failed` | 桌面端服务端未启动或端口被占用 | 检查桌面端是否已运行，端口 `18188` 是否被防火墙放行 |
| `promptBoxStore 未就绪` | 网页未完全加载或非 Flow 项目页面 | 确保浏览器停留在 `labs.google/fx/.../project/...` 页面 |
| `图片上传超时，缺失 MediaKey` | 网络卡顿或素材上传被 Google 拒绝 | 延长 `timeout_seconds` 或在网页上手动重试上传 |
| `全局 generateVideo 方法未就绪` | `flow-proxy.js` 尚未完成 Hook | 刷新网页，检查 `manifest.json` 中 `flow-proxy.js` 是否在 `document_start` 运行 |
| `检测到安全限制（异常活动）` | 连续请求频率过高触发 Google 校验 | 增加任务间的间隔时间（建议 $\ge 20$ 秒），手动在网页上点击解除验证 |

---

> **文档维护建议**：后续增加新参数（如多分辨率 1080P/4K 切换、相机运动控制等）时，直接在 `generate_video` 接口的 `params` 对象中扩展即可，保持向后兼容。
