# Windows 10 / 11 安装包构建说明

本项目的 Windows 版本使用 **PyInstaller onedir + Inno Setup** 打包。请在 Windows 10 或 Windows 11 x64 电脑上完成构建；macOS 不能直接生成可验证的 Windows `.exe`。

## 1. 准备环境

1. 安装 [Python 3.11 x64](https://www.python.org/downloads/windows/)，安装时勾选 **Add Python to PATH**。
2. 安装 [Inno Setup 6](https://jrsoftware.org/isinfo.php)。
3. 打开 PowerShell，进入项目根目录后运行：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

如果 PowerShell 阻止激活脚本，在当前窗口先执行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

## 2. 构建应用目录

```powershell
pyinstaller --noconfirm --clean --distpath dist --workpath build packaging\windows\IOL-Tilt-Labeler.spec
```

构建结果应为：

```text
dist\IOL Tilt Labeler\IOL Tilt Labeler.exe
```

先双击或用 PowerShell 启动这个 EXE，确认主窗口、读图、保存和导出都正常，再制作安装包。

## 3. 制作安装包

若 Inno Setup 安装在默认位置：

```powershell
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\windows\IOL-Tilt-Labeler.iss
```

产物位于：

```text
release\windows\IOL-Tilt-Labeler-Setup-x64-1.2.0.exe
```

这是当前用户安装、无需管理员权限的内部测试版。首次运行可能有 Windows SmartScreen 提示，因为它尚未做代码签名。

## 4. GitHub Actions 自动构建与发布

仓库的 `.github/workflows/windows-release.yml` 会在 GitHub 的 Windows runner 上使用同一套 PyInstaller 和 Inno Setup 配置构建。

- 推送到 `main` 或创建面向 `main` 的 PR：生成可下载的 Actions artifact，保留 30 天；
- 推送版本标签（例如 `v1.2.0`）：自动创建 GitHub Release 并上传安装包和 `setup-manifest.txt`；
- 标签版本必须与 `packaging/windows/IOL-Tilt-Labeler.iss` 中的 `MyAppVersion` 完全一致，否则发布会失败。

发布新版本的顺序：先把 `MyAppVersion` 更新为目标版本并推送 `main`，确认云端构建成功，再在该提交创建并推送同名标签，例如：

```powershell
git tag v1.2.0
git push origin v1.2.0
```

`setup-manifest.txt` 中包含安装包 SHA-256，方便核对下载文件完整性。

## 5. Windows 验收清单

请在未安装 Python 的干净 Windows 10 和 Windows 11 x64 环境各验一次：

- 安装后通过开始菜单和可选桌面快捷方式启动；
- 打开中文名、包含空格的路径中的 JPG / PNG / TIF / TIFF / BMP；
- 完成标注，确认生成 `labels.json`、CSV、XLSX、标注 PNG；
- 点击“打开输出文件夹”“打开 Excel”“生成校准图”；
- 检查中文界面与标注文字没有变成方框；
- 验一遍新交互：拖动已有点微调、`Alt` + 点击删除、方向键微调、`Ctrl+Z` 撤销 / `Ctrl+Shift+Z` 重做；
- 验一遍放大镜、十字准星、亮度/对比度/反相，确认反相不影响导出角度；
- 切换 Windows 深色 / 浅色模式，确认界面配色跟随；
- 卸载后，安装目录被删除，原始图片目录下的结果仍保留；
- 对同一份已保存点位，核对 Windows 和 macOS 的角度结果一致。

## 6. macOS 版

macOS 侧用 `packaging/macos/IOL-Tilt-Labeler.spec` 打独立 `.app`，本地构建：

```bash
.venv/bin/python -m PyInstaller --noconfirm --clean \
  --distpath dist --workpath build packaging/macos/IOL-Tilt-Labeler.spec
```

云端构建见 `.github/workflows/macos-release.yml`（Intel runner，产物是 DMG，标签触发时自动挂到同一个 Release）。

## 注意

- 本工具结果应表述为 **“二维 IOL 相对 A–B 参考线夹角”**，不是三维临床 IOL tilt、环曲 IOL 旋转或偏心量。
- 安装包不应包含患者原图、历史案例、macOS `.app` 或旧 Tkinter 程序。
- 若要发给外部用户，请先用 Windows 代码签名证书为 EXE 和安装包签名，降低 SmartScreen 警告。
