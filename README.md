# Hand Helper

**Hand Helper** is an experimental bidirectional sign-language assistance prototype. It combines an ESP32-P4 edge device with a lightweight service-side stream matcher to explore a practical path from camera-based gesture primitives to text feedback, and from text intent to visual sign prompts.

**Hand Helper** 是一个实验性的双向手语辅助终端原型。项目使用 ESP32-P4 端侧设备和轻量服务端连续流匹配能力，探索从摄像头手势基元到文字反馈、以及从文本意图到可视化手语提示的工程路线。

## Branches / 分支说明

| Branch | Purpose | 说明 |
|---|---|---|
| `local` | ESP32-P4 firmware snapshot | 端侧固件快照，包含摄像头、显示、手势基元生成和上传链路。 |
| `server` | FastAPI stream matcher snapshot | 服务端快照，包含 primitive stream 接口、连续动作匹配、候选重排和调试工具。 |
| `main` | Public project overview | 公开仓库首页，仅保留项目介绍和分支导航。 |

## Architecture / 架构概览

```text
ESP32-P4 camera + display
-> hand detection and gesture primitives
-> primitive stream upload
-> service-side rolling buffer and matcher
-> word / sentence feedback
```

For reverse interaction, the project direction is to map restricted text intents to reusable sign-animation clips and render lightweight 2D sign prompts on the device. This part is experimental and intended for controlled scenarios rather than open-domain sign-language generation.

反向交互方向是将受限文本意图映射为可复用的手语动作片段，并在终端上渲染轻量 2D 手语提示动画。该部分属于实验性能力，面向受控场景，不代表开放域手语自动生成系统。

## Quick Start / 快速入口

- For firmware details, switch to the [`local`](../../tree/local) branch.
- For service-side details, switch to the [`server`](../../tree/server) branch.

- 查看端侧固件，请切换到 [`local`](../../tree/local) 分支。
- 查看服务端代码，请切换到 [`server`](../../tree/server) 分支。

## Public Snapshot Notice / 公开快照说明

This repository is a cleaned public snapshot. Private deployment addresses, local credentials, development logs, datasets, model artifacts, and personal configuration have been removed or replaced with placeholders.

本仓库是经过清理的公开快照。私人部署地址、本地凭据、开发日志、数据集、模型文件和个人配置已被移除或替换为占位符。

## Status / 状态

This is a research and engineering prototype. The current public branches are intended for reference, reproduction, and continued development. Production use requires additional validation, security hardening, and domain-specific review.

这是一个研究与工程原型。当前公开分支主要用于参考、复现和继续开发。若用于生产环境，还需要进一步验证、安全加固和领域专家审查。

## License / 许可证

License to be added.
