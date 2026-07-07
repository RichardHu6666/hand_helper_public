#include "app_hand_gesture.h"

#include <list>
#include <string.h>

#include "sdkconfig.h"
#include "dl_detect_define.hpp"
#include "dl_image_define.hpp"
#include "esp_log.h"
#include "hand_gesture_recognition.hpp"

static const char *TAG = "hand_gesture";
static HandGestureRecognizer *s_recognizer = nullptr;
static constexpr int GESTURE_WARMUP_SIDE = 128;
static constexpr float GESTURE_CROP_NORMAL_SHORT_SCALE = 0.90f;
static constexpr float GESTURE_CROP_COMPACT_ASPECT_START = 1.00f;
static constexpr float GESTURE_CROP_COMPACT_ASPECT_END = 1.18f;
static constexpr float GESTURE_CROP_COMPACT_SHORT_SCALE = 0.82f;
static constexpr float GESTURE_CROP_SLENDER_BLEND_START = 1.20f;
static constexpr float GESTURE_CROP_SLENDER_BLEND_END = 2.35f;
static constexpr float GESTURE_CROP_HARD_SLENDER_START = 1.85f;
static constexpr float GESTURE_CROP_HARD_SLENDER_END = 2.35f;
static constexpr float GESTURE_CROP_SLENDER_SHORT_SCALE = 1.18f;
static constexpr float GESTURE_CROP_SLENDER_LONG_SCALE = 0.90f;
static constexpr float GESTURE_CROP_SLENDER_MIX_RATIO = 0.50f;
static constexpr float GESTURE_CROP_HARD_SLENDER_LONG_RATIO = 0.60f;
static constexpr float GESTURE_CROP_SLENDER_UPSHIFT = 0.30f;
static constexpr float GESTURE_CROP_SLENDER_TOP_ANCHOR = 0.92f;
static constexpr int GESTURE_CROP_MIN_SIDE_NORMAL = 96;
static constexpr int GESTURE_CROP_MIN_SIDE_SLENDER = 128;
static int s_cls_log_counter = 0;

static gesture_id_t map_gesture_name(const char *name)
{
    if (!name) {
        return GESTURE_ID_NO_GESTURE;
    }
    if (strcmp(name, "one") == 0) {
        return GESTURE_ID_ONE;
    }
    if (strcmp(name, "two") == 0) {
        return GESTURE_ID_TWO;
    }
    if (strcmp(name, "three") == 0) {
        return GESTURE_ID_THREE;
    }
    if (strcmp(name, "four") == 0) {
        return GESTURE_ID_FOUR;
    }
    if (strcmp(name, "five") == 0) {
        return GESTURE_ID_FIVE;
    }
    if (strcmp(name, "like") == 0) {
        return GESTURE_ID_LIKE;
    }
    if (strcmp(name, "ok") == 0) {
        return GESTURE_ID_OK;
    }
    if (strcmp(name, "call") == 0) {
        return GESTURE_ID_CALL;
    }
    if (strcmp(name, "dislike") == 0) {
        return GESTURE_ID_DISLIKE;
    }
    if (strcmp(name, "no_hand") == 0) {
        return GESTURE_ID_NO_HAND;
    }
    return GESTURE_ID_NO_GESTURE;
}

static int clamp_int(int value, int min_value, int max_value)
{
    if (value < min_value) {
        return min_value;
    }
    if (value > max_value) {
        return max_value;
    }
    return value;
}

static float clamp_float(float value, float min_value, float max_value)
{
    if (value < min_value) {
        return min_value;
    }
    if (value > max_value) {
        return max_value;
    }
    return value;
}

static float lerp_float(float a, float b, float t)
{
    return a + (b - a) * t;
}

static void copy_debug_text(char *dst, size_t dst_size, const char *src)
{
    if (!dst || dst_size == 0) {
        return;
    }

    if (!src) {
        dst[0] = '\0';
        return;
    }

    strncpy(dst, src, dst_size - 1);
    dst[dst_size - 1] = '\0';
}

static const char *aspect_bucket_name(float aspect_ratio)
{
    if (aspect_ratio < 1.20f) {
        return "normal";
    }
    if (aspect_ratio < 1.75f) {
        return "mid_slender";
    }
    return "hard_slender";
}

static int normalize_detect_box(const ai_result_t *detect_result,
                                int index,
                                int frame_w,
                                int frame_h,
                                dl::detect::result_t *out_det,
                                gesture_debug_info_t *out_debug)
{
    int det_x = 0;
    int det_y = 0;
    int det_w = 0;
    int det_h = 0;
    int crop_side = 0;
    int x1 = 0;
    int y1 = 0;
    int up_shift = 0;
    int center_y1 = 0;
    int top_anchor_y1 = 0;
    int max_x1 = 0;
    int max_y1 = 0;
    int clamped_x1 = 0;
    int clamped_y1 = 0;
    int short_side = 0;
    int long_side = 0;
    int min_crop_side = GESTURE_CROP_MIN_SIDE_NORMAL;
    float aspect_ratio = 1.0f;
    float compact_blend = 0.0f;
    float slender_blend = 0.0f;
    float hard_slender_blend = 0.0f;
    float normal_side = 0.0f;
    float compact_side = 0.0f;
    float slender_side = 0.0f;
    float slender_side_base = 0.0f;
    float blended_side = 0.0f;
    float slender_side_mixed = 0.0f;
    float hard_side_target = 0.0f;
    const char *profile_name = "normal";
    const char *side_source_name = "short";
    const char *aspect_bucket = "normal";

    if (!detect_result || !out_det || !out_debug || index < 0 || index >= detect_result->count) {
        return 0;
    }

    det_x = detect_result->boxes[index].x;
    det_y = detect_result->boxes[index].y;
    det_w = detect_result->boxes[index].w;
    det_h = detect_result->boxes[index].h;
    if (det_w <= 0 || det_h <= 0) {
        return 0;
    }

    short_side = (det_w < det_h) ? det_w : det_h;
    long_side = (det_w > det_h) ? det_w : det_h;
    aspect_ratio = (float)det_h / (float)det_w;
    aspect_bucket = aspect_bucket_name(aspect_ratio);
    compact_blend = clamp_float((GESTURE_CROP_COMPACT_ASPECT_END - aspect_ratio) /
                                (GESTURE_CROP_COMPACT_ASPECT_END - GESTURE_CROP_COMPACT_ASPECT_START),
                                0.0f,
                                1.0f);
    slender_blend = clamp_float((aspect_ratio - GESTURE_CROP_SLENDER_BLEND_START) /
                                (GESTURE_CROP_SLENDER_BLEND_END - GESTURE_CROP_SLENDER_BLEND_START),
                                0.0f,
                                1.0f);
    hard_slender_blend = clamp_float((aspect_ratio - GESTURE_CROP_HARD_SLENDER_START) /
                                     (GESTURE_CROP_HARD_SLENDER_END - GESTURE_CROP_HARD_SLENDER_START),
                                     0.0f,
                                     1.0f);
    if (slender_blend > 0.0f) {
        profile_name = "slender";
        side_source_name = "slender_mix";
    }
    min_crop_side = (int)(lerp_float((float)GESTURE_CROP_MIN_SIDE_NORMAL,
                                     (float)GESTURE_CROP_MIN_SIDE_SLENDER,
                                     slender_blend) +
                          0.5f);

    normal_side = (float)short_side * GESTURE_CROP_NORMAL_SHORT_SCALE;
    compact_side = (float)short_side * GESTURE_CROP_COMPACT_SHORT_SCALE;
    normal_side = lerp_float(normal_side, compact_side, compact_blend);
    slender_side = (float)short_side * GESTURE_CROP_SLENDER_SHORT_SCALE;
    slender_side_mixed = (float)short_side + ((float)(long_side - short_side) * GESTURE_CROP_SLENDER_MIX_RATIO);
    if (slender_side < slender_side_mixed) {
        slender_side = slender_side_mixed;
    }
    {
        float slender_side_cap = (float)long_side * GESTURE_CROP_SLENDER_LONG_SCALE;
        if (slender_side > slender_side_cap) {
            slender_side = slender_side_cap;
        }
    }
    if (slender_side < (float)short_side) {
        slender_side = (float)short_side;
    }
    slender_side_base = slender_side;
    hard_side_target = (float)long_side * GESTURE_CROP_HARD_SLENDER_LONG_RATIO;
    slender_side = lerp_float(slender_side_base, hard_side_target, hard_slender_blend);
    blended_side = lerp_float(normal_side, slender_side, slender_blend);
    crop_side = (int)(blended_side + 0.5f);
    if (crop_side < min_crop_side) {
        crop_side = min_crop_side;
    }
    if (crop_side > frame_w) {
        crop_side = frame_w;
    }
    if (crop_side > frame_h) {
        crop_side = frame_h;
    }

    x1 = det_x + (det_w - crop_side) / 2;
    center_y1 = det_y + (det_h - crop_side) / 2;
    up_shift = (int)(((float)(det_h - crop_side) * GESTURE_CROP_SLENDER_UPSHIFT * slender_blend) + 0.5f);
    top_anchor_y1 = det_y + (int)(((float)(det_h - crop_side) * (1.0f - GESTURE_CROP_SLENDER_TOP_ANCHOR)) + 0.5f);
    y1 = center_y1 - up_shift;
    if (slender_blend > 0.0f) {
        float top_bias = slender_blend * GESTURE_CROP_SLENDER_TOP_ANCHOR;
        y1 = (int)(lerp_float((float)y1, (float)top_anchor_y1, top_bias) + 0.5f);
    }
    max_x1 = frame_w - crop_side;
    max_y1 = frame_h - crop_side;
    if (max_x1 < 0) {
        max_x1 = 0;
    }
    if (max_y1 < 0) {
        max_y1 = 0;
    }
    clamped_x1 = clamp_int(x1, 0, max_x1);
    clamped_y1 = clamp_int(y1, 0, max_y1);

    out_det->category = 0;
    out_det->score = detect_result->boxes[index].score;
    out_det->box = {
        clamped_x1,
        clamped_y1,
        clamped_x1 + crop_side,
        clamped_y1 + crop_side,
    };

    out_debug->detect_x = det_x;
    out_debug->detect_y = det_y;
    out_debug->detect_w = det_w;
    out_debug->detect_h = det_h;
    out_debug->crop_x = clamped_x1;
    out_debug->crop_y = clamped_y1;
    out_debug->crop_w = crop_side;
    out_debug->crop_h = crop_side;
    copy_debug_text(out_debug->profile_name, sizeof(out_debug->profile_name), profile_name);
    copy_debug_text(out_debug->side_source_name, sizeof(out_debug->side_source_name), side_source_name);
    copy_debug_text(out_debug->aspect_bucket, sizeof(out_debug->aspect_bucket), aspect_bucket);
    out_debug->aspect_ratio = aspect_ratio;
    out_debug->slender_blend = slender_blend;
    out_debug->crop_short_ratio = short_side > 0 ? ((float)crop_side / (float)short_side) : 0.0f;
    out_debug->crop_long_ratio = long_side > 0 ? ((float)crop_side / (float)long_side) : 0.0f;
    out_debug->crop_area_ratio = (det_w > 0 && det_h > 0) ?
        (((float)crop_side * (float)crop_side) / ((float)det_w * (float)det_h)) : 0.0f;
    out_debug->center_y_bias = det_h > 0 ?
        ((((float)clamped_y1 + ((float)crop_side * 0.5f)) -
          ((float)det_y + ((float)det_h * 0.5f))) / (float)det_h) : 0.0f;
    out_debug->clamped = (clamped_x1 != x1) || (clamped_y1 != y1);
    out_debug->valid = true;

    return 1;
}

static int build_detect_list(const ai_result_t *detect_result,
                             int frame_w,
                             int frame_h,
                             std::list<dl::detect::result_t> *results,
                             gesture_debug_info_t *crop_debugs,
                             int max_debugs)
{
    int out_count = 0;

    if (!detect_result || !results || !crop_debugs || max_debugs <= 0) {
        return 0;
    }

    results->clear();
    for (int i = 0; i < detect_result->count && i < AI_RESULT_MAX_BOXES && out_count < max_debugs; i++) {
        dl::detect::result_t det = {};
        if (normalize_detect_box(detect_result, i, frame_w, frame_h, &det, &crop_debugs[out_count])) {
            results->push_back(det);
            out_count++;
        }
    }

    return out_count;
}

static void warmup_gesture_recognizer(void)
{
    static uint16_t s_warmup_frame[GESTURE_WARMUP_SIDE * GESTURE_WARMUP_SIDE] = {0};
    dl::image::img_t warmup_img = {
        .data = s_warmup_frame,
        .width = (uint16_t)GESTURE_WARMUP_SIDE,
        .height = (uint16_t)GESTURE_WARMUP_SIDE,
        .pix_type = dl::image::DL_IMAGE_PIX_TYPE_RGB565LE,
    };
    dl::detect::result_t warmup_det = {};
    std::list<dl::detect::result_t> warmup_list;

    warmup_det.box = {0, 0, GESTURE_WARMUP_SIDE, GESTURE_WARMUP_SIDE};
    warmup_list.push_back(warmup_det);

    ESP_LOGI(TAG, "Warming up hand gesture recognizer...");
    (void)s_recognizer->recognize(warmup_img, warmup_list);
    ESP_LOGI(TAG, "Hand gesture recognizer warmup done");
}

extern "C" esp_err_t app_hand_gesture_init(void)
{
    if (s_recognizer) {
        return ESP_OK;
    }

    ESP_LOGI(TAG, "Initializing hand gesture recognizer...");
    s_recognizer = new HandGestureRecognizer(HandGestureCls::MOBILENETV2_0_5_S8_V1);
    if (!s_recognizer) {
        ESP_LOGE(TAG, "Failed to create HandGestureRecognizer");
        return ESP_FAIL;
    }

    warmup_gesture_recognizer();

    ESP_LOGI(TAG, "Hand gesture recognizer loaded");
    return ESP_OK;
}

extern "C" int app_hand_gesture_recognize(uint16_t *frame,
                                           int w,
                                           int h,
                                           const ai_result_t *detect_result,
                                           gesture_result_t *gestures,
                                           int max_gestures,
                                           gesture_debug_info_t *debug_infos,
                                           int max_debug_infos)
{
    if (!s_recognizer || !frame || !detect_result || !gestures || max_gestures <= 0) {
        return 0;
    }

    dl::image::img_t img = {
        .data = frame,
        .width = (uint16_t)w,
        .height = (uint16_t)h,
        .pix_type = dl::image::DL_IMAGE_PIX_TYPE_RGB565LE,
    };
    gesture_debug_info_t crop_debugs[AI_RESULT_MAX_BOXES] = {};
    std::list<dl::detect::result_t> detect_list;
    int detect_count = build_detect_list(detect_result, w, h, &detect_list, crop_debugs, AI_RESULT_MAX_BOXES);
    auto res = s_recognizer->recognize(img, detect_list);

    if (debug_infos && max_debug_infos > 0) {
        memset(debug_infos, 0, sizeof(gesture_debug_info_t) * max_debug_infos);
        for (int i = 0; i < detect_count && i < max_debug_infos; i++) {
            debug_infos[i] = crop_debugs[i];
        }
    }

    if ((int)res.size() != detect_count) {
        ESP_LOGW(TAG, "detect/classify count mismatch: detect=%d classify=%d", detect_count, (int)res.size());
    }

    int out_count = 0;
    for (size_t i = 0; i < res.size() && out_count < max_gestures; i++, out_count++) {
        bool should_log = false;
        gestures[out_count].gesture_id = map_gesture_name(res[i].cat_name);
        gestures[out_count].score = res[i].score;
        gestures[out_count].stable = false;
        gestures[out_count].stable_count = 0;
        if (out_count < detect_count) {
            s_cls_log_counter++;
            should_log = (gestures[out_count].gesture_id != GESTURE_ID_NO_GESTURE &&
                          gestures[out_count].gesture_id != GESTURE_ID_NO_HAND) ||
                         crop_debugs[out_count].clamped ||
                         (s_cls_log_counter % CONFIG_GESTURE_LOG_EVERY_N_FRAMES) == 0;
        }
        if (out_count < detect_count && should_log) {
            ESP_LOGI(TAG,
                     "cls[%d/%d]: detect=(x=%d y=%d w=%d h=%d) crop=(x=%d y=%d w=%d h=%d) profile=%s side_src=%s bucket=%s aspect=%.2f blend=%.2f short_ratio=%.2f long_ratio=%.2f clamp=%d result=%s score=%.2f",
                     out_count + 1,
                     detect_count,
                     crop_debugs[out_count].detect_x,
                     crop_debugs[out_count].detect_y,
                     crop_debugs[out_count].detect_w,
                     crop_debugs[out_count].detect_h,
                     crop_debugs[out_count].crop_x,
                     crop_debugs[out_count].crop_y,
                     crop_debugs[out_count].crop_w,
                     crop_debugs[out_count].crop_h,
                     crop_debugs[out_count].profile_name,
                     crop_debugs[out_count].side_source_name,
                     crop_debugs[out_count].aspect_bucket,
                     crop_debugs[out_count].aspect_ratio,
                     crop_debugs[out_count].slender_blend,
                     crop_debugs[out_count].crop_short_ratio,
                     crop_debugs[out_count].crop_long_ratio,
                     crop_debugs[out_count].clamped ? 1 : 0,
                     app_gesture_name(gestures[out_count].gesture_id),
                     gestures[out_count].score);
        }
    }

    for (int i = out_count; i < max_gestures; i++) {
        gestures[i].gesture_id = GESTURE_ID_NO_GESTURE;
        gestures[i].score = 0.0f;
        gestures[i].stable = false;
        gestures[i].stable_count = 0;
    }

    return out_count;
}

extern "C" const char *app_gesture_name(gesture_id_t gesture_id)
{
    switch (gesture_id) {
    case GESTURE_ID_ONE:
        return "one";
    case GESTURE_ID_TWO:
        return "two";
    case GESTURE_ID_THREE:
        return "three";
    case GESTURE_ID_FOUR:
        return "four";
    case GESTURE_ID_FIVE:
        return "five";
    case GESTURE_ID_LIKE:
        return "like";
    case GESTURE_ID_OK:
        return "ok";
    case GESTURE_ID_CALL:
        return "call";
    case GESTURE_ID_DISLIKE:
        return "dislike";
    case GESTURE_ID_NO_HAND:
        return "no_hand";
    case GESTURE_ID_NO_GESTURE:
    default:
        return "no_gesture";
    }
}

