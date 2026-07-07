# Hand Helper

> 一个面向双向手语辅助交互的开源原型：端侧负责摄像头、显示与交互，服务侧负责连续手势基元流匹配与文字反馈。

Hand Helper 探索的是一条轻量、可解释、可逐步扩展的手语辅助终端路线。项目将 ESP32-P4 终端、摄像头、屏幕和服务端连续流算法组合起来，演示“手语动作到文字反馈”和“文本意图到手语提示动画”的基本交互形态。

本公开仓库是经过清理的功能快照。私人配置、部署地址、日志、模型文件和个人环境信息已移除或替换为占位符。

## 功能展示

| 方向 | 展示能力 | 当前形态 |
|---|---|---|
| 手语到文字 | 摄像头采集手部动作，端侧生成结构化手势基元，服务侧连续匹配并返回词语/句子 | 固件与服务端分支已拆分公开 |
| 文字到手语提示 | 将受限文本意图映射为可视化手语提示动画 | 实验性路线，面向固定场景和受限词表 |
| 端侧交互 | ESP32-P4 驱动摄像头、LCD、Wi-Fi、状态显示和结果反馈 | 端侧固件位于 `local` 分支 |
| 服务侧识别 | FastAPI 接收 primitive stream，维护 session buffer，执行候选匹配、重排和状态输出 | 服务端位于 `server` 分支 |

## 架构概览

```text
ESP32-P4 camera + display
        |
        v
Hand detection / gesture primitives
        |
        v
Primitive stream upload
        |
        v
Service-side rolling buffer
        |
        v
Candidate matching / reranking / output state
        |
        v
Word and sentence feedback
```

反向链路的工程方向是：

```text
Restricted text intent
-> gloss / action sequence
-> reusable sign-animation clips
-> lightweight 2D sign prompt on device
```

该部分目前被定位为受限场景下的实验性能力，不代表开放域自然语言到标准手语的完整自动生成。

## 分支说明

| 分支 | 内容 | 适合查看什么 |
|---|---|---|
| [`local`](../../tree/local) | ESP32-P4 端侧固件快照 | 摄像头、ISP、LCD、Wi-Fi、手势基元生成、上传与本地显示 |
| [`server`](../../tree/server) | FastAPI 服务端快照 | primitive stream API、连续动作匹配、候选重排、session debug 和测试脚本 |
| [`main`](../../tree/main) | 项目公开首页 | 项目介绍、能力边界和分支导航 |

## 快速入口

查看端侧固件：

```text
git checkout local
```

查看服务端代码：

```text
git checkout server
```

或者直接在 GitHub 页面切换到 `local` / `server` 分支阅读对应 README。

## 公开快照说明

这个仓库只保留适合公开展示的代码和说明：

- 已移除私人 Wi-Fi、密码、部署地址和本机路径。
- 已移除开发日志、实验临时文件和非公开材料。
- 数据、模型和部署配置仅保留必要的示例或占位符。
- 各分支以无历史快照方式发布，不包含私有仓库提交历史。

## 当前边界

Hand Helper 仍是研究与工程原型：

- 不是生产级医疗、政务或应急沟通系统。
- 不承诺开放域手语识别或标准手语自动生成。
- 反向手语动画仍需要受限词表、动作资产和人工校验。
- 真实部署前需要进一步的安全、稳定性、准确率和领域审查。

## License

License to be added.

---

# Hand Helper

> An open prototype for bidirectional sign-language assistance: the device side handles camera, display, and interaction, while the service side handles continuous gesture-primitive stream matching and text feedback.

Hand Helper explores a lightweight, explainable, and extensible path for sign-language assistance terminals. It combines an ESP32-P4 device, camera, display, and service-side stream algorithms to demonstrate the interaction loop from sign gestures to text feedback, and from restricted text intents to visual sign prompts.

This public repository is a cleaned snapshot. Private configuration, deployment URLs, logs, model artifacts, and local environment details have been removed or replaced with placeholders.

## Feature Showcase

| Direction | Capability | Current Form |
|---|---|---|
| Sign to text | Capture hand motion, generate structured gesture primitives on device, and match continuous streams on the service side | Public snapshots are split into firmware and service branches |
| Text to sign prompt | Map restricted text intents to visual sign prompt animations | Experimental route for controlled scenarios and limited vocabularies |
| Device interaction | ESP32-P4 drives camera, LCD, Wi-Fi, status display, and result feedback | Firmware lives on the `local` branch |
| Service recognition | FastAPI receives primitive streams, maintains session buffers, matches candidates, reranks results, and returns output state | Service code lives on the `server` branch |

## Architecture Overview

```text
ESP32-P4 camera + display
        |
        v
Hand detection / gesture primitives
        |
        v
Primitive stream upload
        |
        v
Service-side rolling buffer
        |
        v
Candidate matching / reranking / output state
        |
        v
Word and sentence feedback
```

The reverse-interaction direction is planned as:

```text
Restricted text intent
-> gloss / action sequence
-> reusable sign-animation clips
-> lightweight 2D sign prompt on device
```

This part is currently positioned as an experimental capability for restricted scenarios. It is not an open-domain natural-language-to-standard-sign-language generation system.

## Branch Guide

| Branch | Contents | What to Inspect |
|---|---|---|
| [`local`](../../tree/local) | ESP32-P4 firmware snapshot | Camera, ISP, LCD, Wi-Fi, gesture primitives, upload path, and local UI |
| [`server`](../../tree/server) | FastAPI service snapshot | Primitive stream API, continuous gesture matching, candidate reranking, session debug, and tests |
| [`main`](../../tree/main) | Public project landing page | Project overview, boundaries, and branch navigation |

## Quick Start

To inspect the device firmware:

```text
git checkout local
```

To inspect the service-side code:

```text
git checkout server
```

You can also switch to the `local` or `server` branch directly on GitHub and read the branch-specific README.

## Public Snapshot Notice

This repository keeps only material suitable for a public code snapshot:

- Private Wi-Fi credentials, deployment URLs, and local paths were removed.
- Development logs, temporary experiments, and non-public materials were removed.
- Data, models, and deployment configuration are kept only as necessary examples or placeholders.
- Branches are published as history-free snapshots and do not include private repository commit history.

## Current Boundaries

Hand Helper is still a research and engineering prototype:

- It is not a production-grade medical, government, or emergency communication system.
- It does not claim open-domain sign-language recognition or standard sign-language generation.
- Reverse sign animation still requires limited vocabularies, curated animation assets, and human review.
- Real deployment requires further security, stability, accuracy, and domain validation.

## License

License to be added.
