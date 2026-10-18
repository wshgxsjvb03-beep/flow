# Flow 项目安全审核与修复报告

审核日期：2026-10-18。对象为当前工作区，包括审核开始前已有的未提交修改。该报告取代 `VIDS_SECURITY_AUDIT.md` 的历史安全结论。

已修复可复现的 HTML 注入、越界读取和写入、错误视频归档、API 密钥重定向泄露等问题，升级 Qt 补丁并加固扩展和 CI。根据开发者本次决定，已删除应用内更新功能；保留现有浏览器自动化架构和本地密钥保存兼容性。因此仍有两项 High 信任边界风险，不能据此认定项目已无高危风险。

## 项目概况与范围

| 项目 | 结果 |
| --- | --- |
| 语言与框架 | Python、PyQt6 Widgets / WebSockets / Multimedia；JavaScript、CSS；Chrome Manifest V3 扩展 |
| 依赖管理 | pip、requirements.txt；原有 7 个显式运行依赖，修复后 8 个，新增的是原有 Qt 间接依赖的安全下限 |
| 实际运行依赖 | 本机 Windows 虚拟环境共 17 个相关包，8 个直接、9 个间接；另有开发和打包工具 |
| 锁文件 | 第一方项目没有 Python 锁文件或哈希锁定清单；下文是本机实际版本，不能冒充锁文件版本 |
| 构建与发布 | PyInstaller，flow.spec 为主配置，main.spec 为兼容入口，另有 flow_tool.spec 和 Inno Setup；GitHub Actions 发布 Windows / macOS 压缩包 |
| 检查范围 | models、services、views、extension、main.py、适配器、测试、示例、文档、配置、启动脚本、3 个 spec 和 GitHub Actions |
| 检查方法 | 第一方源文件静态检查，逐文件定位入口和危险调用，再人工跟踪网络、消息、文件、凭据、DOM 和发布链路；不是逐行人工证明所有 UI 逻辑安全 |
| 凭据扫描 | 初始扫描计数为 3533 个文件、2063 个 ZIP 内条目、254 个 Git 可达 blob；单文件超过 25 MiB 的 8 项跳过文本扫描，二进制不等同于完成反编译审核 |

详细文件清单见 [source-inventory.json](security-audit-evidence/source-inventory.json)。第一方生产文件、测试和外部保存的 Google 页面分开处理；`.venv`、第三方 `node_modules` 不作为第一方源代码逐行审核。Git blob 包含工具快照的可能性，不能把出现于对象库直接等同于已推送到远程。

## 问题汇总

位置采用修复后的行号；已删除文件标注删除前位置。严重性指项目风险，条件性或尚未证明可利用的依赖问题另行说明。

| 编号 | 类别 | 严重级别 | 位置 | 状态 |
| --- | --- | --- | --- | --- |
| C01 | 代码 | High | extension/injects/ui.js:891、1985、1989 | 已修复 |
| C02 | 代码 | High | views/project_detail_widget.py:2041、2115；services/security.py:51 | 已修复 |
| C03 | 代码 | High | views/project_detail_widget.py:2894、2986；services/security.py:39、65 | 已修复 |
| C04 | 代码 | Medium | models/batch_model.py:58；models/project_model.py:41 | 已修复 |
| C05 | 代码 | Medium | views/project_detail_widget.py:2986；services/video_relocation.py:9；services/video_checker.py:41 | 已修复 |
| C06 | 代码 | Medium | services/speech_extractor.py:132、162、181、193、275 | 已修复 |
| C07 | 代码 | Medium | services/plugin_server.py:79 | 已修复来源规则；鉴权风险见 C12 |
| C08 | 代码 | Medium | services/plugin_server.py:115、324 | 已修复输入类型与单消息大小问题 |
| C09 | 代码 | Medium | 原 services/updater.py:84；原 views/update_dialog.py；views/main_window.py | 已修复，按开发者决定删除功能 |
| C10 | 代码 | Medium | .github/workflows/release.yml:23、28、73、78 | 已修复可变 Action 引用 |
| C11 | 代码 | Medium | extension/background.js:4、129；extension/content-isolated.js:74；extension/manifest.json；plugin_script_adapter.js | 已修复来源、协议和参数边界；C13 仍保留 |
| C12 | 代码 | High | services/plugin_server.py:79；extension/injects/ui.js 的 WebSocket 调度 | 建议关注，开发者明确选择保留现有流程 |
| C13 | 代码 | High | extension/content-isolated.js:72；extension/background.js 的 nativeFileDrag / closeBrowser | 建议关注，开发者明确选择暂不改通信架构 |
| S01 | 密钥 | Medium | models/config_manager.py 的 load / save；views/settings_dialog.py | 建议关注，开发者明确保留本地明文兼容性 |
| S02 | 密钥 | Low | 新建文件夹/Google Flow - 10月 17 - 20_00.html:88 及关联第三方脚本 | 建议关注，凭据所有权与限制待确认；已加入忽略规则 |
| D01 | 依赖 | Medium | requirements.txt:2；原 PyQt6-Qt6 6.11.1 | 已修复到 6.11.2，属防御性升级，模块可达性见下文 |
| D02 | 依赖 | Low | requirements.txt；.github/workflows/release.yml:36 | 建议关注，运行依赖未完整锁定与校验哈希 |
| D03 | 依赖 | Low | PySocks 1.7.1、colorama 0.4.6 | 建议关注，发布间隔较长，不等同于确认停止维护 |
| D04 | 依赖 | Medium | Qt 原生 DLL、外部 ffmpeg、可选 imageio_ffmpeg / pywin32 | 建议关注，原生组件及外部工具的完整漏洞覆盖待确认 |
| C14 | 代码 | Low | extension/injects/ui.js、extension/injects/flow-proxy.js 的调试日志 | 建议关注，部分日志仍含任务内容或媒体地址 |

没有确认的 Critical 问题。C12、C13 是已知设计风险，开发者选择保留不能解释为风险已消失。

## 已修复问题和利用条件

### HTML 注入与页面策略

**C01：** 导入的任务文字、模板名或生成错误消息可包含 HTML 和引号，原先会进入 `innerHTML` 的文本及属性位置。攻击者需要让用户导入恶意内容，或让不可信响应进入状态消息；能在 Google 页面上下文中插入活动节点，可能结合扩展消息桥调用更高权限操作。

现在所有动态字段都转义 `& < > " '`，同时删除 ui.js 和 flow-proxy.js 注册宽松全局 `default` Trusted Types 策略的逻辑，取消 Script / ScriptURL 通行策略。具名 HTML 策略只用于代码内模板，不能把 `setSafeHTML` 名称当作通用 HTML 消毒器；新增动态模板仍须转义。DOM 测试验证恶意文案只成为文本，不生成 img、svg、事件属性或脚本节点。

### 文件边界和视频归档

**C02：** 恶意项目 metadata.json 可把首尾帧图片名改为绝对路径或 `../../private.pem`。原编码函数对未知后缀使用 image/jpeg 并读取原始字节，可能在导出或调度时把任意本地文件内容带入浏览器。现在首尾帧只能引用当前项目 downloads 内的普通图片文件名；拒绝目录逃逸和指向外部的符号链接，未知后缀不再编码，单张编码大小上限为 50 MiB。

**C03：** 原报告允许在整个项目目录内指定写入目标，剪贴板报告甚至允许项目的父存储目录。攻击者需要能提交报告或诱导用户粘贴报告，可以覆盖元数据，或在包含可执行脚本的项目目录写入载荷。现在 WebSocket 报告的目标完全由片段索引生成，固定为当前项目 `downloads/videos/序号.mp4`；剪贴板目标也必须通过同一目录和扩展名校验。写入采用随机临时文件、大小限制和不覆盖发布，既有文件保留，目录解析结果再次校验。

**C04：** 批次 JSON 内可控 id 被拼接成写入或删除路径，项目 id 被拼接成字幕路径。现在拒绝批次 id 中的分隔符、盘符、控制字符及越界解析结果；无效项目 id 保持为项目目录名，阻断字幕目录逃逸。保留正常历史 id。

**C05：** 原归档逻辑找不到文件时，会取 Downloads/Flow 下最近的任意 MP4；手工检查器还使用目录前缀或包含关系匹配项目。它们可误取、误移动其他项目或备份目录中的文件。开发者批准取消这类兜底。现在仅匹配当前项目的确切目录和文件，同名多来源保留待处理，目标不覆盖；没有实际文件时不标记报告完成。延迟检查也只重试同一项目文件。手工目录检查只接受完整项目名及历史上去掉末尾 `-flow` 的完整名称。

### 网络和密钥发送

**C06：** Requests 默认重定向不会自动剥离 `x-gladia-key`、`xi-api-key` 这类自定义密钥头；Gladia 返回的 result_url 原先不校验主机。利用需要控制受信任 API 的响应或其重定向，并非普通第三方能直接设置这些响应。现在上传、创建任务、轮询和 ElevenLabs 请求都关闭自动重定向；轮询只允许 HTTPS、标准端口、无用户信息的 api.gladia.io。

报告直连媒体下载只允许指定 Google 媒体主机及子域，每次跳转前校验，关闭环境代理和 .netrc 继承，拒绝 HTTP、自定义端口和带用户信息的 URL。该措施限制不可信报告的请求目标，不声称实现对恶意 DNS 解析器的地址固定。ffmpeg 音频提取增加 `file,pipe` 协议白名单及 `-nostdin`，避免本地伪装媒体通过外部协议拉取资源。返回的密钥标识改为 SHA-256 短指纹，轮换流程错误内容会移除当前密钥明文。

### 消息入口和扩展权限

**C07：** 原 WebSocket 来源允许 file://、任意 localhost 端口，并未要求 Google 来源使用 HTTPS。现在要求规范化的 HTTPS Google Origin 或合法格式的 Chrome 扩展 Origin，拒绝用户信息、路径、查询和非标准端口。为兼容原生客户端仍接受缺省 Origin；Origin 不是鉴权，剩余风险单列 C12。

**C08：** 原消息解析后直接调用 `.get` 或 `int`，数组、标量和异常点数类型可能从 Qt 回调抛出异常。现在先检查消息对象、字段类型、点数范围和报告列表，单消息及单帧上限为 128 MiB。该上限允许现有 Base64 视频消息，但仍不属于全局连接数或全局内存配额。

**C11：** 后台增加扩展 ID、顶层 frame、发信页面与标签页 URL 校验；独立脚本增加 `event.origin` 和 action 白名单。下载仅允许 HTTPS，拖放参数必须是有界的本地图片路径列表，拒绝 UNC、设备路径、NTFS 备用数据流、控制字符和 `..`。存储操作限制为现有页面状态键，拒绝任意键和异常参数；下载 ID 必须是安全整数。

内容脚本改为只匹配 HTTPS、只在顶层注入；示例用户脚本从匹配所有网站改为目标 Google 页面，并加运行时校验。`debugger`、`tabs`、`downloads` 权限是现有功能所需，本次没有删除。`host_permissions` 仍覆盖多个 Google CDN/API 域，未宣称已达到绝对最小权限；Chrome 的 host permission 路径部分也不能当作有效的路径授权边界。

### 更新和发布

**C09：** 更新模块原先仅按 HTTPS 主机和大小校验安装包，在可预测临时目录下载并启动 EXE。按开发者明确要求，最终方案是删除 services/updater.py、views/update_dialog.py、主窗口更新方法及 flow.spec 中的打包引用，并更新受影响测试和 README。没有保留下载器、安装启动器或静默检查入口。独立 installer.iss 仍是人工发布安装包的构建脚本，不是应用内更新功能。

**C10：** 四个第三方 Action 原先使用可移动大版本标签。现在通过 GitHub 官方 API 解析原大版本标签，固定到完整提交 SHA；checkout 关闭凭据持久化；PyInstaller 固定为本机已验证的 6.22.3。未触发发布，也未推送标签。现有流水线仅由 tag push 触发，没有 pull_request_target 或把 PR 标题直接拼进 shell 的情况。写权限仍在整个发布构建 job 中可见，进一步拆分构建与发布权限是后续加固项。

## 依赖版本和已知漏洞核对

本机 `.venv` 为 Python 3.14.5；CI 声明 Python 3.11。版本来自包元数据，不由 requirements 的最低版本猜测。Web 检索覆盖每个直接依赖，并对关键间接依赖、Qt 和打包工具交叉检查；空搜索结果只表示未查到已知公告。完整在线 `pip-audit --local` 覆盖虚拟环境 48 个包，修复前后均为 0 个已知 Python 包漏洞；它没有揭示 Qt 原生组件问题，所以单独检查官方公告。

| 直接依赖 | 声明 | 本机实际版本 | 核对结果 |
| --- | --- | --- | --- |
| PyQt6 | ==6.11.0 | 6.11.0 | 未查到适用于该 Python 绑定版本的已知公告；原生 Qt 单列 |
| PyQt6-Qt6 | >=6.11.2,<6.12 | 6.11.1 → 6.11.2 | 补丁升级，详见 D01 |
| beautifulsoup4 | ==4.15.0 | 4.15.0 | 未查到适用于该版本的已知公告；CSS 选择器引擎另核对 |
| gdown | ==6.1.0 | 6.1.0 | 已高于 archive extractall 路径遍历修复版 5.2.2；项目不调用该解压 API |
| requests | ==2.34.2 | 2.34.2 | 已高于 extract_zipped_paths 临时文件复用修复版 2.33.0；项目未直接调用该 API |
| pillow | ==12.3.0 | 12.3.0 | 图片打开、翻转等功能实际使用；当前版本已包含相关 12.3.0 安全修复 |
| urllib3 | >=2.8.0 | 2.8.0 | 实际用于 Requests 流式下载；已达 2026-09 HTTPS 代理 TLS 与 chunk-size 行内存问题的修复下限 |
| soupsieve | >=2.9.0 | 2.10 | 已高于选择器 ReDoS 修复版 2.8.4，也覆盖后续 2.9 修复 |

gdown、Requests 的条件与版本分别依据 [gdown 官方公告](https://github.com/advisories/GHSA-76hw-p97h-883f)、[Requests 官方公告](https://github.com/psf/requests/security/advisories/GHSA-gc5v-m9x4-r6x2)。urllib3 依据 [2.8.0 发布说明](https://github.com/urllib3/urllib3/releases/tag/2.8.0)；Soup Sieve 依据 [选择器 ReDoS 公告](https://github.com/advisories/GHSA-836r-79rf-4m37)和[后续空白处理公告](https://github.com/facelessuser/soupsieve/security/advisories/GHSA-j934-xhv5-fg8f)。Pillow 依据 [12.3.0 发布说明](https://github.com/python-pillow/Pillow/blob/main/docs/releasenotes/12.3.0.rst)。这些是已验证的版本边界，不代表本项目当前仍受上述历史漏洞影响。

| 关键间接依赖 | 本机实际版本 | 核对结果 |
| --- | --- | --- |
| PyQt6_sip | 13.11.1 | pip-audit 未报告适用漏洞；官方项目元数据已核对 |
| certifi | 2026.6.17 | 高于 GLOBALTRUST 根证书移除版本 2024.7.4 |
| charset-normalizer | 3.4.9 | 未检出适用已知漏洞 |
| idna | 3.18 | 高于编码输入 DoS 修复版 3.7 |
| filelock | 3.29.7 | 高于锁文件竞态修复版 3.20.1 / 3.20.3 |
| tqdm | 4.68.4 | 已高于历史 CLI 参数注入修复；项目使用进度库，不调用其 CLI 注入入口 |
| typing_extensions | 4.16.0 | 未检出适用已知漏洞 |
| colorama | 0.4.6 | 未检出适用已知漏洞；2022-10-25 发布，长期未发布需关注 |
| PySocks | 1.7.1 | Requests 的 socks extra 经 gdown 引入；2019-09-20 发布，长期未发布需关注 |

间接依赖公告参见 [certifi](https://github.com/certifi/python-certifi/security/advisories/GHSA-248v-346w-9cwc)、[idna](https://github.com/advisories/GHSA-jjg7-2v4v-x38h)、[filelock 文件竞态](https://github.com/advisories/GHSA-w853-jp5j-5j7f)、[SoftFileLock](https://github.com/advisories/GHSA-qmgc-5h2g-mvrw)、[tqdm CLI](https://github.com/tqdm/tqdm/security/advisories/GHSA-g7vv-2v7x-gj9p)。发布时间以 [PySocks PyPI](https://pypi.org/project/PySocks/1.7.1/) 和 [colorama PyPI](https://pypi.org/project/colorama/0.4.6/) 为依据。未发现直接依赖名称仿冒证据；没有因此认定其他包绝不可能存在供应链风险。

**D01 Qt 原生组件：** [Qt 官方公告清单](https://wiki.qt.io/List_of_known_vulnerabilities_in_Qt_products)列明 6.11.1 的 HTTP Cache-Control 解析、QXmlStreamReader、QDom、Qt Quick SVG path 等问题，6.11.2 修复相应分支。项目未发现直接调用这些受影响的 HTTP/XML/Quick API，因此没有把它们报成已确认可远程利用的 High。仍升级运行时并写入安装下限，防止后续安装回退。Qt VNC 身份验证问题修复版为 6.11.3，QDom 特定 XML 序列化问题修复版为 6.12.0；项目未发现使用 Qt VNC / QDom，PyPI 当前提供的 Qt wheel 为 6.11.2，不能声称此次升级修复 Qt 的所有公告。今后启用相关模块前须重新确认。

打包工具为 PyInstaller 6.22.3。其[特权 onefile 环境变量公告](https://github.com/pyinstaller/pyinstaller/security/advisories/GHSA-9fxf-4qw3-ghmr)修复版为 6.22.1；本项目当前采用 onedir，安装脚本要求最低普通用户权限，没有发现特权 onefile 用法。

**D04 原生媒体边界：** 实测升级后的 Qt DLL 通过 `av_version_info` 返回 FFmpeg 7.1.5；Qt Multimedia 确实处理视频，不能用 pip-audit 的 0 结果代替原生解码器审计。[FFmpeg 官方安全清单](https://ffmpeg.org/security.html)的分支条目与 DLL 构建补丁不是完整一一映射，尚未确认该 DLL 存在某条具体未修复漏洞。系统 ffmpeg、可选 imageio_ffmpeg / pywin32 在本环境未安装，分别走原视频上传或关闭浏览器失败的兼容路径；其他部署环境的版本待确认，没有擅自添加依赖或替换 DLL。

`scratch/flow-dom-runtime/node_modules` 存有用于测试的 jsdom 26.1.0，但没有顶层 package.json 或 lock；`npm audit --prefix scratch/flow-dom-runtime --json` 返回 ENOLOCK，不能报告 npm 审计通过。它不在生产扩展或 PyInstaller 的运行依赖中，测试环境应补齐可复现的开发依赖清单。

## 密钥与凭据检查

扫描包含源码、配置、测试、示例、注释、文档、文本构建产物、可读 ZIP 项及本地 Git 可达 blob，规则覆盖私钥头、GitHub / AWS / 常见服务 token、JWT、带口令 URL、Webhook 和密钥赋值。输出只记录路径、行号和匹配类型，不复制密钥值。

- `.env`、`.env.*`、`.app_config.json`、常见密钥文件和账号状态文件已有忽略规则；`git check-ignore` 验证有效。当前跟踪列表中没有真实 `.env` 或 `.app_config.json`，只有空值示例。
- `.env.example` 已有 `GLADIA_API_KEYS=`、`ELEVENLABS_API_KEYS=`，无需制造新的示例密钥；配置层本来支持单数环境变量别名并避免回存环境变量密钥。
- 没有确认属于本项目的硬编码有效私钥、服务 token 或口令。保存的 Google 网页和附带脚本匹配到 Google 浏览器 API key 格式；它们在第三方页面资源中，可能为公开客户端标识。归属、授权域和限制配置**待确认**，未尝试调用或验证其权限。相关 blob 也见于本地 Git 对象库，但常规 `git log --all -- 路径` 没有提交记录，不能声称已经公开泄露。
- 已将 `/新建文件夹/` 加入忽略规则，避免把认证网页快照和第三方脚本误提交。按用户规则没有擅自删除原始资料或重写 Git 历史。
- **任何已经提交或泄露的自有密钥，都必须到对应平台作废并重新生成；只删除代码、加 .gitignore 或改环境变量不够。** 本次没有代替开发者作废任何凭据。

S01 的本地 JSON 明文保存与硬编码泄露不同：利用需要读取用户设置文件、其备份或错误共享目录。开发者已选择保留兼容行为；建议后续迁移到 Windows Credential Manager / 系统凭据库，同时处理已有 JSON 迁移和回退，不能只对保存值做 Base64 或固定密钥“加密”。

## 开发者决定与剩余风险

| 问题 | 已作决定或可选方案 | 后续建议 |
| --- | --- | --- |
| C13 网页到高权限后台的桥 | 开发者选择保留流程，仅做来源、协议和参数校验；另一方案为配对并把 WebSocket 与高权限调度移入隔离环境 | 下一阶段采用架构方案。当前同页脚本仍可伪造 flow-main 消息；`event.source` / `event.origin` 无法区别同一文档中的脚本。任意本地图片路径和关闭浏览器权限仍可能被滥用 |
| C12 本地 WebSocket 无鉴权 | 原生客户端可不带 Origin，任意合法 Chrome 扩展 Origin 也不绑定特定扩展；配对需要改变连接流程，本次没有实施 | 增加一次性配对、每客户端能力限制及任务与报告归属校验；本机恶意进程可以伪造 Origin 并竞争接收任务，因此项目图片和提示词仍可能泄露 |
| S01 本地密钥保存 | 开发者选择保留本地 JSON 和环境变量兼容性；可选系统凭据库迁移 | 后续单独实施迁移和恢复设计。现在优先由进程环境变量注入，限制用户设置目录的共享和备份权限 |
| C05 归档行为 | 开发者批准确切文件匹配，已实施 | 找不到确切文件时由用户核对，避免恢复“最新任意视频”的兜底 |
| C09 更新程序 | 开发者要求删除功能，已实施 | 旧 dist 中的历史二进制不会因为源码删除自动变安全；正式发布须重新构建 |
| D02 可复现依赖 | 无完整锁文件；本次未把 Windows / Python 3.14 环境冻结成 macOS / Python 3.11 通用锁 | 分平台生成有哈希的构建锁，保存 SBOM；保留安全更新流程 |
| D03 老旧间接依赖 | 未确认停止维护，也未确认存在当前可用的安全替代补丁 | 检查代理功能是否必需，再决定 Requests socks extra / gdown 依赖替代，避免无理由删功能 |
| D04 原生解析器 | 未确认具体未修复的可利用漏洞；没有擅自替换 ABI 相关 DLL | 单独追踪 Qt / FFmpeg SBOM，隔离处理不可信媒体，禁用未使用的解析功能前确认业务需求 |

扩展 C13、WebSocket C12 与环境中可安装其他扩展或本地进程的威胁模型直接相关，应优先于低风险日志和依赖清单整理。C14 中已删除后台完整消息、部分完整 URL 和响应转储，但页面代理仍有详细调试日志；共享控制台截图和日志前应检查任务内容与签名媒体 URL。CI 可进一步把读取源码的构建 job 与有写权限的发布 job 分开。

## 测试和构建结果

| 检查 | 结果和边界 |
| --- | --- |
| 修复前 Python 基线 | 35 项全部通过 |
| 修复后 Python | 47 项全部通过；含原有业务测试与新增安全边界测试 |
| JavaScript | 5 组全部通过：批次进度、首尾帧、真实页面 DOM 回放、响应解析、安全测试 |
| pip-audit 在线 | 最终 48 个已安装 Python 包，0 个已知漏洞；不包含原生 DLL 漏洞证明 |
| pip check | 无依赖冲突 |
| compileall | 第一方 Python 模块编译通过 |
| Bandit | 全量第一方 Python 检查，没有 High / Medium 自动告警；Low 为宽泛异常处理、子进程等人工复核项目，工具结果不能覆盖 DOM / Qt 消息漏洞 |
| git diff --check | 通过 |
| 原始 flow.spec | 后续按开发者要求统一命名为 Flow，移除 logo.ico 资源引用，EXE 设置 icon='NONE'；原缺图构建阻碍已解决 |
| 独立测试打包 | 直接使用正式 flow.spec，在 scratch/flow-branding-dist 输出 Windows onedir 的 Flow/Flow.exe；不再需要临时补图，根目录图标保持删除 |
| 实际第三方业务 | 未消费 Google 生成积分，未使用真实语音密钥；Gladia 重定向测试使用模拟响应，浏览器测试为 DOM 回放，不代替 Chrome 与真实服务端到端测试 |
| 平台范围 | 当前机器为 Windows / Python 3.14.5，macOS 与 CI Python 3.11 的构建未执行；Inno Setup 安装器未执行 |

原来源测试使用 `chrome-extension://sample` 作为成功样本，现改为合法 32 字符扩展 ID，同时添加对非法 ID、HTTP、file、localhost、非标准端口和带路径 Origin 的拒绝测试。这是安全规则更新，不是跳过回归。更新模块删除后，相关 UI 测试移除了对已删除方法的 mock，并新增更新入口不存在的检查。

## 审核证据与逐文件覆盖

可复查数据保存在 `security-audit-evidence/`：

- [pip-audit.json](security-audit-evidence/pip-audit.json)：最终 Python 漏洞检查结果。
- [bandit.json](security-audit-evidence/bandit.json)：Python 静态扫描的原始 Low 项位置。
- [runtime-dependencies.json](security-audit-evidence/runtime-dependencies.json)：运行依赖实际版本和依赖声明。
- [official-package-metadata.json](security-audit-evidence/official-package-metadata.json)：官方 PyPI 元数据与 GitHub Action SHA 查询结果。
- [secret-scan-metadata.json](security-audit-evidence/secret-scan-metadata.json)：初始凭据扫描的匹配路径和类型，不含匹配值。
- [source-inventory.json](security-audit-evidence/source-inventory.json)：第一方代码和测试文件列表。

| 文件范围 | 逐文件检查重点及结论 |
| --- | --- |
| main.py、create_shortcut.py、启动FlowCue(本地测试版).bat | 配置迁移、错误日志、进程启动和快捷方式；没有发现把网络输入拼成 shell 的执行链。系统进程命令和日志仍依赖本机用户环境 |
| models/config_manager.py、storage_manager.py、template_manager.py | 环境变量、JSON 保存、模板加载和存储路径；明文保存按决定保留，模板作为普通数据处理，未发现 eval / pickle / YAML 不安全加载 |
| models/project_model.py、batch_model.py | 项目标识、字幕写入、批次保存和删除；修复路径问题 |
| services/plugin_server.py、pipeline_scheduler.py | 来源、消息解析、任务路由、点数和报告信任；修复格式边界，保留未鉴权风险 |
| services/downloader.py | Google Drive 域限制、目录项解析、文件名和 gdown 回退；已有解析后路径检查，未发现项目自动解压入口；第三方下载器回退和本地目录权限仍属于供应链与文件系统边界 |
| services/speech_extractor.py、text_processor.py | 自定义密钥头、返回 URL、ffmpeg、文本正则；修复网络密钥边界，未发现用户输入进入 shell=True 或 Python eval |
| services/video_checker.py、video_relocation.py | 文件匹配、移动、删除、越界和覆盖；修复项目匹配，复用完整文件无覆盖发布 |
| services/image_assignment.py、project_prompts.py | 图片分配规划、稳定标识、占位符和原子保存；没有动态代码执行入口 |
| views/main_window.py、project_detail_widget.py、hosted_mode_widget.py、batch_generate_tab.py、pipeline_tab_widget.py | 导入、调度、图片导出、报告和磁盘操作；重点修复资源与文件路径边界，删除更新方法 |
| views/import_dialog.py、settings_dialog.py、template_config_dialog.py、image_assignment_dialog.py、project_prompt_dialog.py | 剪贴板 HTML 解析、配置编辑、图片与模板数据；未发现 WebView、远程脚本或浏览器 JS 执行容器 |
| views/video_check_dialog.py、video_compare_widget.py、close_confirm_dialog.py | 本地媒体播放、手工确认与删除入口；媒体解析原生风险见 D04 |
| extension/background.js、content-isolated.js、manifest.json | 高权限消息来源和参数、下载、拖放、存储、权限范围；局部加固，整体隔离见 C13 |
| extension/injects/ui.js、flow-proxy.js、ui.css | DOM 模板、网络拦截、Trusted Types、WebSocket、状态缓存；修复 XSS 与全局策略，保留同页脚本信任和详细日志风险 |
| plugin_script_adapter.js | 用户脚本匹配范围、图片数据和 WebSocket；收窄匹配范围，不引入远程脚本 |
| tests 内所有第一方测试与 fixtures/flow-page.html | 现有业务回归、净化 DOM 快照和新增安全反例；工具依赖缺少锁文件已说明 |
| .github/workflows/release.yml、flow.spec、main.spec、flow_tool.spec、installer.iss | 可变 Action、权限、标签输入、打包资源和特权；固定 Action 与打包器，后续移除图标依赖并统一应用及产物名称为 Flow |

本项目没有发现 SQL / NoSQL 数据访问层、HTTP CORS 服务端、远程 WebView、Electron IPC、自动归档解压或用户模板执行引擎，因此这些类别未找到对应可利用入口。用户可控网址、下载和本地消息边界则按上文审查。已完成的修复只作用于源码和当前虚拟环境，尚未发布到远程或替换已分发版本。
