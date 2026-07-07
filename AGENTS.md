# AGENTS.md - 手语通项目

本文件用于记录当前项目的长期有效约束、硬件事实、开发路线和高优先级决策。
若后续讨论与本文件冲突，以最新修改日期对应的内容为准。

## 协作约定

- 用户负责在 ESP-IDF PowerShell 中执行实际命令、编译、烧录和上板测试。
- 代理负责阅读代码、修改代码、收敛路线，并明确告诉用户下一步该执行什么命令。
- 当前开发仓库统一为 `hello_world`，不再把新功能迁回旧仓库开发。
- 调试结论一旦在板端验证成立，应尽量简短写回本文件，避免重复踩坑。
- 当前仓库只保留现路线直接需要的固件代码与路线文档；旧 demo 词级代码、旧云端 compose 代码、旧训练试验代码不再继续堆在主仓库根目录。

## 项目目标

手语通：基于 ESP32-P4 的听障人士双向翻译终端。

目标能力：
- 手语 -> 文字/语音
- 文字/语音 -> 手语动画

## 当前主路线（2026-06-05 起）

### 总体链路

当前项目主路线为：
`官方手型识别 -> 结构化动作/位置/双手关系基元 -> 端云联调按帧上传 -> 云端连续基元流匹配/RAG/句子级重排`

### 明确排除

以下路线不再作为当前主路线：
- 端侧整词直接分类
- 纯自然语言 RAG 自由问答式手语识别
- 继续围绕旧 demo 词模板长期堆规则

### 云端口径

云端方案不是“纯 RAG 问答”，而是：
`连续基元流匹配 + RAG 候选重排 + LLM 句子级重排/补全`

具体分工：
- 当前联调 v1：端侧先按帧上传 `primitive` 到 `/api/v1/stream/frame`
- 下一阶段：端侧再补“候选动作片段”切分与压缩上传
- 云端负责 rolling buffer、连续基元流匹配、RAG 候选重排与句子级输出
- LLM 只在候选集合上做句子级重排、补全和消歧
- LLM 不直接面对全词表自由生成

## 当前开发分层

### 第一层：官方手型层

当前优先先做稳官方手型分类层，类别为：
- `one`
- `two`
- `three`
- `four`
- `five`
- `like`
- `ok`
- `call`
- `dislike`

内部状态保留：
- `no_gesture`
- `no_hand`

### 第二层：基元层

基元设计以“先少而稳、再逐步扩展”为原则。

| 字段名 | v1 是否启用 | 取值枚举 | 生成依据 | 云端字段名 | 备注 |
|------|------|------|------|------|------|
| `hand_count` | Y | `{0,1,2}` | `HandDetect` 有效框数量 + 主副手筛选 | `hand_count` | 基元入口字段 |
| `dominant_shape` | Y | `{one,two,three,four,five,like,ok,call,dislike,no_gesture,no_hand}` | 官方分类输出 | `dominant_shape` | 主手手型 |
| `movement` | Y | `{hold,left_right,up_down,toward_away,open_close,repeat}` | 框中心点时序 + 框面积变化 + 短时状态机 | `movement` | 第一版先做粗粒度运动 |
| `location` | Y | `{signer_left,signer_center,signer_right} x {upper,middle,lower}` | 画面归一化位置 + `camera_* -> signer_*` 映射 | `location` | 端侧可见 `camera_*`，上传统一 `signer_*` |
| `dominant_side` | Y | `{signer_left,signer_right}` | 左右手相对位置 + 强制映射规则 | `dominant_side` | 固定场景：手语者正对摄像头 |
| `nondominant_shape` | Y | `{one,two,three,four,five,like,ok,call,dislike,no_gesture,no_hand}` | 双手 detect + 副手分类 | `nondominant_shape` | v1 直接支持双手 |
| `bimanual_relation` | Y | `{single_hand,dual_hand,same_shape,different_shape}` | 双手同时出现 + 左右手手型关系 | `bimanual_relation` | v1 直接支持双手 |
| `temporal_segment` | N(预留) | `{start,hold,transition,end}` | 连续帧分段 + 短时状态机 | `temporal_segment` | 词边界与动作阶段 |
| `orientation` | N(预留) | `{palm,back,side,forward}` | 关键点或轮廓方向特征 | `orientation` | 第一版暂缓 |
| `body_anchor_relative_location` | N(预留) | `{near_head,near_shoulder,near_chest,neutral_space}` | 手框相对人体锚点位置 | `body_anchor_relative_location` | 第一版暂缓 |

当前基元 v1 先强制落地这 7 个字段：
- `hand_count`
- `dominant_shape`
- `nondominant_shape`
- `bimanual_relation`
- `movement`
- `location`
- `dominant_side`

后续再按优先级打开：
- `temporal_segment`
- `orientation`
- `body_anchor_relative_location`

### 第三层：词表映射层

将《国家通用手语词表》的动作描述离线改写为基元组合模板，形成：
`基元模板 -> 词条`

### 第四层：句子级消歧层

一句话中每个词位可有多个候选，最终由语言模型基于上下文进行全句重排，选出最合理结果。

## 左右与空间位置硬规则

### 固定场景假设

固定使用场景为：
`手语者正对摄像头`

后续所有左右和空间位置语义都必须显式区分：
- `camera_*`
- `signer_*`

### 左右硬规则

- 画面中更靠左的手记为 `camera_left`
- 画面中更靠右的手记为 `camera_right`
- 在“手语者正对摄像头”场景下，强制映射为：
  - `camera_left = signer_right`
  - `camera_right = signer_left`

规则要求：
- 端侧日志可保留 `camera_*`
- 上传云端、词表模板、基元语义统一使用 `signer_*`

### 空间位置硬规则

第一版空间位置先基于画面归一化坐标：
- 水平：`left / center / right`
- 垂直：`upper / middle / lower`

但最终语义仍统一映射为 `signer_*`：
- `camera_left_zone -> signer_right_zone`
- `camera_right_zone -> signer_left_zone`
- `camera_center_zone -> signer_center_zone`

结论：
- 云端模板不使用 `camera_left/right`
- 云端模板统一使用 `signer_left/right/center`

## 运动基元 v1 建议

第一版优先做轻量运动基元，不追求 3D 精细建模：
- `hold`
- `left_right`
- `up_down`
- `toward_away`
- `open_close`
- `repeat`

第一版实现方式：
- 基于检测框中心点时序
- 基于框面积变化估计远近
- 基于短时状态机做片段压缩

## 双手关系基元 v1 建议

第一版优先保留：
- `single_hand`
- `dual_hand`
- `left_hand_shape`
- `right_hand_shape`
- `same_shape`
- `different_shape`

暂不在第一版强上复杂双手语义模板。

## 旧 demo 规则的状态

以下内容仍可作为历史调试经验保留，但不再代表当前主架构：
- `goodbye / thanks / hello / welcome` 词级互斥模板
- 基于特定单词的 decoder 特判
- 围绕旧 demo 词表堆叠的 `THUMB_UP / FIVE_OPEN / FIST` 词级规则

使用原则：
- 这些规则仅视为历史 demo/调试策略
- 不替代“官方手型层 -> 基元层 -> 云端检索层”的主路线

## 当前工程优先级

当前优先级按以下顺序推进：
1. 官方手型层稳定
2. 基元 v1 输出稳定
3. 词表模板离线改写
4. 云端候选召回
5. LLM 句子级重排
6. 手语动画反向链路完善

## 已确认的硬件与平台事实

### 硬件平台
- 开发板：ESP32-P4X-Function-EV-Board
- 主控：ESP32-P4 双核 RISC-V @ 400MHz
- 无线：板载 ESP32-C6
- 屏幕：7 寸 MIPI-DSI 1024x600
- 摄像头：SC2336，MIPI-CSI，RAW8

### 已验证关键事实
- LCD Reset 必须使用 `GPIO27`
- 摄像头 SCCB：`SCL=GPIO8`，`SDA=GPIO7`
- CSI 必须 RAW8 直通，不能直接走 RGB565 输出
- ISP 负责 RAW8 -> RGB565
- `CONFIG_CAMERA_SC2336=y` 必须启用，否则无法识别传感器
- Git Bash 不适合本项目 `idf.py` 工作流，统一用 ESP-IDF PowerShell
- 板端画面偏绿目前不阻塞手部识别开发

## 当前软件与调试事实

- 当前手型识别链路基于官方 `HandDetect + HandGestureRecognizer`
- 当前已经在板端反复验证：`five / one / two / like / ok / three` 已有可用基础
- 当前 `ok <-> three` 的主要问题已从“完全分不开”收敛到“姿态边界与输入形态一致性”
- 当前稳定器逻辑已做过一轮收紧：旧 stable 对 `no_hand` 的拖延释放已减弱

## 性能与调试原则

- 真实板端反馈优先于理论推断
- 若用户明确说“新版本效果更差”，优先回退或缩小改动范围
- 优先保护流畅度和可演示性，不做高复杂度但不可控的识别扩张
- 若识别 breadth 上去了但噪声显著增大，优先收缩而不是继续放宽

## 构建与烧录

在 ESP-IDF PowerShell 中执行：

```powershell
idf.py build
idf.py -p COM7 flash monitor
```

## 文档锚点

与当前路线直接相关的文档：
- `docs/【11-20260605-动作基元v1与云端检索方案】.md`
- `docs/手语通技术路线.md`
- `docs/手语基元表_四维度分析.md`

若未来有新路线更新，应优先更新本文件与上述路线文档，避免“代码已变、路线文档未变”。

