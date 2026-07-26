# IOL Tilt Labeler

用于人工点位标注并自动计算人工晶体与 A–B 参考线夹角的桌面工具，macOS 与 Windows 通用。

> 测量结果是**二维 IOL 相对 A–B 参考线夹角**，不是三维临床 IOL tilt、环曲 IOL 旋转或偏心量。

## 下载

在 GitHub 的 **Releases** 页面下载最新版：

```text
IOL-Tilt-Labeler-Setup-x64-<版本号>.exe    # Windows 10 / 11 x64
IOL倾斜标注-<版本号>.dmg                     # macOS 11+（Intel，Apple Silicon 走 Rosetta）
```

Windows 安装到当前用户目录，不需要管理员权限。两个包目前都没有代码签名：
Windows 首次运行可能出现 SmartScreen 提示；macOS 若提示「已损坏 / 无法验证开发者」，执行一次：

```bash
xattr -dr com.apple.quarantine "/Applications/IOL 倾斜标注.app"
```

## 使用

1. 启动软件，打开图片文件夹，或直接把图片/文件夹拖进窗口（支持 JPG、PNG、TIF、TIFF、BMP）。
2. 第 2 步点 A、B 两点，第 3/4 步分别点晶体前、后表面各 3 点以上，软件自动拟合出 IOL 轴。
3. 拖动已有点可微调，`⌥`/`Alt` + 点击删除，方向键微调 1 px，`⌘Z`/`Ctrl+Z` 撤销。
4. 「保存并下一张」写入结果。

程序会在原图所在目录的 `IOL_Tilt_Output/` 中写入：

- `labels.json`：可继续编辑的点位；
- CSV / XLSX：汇总结果（四列：IOL轴角度、A-B角度、最终夹角、备注）；
- `annotated/`：带标注的导出图。

详细用法见 [使用说明](00_工具程序/IOL_Tilt_Labeler_使用说明.md)。

## 隐私

不要将患者原图、处理输出、`labels.json`、CSV/XLSX 或截图上传到 Issue、Release 或公开仓库。
它们不属于本仓库的源码和安装包内容。

## 开发

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python 00_工具程序/iol_tilt_labeler_qt.py     # 运行
.venv/bin/python tests/smoke_test.py                    # 冒烟测试（39 项）
.venv/bin/python tools/make_icons.py                    # 重新生成图标
```

源码结构：

| 文件 | 作用 |
| --- | --- |
| `00_工具程序/iol_tilt_labeler_qt.py` | 主窗口、交互、导出 |
| `00_工具程序/iol_core.py` | 圆拟合、角度计算、Excel / 标注图输出 |
| `00_工具程序/canvas.py` | 影像画布：缩放、取点、拖点、放大镜 |
| `00_工具程序/theme.py` | 浅色 / 深色配色与样式表 |
| `00_工具程序/platform_utils.py` | 跨平台路径、字体 |

调试参数：`--demo` 注入示例点位，`--shot <path>` 截图后退出，环境变量 `IOL_FORCE_THEME=dark|light` 强制主题。

## 发布

云端构建走 GitHub Actions：

- 推送到 `main` 或提交 PR：生成 Windows 安装包 artifact；
- 推送与 `APP_VERSION` 一致的标签（如 `v1.2.0`）：自动创建 Release，并上传 Windows 安装包与 macOS DMG，附 SHA-256 manifest。

本地构建细节见 [Windows打包说明.md](Windows打包说明.md)。macOS 本地构建：

```bash
.venv/bin/python -m PyInstaller --noconfirm --clean \
  --distpath dist --workpath build packaging/macos/IOL-Tilt-Labeler.spec
```
