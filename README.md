# Flow - AI口播视频批量制作与自动化生成工具

Flow 是一款面向创作者与出海口播视频制作的批量辅助工具，深度集成 Google Labs Flow 平台，支持视频分段提示词生成、多账号自动调度并发、原生批量图片拖拽上传与视频自动化下载归位。

应用内自动检查、下载和安装更新功能已移除。升级请手动从本项目的 GitHub Releases 获取发布包。

## 如何发布新版本

本项目在 GitHub Actions 上构建和发布，无需在本地安装打包工具或生成可执行文件。将代码（包括 `.github/workflows/release.yml`、`scripts/`、`extension/` 和测试文件）提交到 GitHub 后，推送版本 Tag 即会启动构建。

成功后，同一个 Release 会提供三个下载包，以 `v1.8.1` 为例：

| 下载文件 | 内容 |
| --- | --- |
| `Flow-windows-v1.8.1.zip` | Windows x64 便携版，解压后运行 `Flow/Flow.exe`，整个目录需一起保留 |
| `Flow-macos-v1.8.1.zip` | 两个独立原生版本：`Flow-macos/Apple Silicon/Flow.app` 适用于 M 系列 Mac，`Flow-macos/Intel/Flow.app` 适用于 Intel Mac；选择对应版本运行 |
| `Flow-extension-v1.8.1.zip` | 独立浏览器插件，Windows 和 macOS 共用；解压后在 `chrome://extensions/` 加载包含 `manifest.json` 的文件夹 |

macOS 两个版本分别在 GitHub 的 Apple Silicon 和 Intel 运行器上构建，并合并为一个下载包；这不是一个 Universal 2 应用。Windows 版在 Windows 运行器上构建。运行器对应关系见 [GitHub 官方清单](https://github.com/actions/runner-images)。桌面应用与插件均使用 Flow 名称，不包含自定义应用图标。

macOS 应用仅执行临时签名，尚未配置 Apple Developer ID 签名与公证，首次打开可能被系统阻止，相关要求见 [Apple 说明](https://support.apple.com/en-ie/102445)。旧版流水线的 Windows 原生文件对话框填写、Win32 窗口定位在 macOS 不适用；Mac 请使用浏览器插件的上传功能与全局托管模式。

### 发布步骤

#### 1. 确保代码已提交并推送

在发布之前，确保你的所有代码改动已经提交并推送到 GitHub：

先将 `version.py` 中的版本号更新为准备发布的版本，再创建相同版本的 Tag。

```bash
# 查看当前状态
git status

# 添加所有改动
git add .

# 提交改动（把"你的改动说明"替换成实际的描述）
git commit -m "你的改动说明"

# 推送到 GitHub
git push origin main
```

#### 2. 创建版本 Tag

Git Tag 是一个版本标记，用于标识发布的版本号。版本号格式为 `v主版本.次版本.修订版本`，例如 `v1.0.0`、`v1.1.0`、`v2.0.0`。

```bash
# 创建一个新的版本 tag（将 v1.8.1 替换为你想要的版本号）
git tag -a v1.8.1 -m "Release version 1.0.1"
```

#### 3. 推送 Tag 触发自动构建

```bash
# 推送 tag 到 GitHub（这会自动触发 CI 构建）
git push origin v1.8.1
```

推送后，GitHub Actions 会自动执行以下操作：
1. 在 Windows、Apple Silicon Mac、Intel Mac 三种运行器上测试并构建桌面应用，同时独立打包插件。
2. 等待全部任务成功，将两个 Mac 版本合并为一个压缩包，核对最终恰好有三个下载包。
3. 生成构建来源证明（Attestation），创建 Release 并上传三个下载包。来源证明不等同于 Apple Developer ID 签名。

如果已有版本 Tag，也可以在 GitHub 的 **Actions → Build and Release Flow → Run workflow** 中填写现有 Tag 手动构建。填写的 Tag 必须已经存在，且对应提交包含这份工作流与打包脚本。仅上传普通分支代码不会自动发布版本。

#### 4. 查看构建结果

- 构建进度：访问项目的 **Actions** 页面查看
- 发布结果：访问项目的 **Releases** 页面查看已发布的文件

### 版本号说明

| 版本号格式 | 什么时候用 | 示例 |
|-----------|-----------|------|
| `vX.0.0` | 重大更新、不兼容改动 | `v2.0.0` |
| `vX.Y.0` | 新增功能 | `v1.1.0` |
| `vX.Y.Z` | 修复 bug | `v1.8.1` |

### 如果构建失败怎么办

1. 访问项目的 **Actions** 页面查看错误日志
2. 修复代码问题
3. 删除失败的 tag 并重新创建：

```bash
# 删除本地 tag
git tag -d v1.8.1

# 删除远程 tag
git push origin :refs/tags/v1.8.1

# 修复问题后，重新创建并推送
git tag -a v1.8.1 -m "Release version 1.0.1"
git push origin v1.8.1
```
