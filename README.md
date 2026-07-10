# IOL Tilt Labeler

用于人工点位标注并自动计算人工晶体与 A–B 参考线夹角的桌面工具。

> 测量结果是**二维 IOL 相对 A–B 参考线夹角**，不是三维临床 IOL tilt、环曲 IOL 旋转或偏心量。

## 下载 Windows 安装包

在 GitHub 的 **Releases** 页面下载最新版：

```text
IOL-Tilt-Labeler-Setup-x64-<版本号>.exe
```

支持 Windows 10 / 11 x64。安装到当前用户目录，不需要管理员权限；安装包目前没有代码签名，首次运行可能出现 Windows SmartScreen 提示。

## 使用

1. 启动 **IOL Tilt Labeler**。
2. 打开需要处理的 JPG、PNG、TIF、TIFF 或 BMP 图像。
3. 按界面提示完成点位标注并保存。
4. 程序会在原图所在目录的 `IOL_Tilt_Output/` 中写入结果：
   - `labels.json`：可继续编辑的点位；
   - CSV / XLSX：汇总结果；
   - PNG：带标注的导出图。

## 隐私

不要将患者原图、处理输出、`labels.json`、CSV/XLSX 或截图上传到 Issue、Release 或公开仓库。它们不属于本仓库的源码和安装包内容。

## 开发与发布

Windows 云端打包使用 GitHub Actions：

- 推送到 `main` 或提交 PR：自动生成可下载的 Actions artifact；
- 推送与安装器版本一致的标签（如 `v1.1.0`）：自动创建 GitHub Release 并上传安装包。

本地和 CI 构建细节见 [Windows打包说明.md](Windows打包说明.md)。
