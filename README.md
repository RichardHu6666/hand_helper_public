# 手语通端侧固件

`hello_world` 是当前手语通项目的端侧主开发仓库，运行在 ESP32-P4X-Function-EV-Board 上。

当前正向链路已经从“本地手型识别调试”推进到“端侧基元实时输出 + 云端连续基元流匹配 + 词/句回传显示”：

```text
Camera / ISP
-> HandDetect
-> HandGestureRecognizer
-> local primitive state
-> app_cloud frame upload
-> cloud stream decoder / RAG rerank / sentence composer
-> Word / Sentence display
```

## 当前正向链路

### 1. 端侧视觉与基元生成

端侧仍以官方模型作为底座：

```text
camera frame
-> app_hand_detect_run()
-> duplicate/filter/stable primitive boxes
-> app_hand_gesture_run()
-> primitive state
```

当前本地基元字段为：

```text
hand_count
dominant_side
location
movement
bimanual_relation
dominant_shape
nondominant_shape
```

屏幕本地调试区显示：

```text
Hands / Side / Loc / Move / Rel / Shape
```

基元生成采用“快路径优先”：

- `Hands / Side / Loc / Move / Rel` 跟随检测框实时更新。
- `Shape` 使用手型分类稳定缓存，可以慢一拍。
- 本地基元输出不等待云端响应。

### 2. 端侧上传

端侧在 primitive 发布点直接提交 cloud frame，不通过 UI snapshot 轮询。

代码入口：

```text
main/app_ai_pipeline.c -> publish_primitive_output(...)
main/app_cloud.c       -> app_cloud_submit_frame(...)
```

上传策略：

- 仅在 `hand_count > 0` 时上传。
- cloud task 独立运行，不阻塞 AI pipeline。
- active 动作期间默认以 250 ms 为起点采样上传，但会根据最近一次 HTTP 往返耗时自动节流，避免慢 HTTPS 导致旧帧堆积。
- 静止 `hold` 且字段不变时默认每 1000 ms 上传一次心跳。
- primitive 关键字段变化时立即上传：`movement / location / dominant_shape / hand_count / bimanual_relation`。
- 上传队列固定长度为 24，发送保持 FIFO 顺序。
- 实际 backlog 限制为最近约 6 帧；超过后丢最旧帧，避免几秒前的旧状态继续污染云端。
- HTTPS 请求超时默认 10000 ms。
- 上传前会做一层窄范围归一化：横向运动 `left_right` 的瞬时左右位置会归并到同一垂直带的 `signer_center_*`，手型短暂掉成 `no_hand/no_gesture` 时会沿用最近稳定具体手型，运动期间垂直带短暂抖动会沿用最近稳定带。该归一化只影响云端匹配，不改变屏幕上的本地原始基元显示。
- cloud 日志会输出 `q / http_ms / err / http`，用于判断网络是否拖慢上传。

请求端点：

```text
POST {CLOUD_BASE_URL}/api/v1/stream/frame
```

当前默认云端地址：

```text
<YOUR_SERVER_URL>
```

请求 JSON：

```json
{
  "session_id": "esp32p4-dev-001",
  "timestamp": "260702-000001-001",
  "primitive": {
    "hand_count": 1,
    "dominant_side": "signer_right",
    "location": "signer_center_upper",
    "movement": "left_right",
    "bimanual_relation": "single_hand",
    "dominant_shape": "five",
    "nondominant_shape": "no_hand"
  },
  "debug": false
}
```

时间戳格式固定为：

```text
YYMMDD-HHMMSS-XXX
```

其中 `YYMMDD` 来自 `CONFIG_CLOUD_TIMESTAMP_DATE_YYMMDD`，`HHMMSS` 使用开机后 uptime 换算，`XXX` 为同秒递增序号。该时间戳只要求同一 session 内可排序，不要求真实北京时间。

### 3. 云端匹配

云端当前主逻辑不属于本仓库，但端侧协议已与它对齐。云端正向算法为：

```text
primitive frame stream
-> session rolling buffer
-> dynamic span generation
-> primitive wide filter
-> frame-step alignment
-> candidate scoring
-> RAG rerank
-> state machine collecting / pending / confirmed
-> sentence fallback or LLM composer
```

当前使用 lite 词库作为候选库。词库每条包含词目、动作描述、检索文本和 `primitive_text`。云端先用 primitive 规则做宽过滤，再在候选集合内用 embedding/RAG 做小权重重排，最后输出词级结果和句子级结果。

重要约束：

- primitive 冲突优先于 RAG 相似度。
- RAG 只做候选重排，不直接绕过 primitive 规则。
- LLM 只面对候选集合，不直接面对全词表自由生成。

### 4. 云端响应与端侧显示

端侧只解析正式稳定字段：

```json
{
  "status": "confirmed",
  "result": {
    "word_base": "厕所",
    "confidence": 0.82
  },
  "sentence": {
    "text": "厕所",
    "status": "fallback"
  },
  "last_confirmed": {
    "word_base": "厕所",
    "sentence": "厕所",
    "timestamp": "260702-000001-006"
  }
}
```

端侧显示区：

```text
Cloud: ...
Word: ...
Sentence: ...
```

响应语义：

- `collecting`：当前还没有有效候选，端侧显示 `Word: - / Sentence: -`。
- `pending`：云端已有当前候选但尚未确认，可返回当前 top1。
- `confirmed`：云端确认当前词，端侧显示 `result.word_base` 与 `sentence.text`。
- `last_confirmed`：历史信息，端侧 v1 不读取，避免污染当前结果。
- HTTP/JSON 错误：端侧保留旧显示并标记 `stale`，屏幕显示 `Word(old)` / `Sentence(old)`。

## 联网与配置

联网路线固定为：

```text
ESP32-P4 + 板载 ESP32-C6 ESP-Hosted
```

工程策略为：

```text
依赖常驻，逻辑开关
```

也就是说，hosted / Wi-Fi / HTTP 依赖默认作为工程底座存在，`CLOUD_ENABLE` 只控制是否启动 Wi-Fi 和上传逻辑，不控制依赖是否参与编译。

当前默认配置：

```text
CONFIG_CLOUD_ENABLE=y
CONFIG_WIFI_SSID="<YOUR_WIFI_SSID>"
CONFIG_WIFI_PASSWORD="<YOUR_WIFI_PASSWORD>"
CONFIG_CLOUD_BASE_URL="<YOUR_SERVER_URL>"
CONFIG_CLOUD_SESSION_ID="esp32p4-dev-001"
CONFIG_CLOUD_HTTP_TIMEOUT_MS=10000
CONFIG_CLOUD_UPLOAD_SAMPLE_MS=250
CONFIG_CLOUD_UPLOAD_IDLE_HEARTBEAT_MS=1000
CONFIG_CLOUD_NORMALIZE_GRACE_MS=1500
CONFIG_CLOUD_ACTIVE_MOVEMENT_GRACE_MS=800
CONFIG_CLOUD_FRAME_QUEUE_LEN=24
CONFIG_CLOUD_DEBUG_LOG=n
```

配置入口：

```text
idf.py menuconfig
-> Cloud Link
```

## UI 与字体

屏幕左上角黑色面板由共享布局常量控制：

```text
main/app_ui_layout.h
```

该常量同时用于：

- LVGL 面板位置和尺寸。
- 相机画面中黄/绿框的保护区裁剪。

中文显示使用项目专用 LVGL 字体：

```text
main/fonts/lv_font_sign_ui_14.c
```

字体生成脚本：

```powershell
python tools\font\generate_sign_ui_font.py
```

字体校验：

```powershell
python tools\font\generate_sign_ui_font.py --check-only
```

字体字符来源：

- `data/vocab_pipeline/hand_language_vocabulary_lite.sqlite3`
- `tools/font/sign_ui_extra_chars.txt`

如果 lite 词库或额外中文字符表变化，需要重新生成字体。

## 构建与烧录

在 ESP-IDF PowerShell 中执行：

```powershell
python tools\font\generate_sign_ui_font.py --check-only
idf.py build
idf.py -p COM7 flash monitor
```

保存板端日志：

```powershell
New-Item -ItemType Directory -Force logs
idf.py -p COM7 flash monitor 2>&1 | Tee-Object -FilePath logs\board_cloud_latest.log
```

筛选关键日志：

```powershell
Select-String -Path logs\board_cloud_latest.log -Pattern "app_cloud|app_wifi|error|failed|timeout|json_error|http_error"
```

## 云端联调检查

检查云端健康状态：

```powershell
curl.exe -k <YOUR_SERVER_URL>/health
```

清空当前端侧 session：

```powershell
curl.exe -k -X POST <YOUR_SERVER_URL>/api/v1/debug/reset/esp32p4-dev-001
```

推荐测试顺序：

1. reset session。
2. 手静止或五指张开不动。
3. 观察 `Cloud: collecting`，`Word: -`，`Sentence: -`。
4. 做 left-right 连续动作 2-3 秒。
5. 观察 `collecting -> pending -> confirmed`。
6. confirmed 后屏幕显示 `Word` 和 `Sentence`。

## 当前能力边界

当前已经具备：

- 本地手部检测与手型识别。
- 本地基元实时输出。
- P4+C6 Wi-Fi 联网。
- primitive frame HTTPS 上传。
- 云端词级匹配与句子返回。
- 端侧 Cloud / Word / Sentence 显示。
- 中文词条显示字体。

当前尚未实现：

- 端侧动作片段切分后上传。
- 端侧词表匹配。
- 端侧 embedding / RAG / LLM。
- TTS 语音播报。
- 文字/语音到手语动画的反向链路。
- full 词库稳定演示。

当前验收重点是先跑通：

```text
primitive -> HTTPS POST -> cloud stream match -> Word/Sentence -> UI
```

识别准确率、词库扩容、句子级 LLM 效果和反向动画属于下一阶段。


