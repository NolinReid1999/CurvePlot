# CurvePlot 1.0.0 build1

面向科研的数据整理、绘图、拟合与分析桌面应用。

主开发者：**NolinReid**。开发协作：Codex（OpenAI）。本项目基于 [Tailor](https://github.com/davidfokkema/tailor)，保留 David Fokkema 与贡献者的署名，以 **GPL-3.0-or-later** 分享，详见 [LICENSE](LICENSE) 和 [UPSTREAM.md](UPSTREAM.md)。

## 功能

- CSV / Excel 导入、列角色与名称、表格编辑、排除坏点和撤销。
- 单曲线、多曲线、左右Y轴、误差棒、坐标轴与智能刻度。
- 文字、图片及图例编辑、局部放大、断轴。
- 内置与自定义拟合、Gaussian / Lorentzian 多峰拟合、置信带与预测带。
- 描述统计、基础数学、平滑校正、区域分析、FFT / 常用滤波、包络及重复测量。
- 分组 / 堆叠 / 百分比柱图、三维图与组图。
- 可编辑 `.cur` 工程、多项目及普通图多窗口；PNG / SVG / PDF 导出。

## 下载和安装

在本仓库的 Releases 中下载 `Curve-1.0.0-build1-macOS-arm64.dmg`，打开后把 Curve 拖入 Applications。

当前安装包适用于 **Apple Silicon macOS**，采用临时签名，尚未通过 Apple 公证；首次打开可能出现 macOS 安全提示。当前没有 Windows EXE，未验证 Intel Mac / Windows 的发布包。

## 从源码运行

建议使用 Python 3.12，在此目录执行：

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python tools/macos_entry.py
```

Windows 的虚拟环境激活命令为 `.venv\Scripts\Activate.ps1`；跨平台源码运行仍需单独验证。启动脚本名称沿用历史文件名，实际调用 Curve 桌面入口。`pyproject.toml` 内的 `tailor 2.1.4` 是上游后端包身份，Curve 界面版本为 **1.0.0 build1**，两者独立。

## 构建 macOS DMG

```sh
python -m pip install -r requirements-build.txt
python tools/build_macos.py
```

构建使用现有 PyInstaller spec，包含应用图标、手册、拖入 Applications 的背景和链接。构建脚本仅输出到 `dist/` 与 `build/`，不会安装应用。第三方构建依赖见 `pyproject.toml`、`uv.lock` 和 `requirements-build.txt`。

## 本次修复与验证

修复组图刻度区域反复缩放造成的闪烁，以及多窗口恢复局部放大时功能区位置变化引发的异常。必要核心流程及扩大范围复查已完成；扩大复查224项通过，覆盖数值、更多模型/处理、坐标轴联动、高级绘图和重点主题显示。测试范围和性能限制见 [验证摘要](docs/VALIDATION.md) 与 [已知限制](docs/KNOWN_ISSUES.md)，不代表所有操作组合均已验收。

[快速开始](docs/QUICK_START.md) · [更新说明](CHANGELOG.md) · [参与贡献](CONTRIBUTING.md)。仓库附带的旧版手册供参考，部分界面名称与当前版本不同。
