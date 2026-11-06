# CurvePlot

面向科研的数据整理、绘图、拟合与分析桌面应用。主开发者：**NolinReid**；开发协作：Codex（OpenAI）。

[下载最新版本](https://github.com/NolinReid1999/CurvePlot/releases/latest) · [更新日志](CHANGELOG.md) · [快速开始](docs/QUICK_START.md) · [已知限制](docs/KNOWN_ISSUES.md)

## 功能概览

- **数据表格**：CSV / Excel导入、列角色与名称、单元格编辑、多列操作、坏点排除和撤销。
- **科研绘图**：单曲线、多曲线、左右Y轴、误差棒、图例、字体与线条偏好；独立调整四个坐标轴及智能刻度。
- **图形编辑**：文字与图片标注、局部放大、断轴、图形边距和对象位置调整。
- **数据拟合**：内置与自定义模型、Gaussian / Lorentzian单峰与多峰、初值和参数约束、残差及置信带/预测带。
- **数据处理**：描述统计、基础数学、平滑校正、区域分析、FFT及常用滤波、SciPy包络、重复测量汇总。
- **高级绘图**：分组/堆叠/百分比柱状图、三维绘图、组图与子图布局。
- **工程与导出**：可编辑 `.cur` 工程、多项目、普通图多窗口、自动恢复及 PNG / SVG / PDF 导出。
- **个性设置**：深浅色外观、默认格式、导出与保存位置、性能选项、诊断日志，以及GitHub正式版本更新检测。

## 最近更新

**1.0.2 · 2026-11-06**：与1.0.1功能一致，版本号递增，用于验证正式Release更新提示流程；没有新增算法或额外功能。

**1.0.1 · 2026-11-06**：新增异步联网更新检测；重排轴显示控制，修复零长度刻度残留；补齐部分默认格式的保存与旧配置兼容，并更换更新图标。详见[完整更新日志](CHANGELOG.md)。

## 安装与更新

在[Releases](https://github.com/NolinReid1999/CurvePlot/releases)下载 `Curve-1.0.2-macOS-arm64.dmg`，打开后将Curve拖入Applications。

当前安装包适用于 **Apple Silicon macOS**，采用ad-hoc签名，尚未通过Apple公证；未提供Windows EXE或Intel Mac安装包。

启动后后台检查最新正式Release，每24小时最多自动检查一次；也可在设置或快捷栏手动检查。“稍后提醒”对同一版本静默7天，手动检查不受限制。下载按钮只打开Release页面，**不会自动替换或执行App**。更新功能不发送工程和实验数据。

## 源码运行与构建

建议Python3.12，安装本项目后运行：

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python tools/macos_entry.py
```

macOS构建：`python -m pip install -r requirements-build.txt`，再运行 `python tools/build_macos.py`，输出到 `dist/`，不会自动安装。产品版本只修改 `src/tailor/version.py`；`pyproject.toml`内的Tailor后端包版本与产品版本独立。

## 说明与许可

大数据及高级绘图仍可能有等待，旧手册与部分界面名称存在差异；专项测试不代表所有设备和操作组合均已验收。详见[验证摘要](docs/VALIDATION.md)。

CurvePlot基于 [Tailor](https://github.com/davidfokkema/tailor)，保留David Fokkema及贡献者署名，按 **GPL-3.0-or-later** 开源。参见 [LICENSE](LICENSE)、[UPSTREAM.md](UPSTREAM.md) 和 [上游README](README.upstream.md)。
