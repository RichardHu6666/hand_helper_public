# Hand Helper

> 面向公共服务场景的双向手语辅助终端原型：用 ESP32-P4 端侧设备完成视觉采集与本地交互，用服务端连续流算法完成结构化手势理解，并探索从文本意图到手语提示动画的反向表达。

Hand Helper 关注的是一个真实沟通问题：在医院导引、服务窗口、社区办事、交通问询等场景中，听障人士和健听人群常常需要即时、连续、双向地交换信息。传统纸笔交流和人工转述虽然可用，但效率低、实时性弱，也难以形成自然的交替对话。

本项目希望探索一条更轻量、更可解释、更容易部署的路线：终端设备负责稳定采集、实时显示和初步结构化表达；服务端负责连续动作匹配、候选约束、语义恢复和调试分析。系统不是只做一个单手势分类器，而是尝试把“手语到文字”和“文字到手语提示”放到同一个交互终端里，形成可展示、可迭代的双向沟通原型。

本公开仓库是经过清理的功能快照。私人配置、部署地址、日志、模型文件和个人环境信息已移除或替换为占位符。

## 项目亮点

| 亮点 | 说明 |
|---|---|
| 双向交互原型 | 正向链路关注“手语动作 -> 文字反馈”，反向链路关注“文本意图 -> 手语提示动画”。 |
| 结构化手势表达 | 不直接把原始视频交给开放式生成模型，而是先提取手数、手型、空间位置、运动趋势和双手关系等动作基元。 |
| 受限候选语义恢复 | 服务端在受限词表和候选集合内做连续流匹配、重排和句子输出，降低自由生成的不确定性。 |
| 嵌入式端侧闭环 | ESP32-P4 端侧负责摄像头、ISP、LCD、Wi-Fi、LVGL UI 和实时状态显示。 |
| 可解释调试链路 | 检测框、手型结果、基元字段、session buffer、候选分数和输出状态都可以被检查和调试。 |
| 轻量反向动画路线 | 反向表达采用受限词表、动作片段和 2D 骨架提示动画，避免一开始就承诺复杂 3D 数字人。 |

## 功能展示

| 方向 | 展示能力 | 当前形态 |
|---|---|---|
| 手语到文字 | 摄像头采集手部动作，端侧生成结构化手势基元，服务侧连续匹配并返回词语/句子 | 固件与服务端分支已拆分公开 |
| 文字到手语提示 | 将受限文本意图映射为可视化手语提示动画 | 实验性路线，面向固定场景和受限词表 |
| 端侧交互 | ESP32-P4 驱动摄像头、LCD、Wi-Fi、状态显示和结果反馈 | 端侧固件位于 `local` 分支 |
| 服务侧识别 | FastAPI 接收 primitive stream，维护 session buffer，执行候选匹配、重排和状态输出 | 服务端位于 `server` 分支 |

## 系统架构

正向链路采用“端侧结构化表达 + 服务端连续流匹配”的思路：

```text
SC2336 camera / MIPI-CSI / ISP
        |
        v
Hand detection and gesture recognition
        |
        v
Gesture primitives
(hand count, shape, movement, location, relation)
        |
        v
Primitive stream upload
        |
        v
Rolling session buffer
        |
        v
Candidate matching / reranking / output state
        |
        v
Word and sentence feedback on device
```

反向链路采用“受限文本意图 + 动作片段库 + 轻量 2D 展示”的路线：

```text
Restricted text or speech intent
        |
        v
Text normalization / intent mapping
        |
        v
Gloss or action sequence
        |
        v
Reusable sign-animation clips
        |
        v
Lightweight 2D sign prompt on device
```

这条反向路线目前定位为实验性能力，适合固定场景和受限词表，不代表开放域自然语言到标准手语的完整自动生成。

## 技术路线

### 端侧固件

端侧运行在 ESP32-P4 平台上，主要承担实时交互和硬件链路工作：

- 通过 SC2336 MIPI-CSI 摄像头采集 RAW8 图像。
- 使用 ISP 将原始图像转换为可显示和可推理的 RGB565 数据。
- 组织手部检测、手型识别、主手选择、稳定化判定和显示刷新任务。
- 通过 FreeRTOS 将采集、检测、后处理、上传和 UI 显示拆成相对独立的实时流程。
- 基于 LVGL 在 7 寸屏幕上展示摄像头画面、状态信息、检测结果和文字反馈。

### 服务端匹配

服务端使用 FastAPI 提供 primitive stream 接口，面向连续手势片段而不是孤立单帧：

- 按 session 维护 rolling buffer。
- 从连续 primitive frames 中生成候选动作片段。
- 使用宽过滤、帧级对齐和候选评分缩小范围。
- 在候选集合内进行重排和句子级输出。
- 提供 debug/session 接口和测试脚本，便于观察匹配过程。

### 反向表达

反向链路的长期目标是让健听用户的文字或语音输入能被转换为听障用户可理解的视觉提示。当前公开说明中将它限定为受限场景路线：

- 文本先被规范化为短句意图。
- 系统在受限词表内映射到 gloss 或动作序列。
- 每个动作对应本地可复用动画片段。
- 端侧通过 2D 骨架或轻量动画同步展示原始文本和动作提示。

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

> A bidirectional sign-language assistance terminal prototype for public-service scenarios: an ESP32-P4 device handles visual capture and local interaction, while the service side performs continuous gesture-primitive stream matching and text feedback.

Hand Helper addresses a practical communication gap. In service counters, community help desks, hospital guidance, and transportation inquiry scenarios, deaf and hard-of-hearing users and hearing users often need immediate, continuous, two-way communication. Paper notes and manual relay can help, but they are slow, interruptive, and difficult to use for natural back-and-forth dialogue.

This project explores a lightweight, explainable, and deployable route. The device side focuses on stable capture, local display, and structured gesture representation; the service side focuses on continuous motion matching, candidate restriction, semantic recovery, and debugging. The goal is not to build a single isolated gesture classifier, but to place both sign-to-text and text-to-sign-prompt interaction in one extensible terminal prototype.

This public repository is a cleaned snapshot. Private configuration, deployment URLs, logs, model artifacts, and local environment details have been removed or replaced with placeholders.

## Highlights

| Highlight | Description |
|---|---|
| Bidirectional interaction prototype | The forward path focuses on sign gestures to text feedback; the reverse path focuses on text intents to visual sign prompts. |
| Structured gesture representation | Instead of sending raw video directly into an open-ended generator, the system first extracts primitives such as hand count, hand shape, motion, location, and bimanual relation. |
| Restricted-candidate semantic recovery | The service side performs stream matching, reranking, and sentence output within constrained vocabularies and candidate sets. |
| Embedded device loop | The ESP32-P4 device handles camera, ISP, LCD, Wi-Fi, LVGL UI, and real-time status feedback. |
| Explainable debugging path | Detection boxes, gesture classes, primitive fields, session buffers, candidate scores, and output state can be inspected. |
| Lightweight reverse-animation route | Reverse interaction uses limited vocabularies, curated action clips, and 2D sign prompts instead of starting with a complex 3D avatar. |

## Feature Showcase

| Direction | Capability | Current Form |
|---|---|---|
| Sign to text | Capture hand motion, generate structured gesture primitives on device, and match continuous streams on the service side | Public snapshots are split into firmware and service branches |
| Text to sign prompt | Map restricted text intents to visual sign prompt animations | Experimental route for controlled scenarios and limited vocabularies |
| Device interaction | ESP32-P4 drives camera, LCD, Wi-Fi, status display, and result feedback | Firmware lives on the `local` branch |
| Service recognition | FastAPI receives primitive streams, maintains session buffers, matches candidates, reranks results, and returns output state | Service code lives on the `server` branch |

## System Architecture

The forward path follows a device-side structured representation plus service-side continuous stream matching approach:

```text
SC2336 camera / MIPI-CSI / ISP
        |
        v
Hand detection and gesture recognition
        |
        v
Gesture primitives
(hand count, shape, movement, location, relation)
        |
        v
Primitive stream upload
        |
        v
Rolling session buffer
        |
        v
Candidate matching / reranking / output state
        |
        v
Word and sentence feedback on device
```

The reverse path is planned as restricted text intent plus reusable action clips and lightweight 2D rendering:

```text
Restricted text or speech intent
        |
        v
Text normalization / intent mapping
        |
        v
Gloss or action sequence
        |
        v
Reusable sign-animation clips
        |
        v
Lightweight 2D sign prompt on device
```

The reverse path is currently positioned as an experimental capability for controlled scenarios and limited vocabularies. It is not an open-domain natural-language-to-standard-sign-language generation system.

## Technical Route

### Device Firmware

The device firmware runs on ESP32-P4 and is responsible for real-time interaction and hardware integration:

- Captures RAW8 frames from an SC2336 MIPI-CSI camera.
- Uses the ISP pipeline to convert raw frames into RGB565 data for display and inference.
- Organizes hand detection, gesture recognition, dominant-hand selection, stability filtering, and display refresh.
- Splits capture, detection, post-processing, upload, and UI display into FreeRTOS tasks.
- Uses LVGL on a 7-inch screen to show camera preview, status, detection results, and text feedback.

### Service-Side Matching

The service side exposes FastAPI primitive stream endpoints and works on continuous gesture segments rather than isolated frames:

- Maintains a rolling buffer for each session.
- Generates candidate motion spans from primitive frames.
- Uses wide filtering, frame-step alignment, and candidate scoring to narrow the search space.
- Performs reranking and sentence-level output within candidate sets.
- Provides debug/session endpoints and test scripts for observing the matching process.

### Reverse Expression

The long-term reverse path aims to convert text or speech from hearing users into visual prompts that deaf and hard-of-hearing users can understand. In this public description, it is intentionally scoped to restricted scenarios:

- Text is normalized into short intents.
- The system maps intents to glosses or action sequences within a limited vocabulary.
- Each action maps to a reusable local animation clip.
- The device displays the original text and a synchronized lightweight 2D sign prompt.

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

