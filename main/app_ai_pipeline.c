#include "app_ai_pipeline.h"

#include <inttypes.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "app_camera.h"
#include "app_cloud.h"
#include "app_hand_detect.h"
#include "app_hand_gesture.h"
#include "app_output.h"
#include "app_ui_layout.h"
#include "sdkconfig.h"
#include "esp_cache.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"

#ifndef CONFIG_PRIMITIVE_MOTION_DEBUG_LOG
#define CONFIG_PRIMITIVE_MOTION_DEBUG_LOG 0
#endif

static const char *TAG = "ai_pipeline";

#define RGB565_GREEN           0x07E0
#define RGB565_YELLOW          0xFFE0
#define DISPLAY_INTERVAL_MS    33
#define AI_DETECT_TASK_STACK   8192
#define AI_POST_TASK_STACK     8192
#define AI_DISPLAY_TASK_STACK  4096
#define AI_DETECT_TASK_PRIORITY 2
#define AI_POST_TASK_PRIORITY   2
#define AI_DISPLAY_TASK_PRIORITY 2
#define CACHE_LINE_SIZE         64

#ifndef CONFIG_GESTURE_DETECT_INTERVAL_MS
#define CONFIG_GESTURE_DETECT_INTERVAL_MS 66
#endif
#ifndef CONFIG_GESTURE_STABLE_FRAMES
#define CONFIG_GESTURE_STABLE_FRAMES 2
#endif
#ifndef CONFIG_GESTURE_MIN_SCORE
#define CONFIG_GESTURE_MIN_SCORE 55
#endif
#ifndef CONFIG_GESTURE_LOG_EVERY_N_FRAMES
#define CONFIG_GESTURE_LOG_EVERY_N_FRAMES 5
#endif
#ifndef CONFIG_GESTURE_DEBUG_SUMMARY_INTERVAL
#define CONFIG_GESTURE_DEBUG_SUMMARY_INTERVAL 30
#endif
#ifndef CONFIG_GESTURE_PRIMITIVE_LOG_EVERY_N_FRAMES
#define CONFIG_GESTURE_PRIMITIVE_LOG_EVERY_N_FRAMES 10
#endif

#define DETECT_INTERVAL_MS CONFIG_GESTURE_DETECT_INTERVAL_MS
#define STABLE_FRAMES      CONFIG_GESTURE_STABLE_FRAMES
#define MIN_GESTURE_SCORE  ((float)CONFIG_GESTURE_MIN_SCORE / 100.0f)
#define RAW_LOG_INTERVAL   CONFIG_GESTURE_LOG_EVERY_N_FRAMES
#define DEBUG_SUMMARY_INTERVAL CONFIG_GESTURE_DEBUG_SUMMARY_INTERVAL
#define PRIMITIVE_LOG_INTERVAL CONFIG_GESTURE_PRIMITIVE_LOG_EVERY_N_FRAMES
#define PRIMARY_TRACK_MAX_DIST_SCALE 0.95f
#define PRIMARY_TRACK_MIN_DIST_PX    80.0f
#define PRIMARY_TRACK_MAX_AREA_RATIO 4.0f
#define PRIMARY_STABLE_MISS_GRACE    1
#define SECONDARY_CLASSIFY_MIN_SCORE      0.42f
#define SECONDARY_CLASSIFY_MIN_AREA_RATIO 0.38f
#define SECONDARY_CLASSIFY_MIN_SHORT_RATIO 0.58f
#define PRIMITIVE_MAX_HANDS 2
#define PRIMITIVE_MOVEMENT_HISTORY 4
#define PRIMITIVE_MOVEMENT_HOLD_GRACE_FRAMES 3
#define PRIMITIVE_MOVEMENT_AXIS_MIN_SCALE 0.20f
#define PRIMITIVE_MOVEMENT_AXIS_DOMINANCE 1.20f
#define PRIMITIVE_MOVEMENT_CENTER_SMALL_SCALE 0.45f
#define PRIMITIVE_MOVEMENT_TOWARD_AWAY_AREA_RATIO 1.50f
#define PRIMITIVE_MOVEMENT_STRONG_TOWARD_AWAY_AREA_RATIO 1.75f
#define PRIMITIVE_MOVEMENT_STRONG_TOWARD_AWAY_CENTER_SCALE 0.70f
#define PRIMITIVE_MOVEMENT_HOLD_SCALE 0.12f
#define PRIMITIVE_MOVEMENT_HOLD_MAX_AREA_RATIO 1.18f
#define PRIMITIVE_MOTION_DEBUG_LOG_INTERVAL 8
#define CLASSIFY_SKIP_ACTIVE_WARMUP_FRAMES 2
#define CLASSIFY_SKIP_ACTIVE_LOG_MS 1000
#define PRIMITIVE_MIN_SHORT_SIDE 100
#define PRIMITIVE_MIN_SCORE 0.30f
#define PRIMITIVE_WEAK_SCORE 0.36f
#define PRIMITIVE_WEAK_MIN_SHORT_SIDE 140
#define PRIMITIVE_EDGE_MARGIN 2
#define PRIMITIVE_MISS_GRACE_FRAMES 2

static gesture_id_t s_primary_candidate = GESTURE_ID_NO_GESTURE;
static gesture_id_t s_stable_primary = GESTURE_ID_NO_GESTURE;
static float s_stable_primary_score = 0.0f;
static int s_primary_candidate_frames = 0;
static int s_stable_miss_frames = 0;
static int s_detect_log_counter = 0;
static int s_classify_log_counter = 0;
static int s_classify_box_log_counter = 0;
static int s_drop_detect_counter = 0;
static int s_stale_drop_log_counter = 0;
static int s_primary_debug_log_counter = 0;
static int s_primary_debug_frame_counter = 0;
static int s_summary_one = 0;
static int s_summary_two = 0;
static int s_summary_three = 0;
static int s_summary_four = 0;
static int s_summary_five = 0;
static int s_summary_like = 0;
static int s_summary_ok = 0;
static int s_summary_call = 0;
static int s_summary_dislike = 0;
static int s_summary_no_gesture = 0;
static int s_summary_no_hand = 0;
static int s_summary_other = 0;
static char s_last_primary_profile[16] = "";
static int s_primitive_log_counter = 0;
static int s_primitive_motion_debug_log_counter = 0;
static int s_active_motion_classify_warmup_frames = 0;
static int64_t s_last_classify_skip_log_us = 0;
static bool s_last_primitive_valid = false;
static app_primitive_state_t s_last_primitive_state = {0};

typedef struct {
    bool valid;
    int x;
    int y;
    int w;
    int h;
    float aspect_ratio;
} primary_box_tracker_t;

static primary_box_tracker_t s_primary_box_tracker = {0};

typedef struct {
    gesture_id_t candidate;
    gesture_id_t stable;
    float stable_score;
    int candidate_frames;
    int miss_frames;
} primitive_side_stability_t;

typedef struct {
    bool valid;
    float cx;
    float cy;
    float area;
    int w;
    int h;
    int64_t timestamp_us;
} primitive_motion_sample_t;

typedef struct {
    app_signer_side_t dominant_side;
    primitive_motion_sample_t samples[PRIMITIVE_MOVEMENT_HISTORY];
    int count;
    int next;
    app_movement_t latched_movement;
    app_relative_motion_t latched_relative_motion;
    int hold_grace_frames;
} primitive_motion_history_t;

typedef struct {
    app_signer_side_t signer_side;
    const char *camera_side_name;
    int box_index;
    int classify_index;
    gesture_id_t stable_shape;
} primitive_hand_slot_t;

typedef struct {
    ai_result_t result;
    int miss_frames;
    bool valid;
} primitive_stable_result_t;

typedef struct {
    int raw_count;
    int filtered_count;
    int rejected_edge;
    int rejected_small;
    int rejected_weak;
} primitive_filter_stats_t;

static primitive_side_stability_t s_primitive_left_stability = {
    .candidate = GESTURE_ID_NO_GESTURE,
    .stable = GESTURE_ID_NO_HAND,
};
static primitive_side_stability_t s_primitive_right_stability = {
    .candidate = GESTURE_ID_NO_GESTURE,
    .stable = GESTURE_ID_NO_HAND,
};
static primitive_motion_history_t s_primitive_motion = {
    .dominant_side = APP_SIGNER_SIDE_NONE,
};
static primitive_stable_result_t s_primitive_stable_result = {0};

static void cache_msync_aligned(void *ptr, size_t size, uint32_t flags)
{
    uintptr_t start = 0;
    uintptr_t end = 0;

    if (!ptr || size == 0) {
        return;
    }

    start = ((uintptr_t)ptr) & ~((uintptr_t)CACHE_LINE_SIZE - 1U);
    end = ((uintptr_t)ptr + size + CACHE_LINE_SIZE - 1U) & ~((uintptr_t)CACHE_LINE_SIZE - 1U);
    esp_cache_msync((void *)start, end - start, flags);
}

static float box_rank_score(const ai_result_t *result, int i)
{
    float area = (float)result->boxes[i].w * (float)result->boxes[i].h;
    return area * result->boxes[i].score;
}

static float box_iou(const ai_result_t *result, int a, int b)
{
    int ax1 = result->boxes[a].x;
    int ay1 = result->boxes[a].y;
    int ax2 = ax1 + result->boxes[a].w;
    int ay2 = ay1 + result->boxes[a].h;
    int bx1 = result->boxes[b].x;
    int by1 = result->boxes[b].y;
    int bx2 = bx1 + result->boxes[b].w;
    int by2 = by1 + result->boxes[b].h;
    int ix1 = ax1 > bx1 ? ax1 : bx1;
    int iy1 = ay1 > by1 ? ay1 : by1;
    int ix2 = ax2 < bx2 ? ax2 : bx2;
    int iy2 = ay2 < by2 ? ay2 : by2;
    int iw = ix2 - ix1;
    int ih = iy2 - iy1;

    if (iw <= 0 || ih <= 0) {
        return 0.0f;
    }

    float intersection = (float)iw * (float)ih;
    float area_a = (float)result->boxes[a].w * (float)result->boxes[a].h;
    float area_b = (float)result->boxes[b].w * (float)result->boxes[b].h;
    float union_area = area_a + area_b - intersection;

    if (union_area <= 0.0f) {
        return 0.0f;
    }

    return intersection / union_area;
}

static float box_center_distance(const ai_result_t *result, int a, int b)
{
    float acx = (float)result->boxes[a].x + (float)result->boxes[a].w * 0.5f;
    float acy = (float)result->boxes[a].y + (float)result->boxes[a].h * 0.5f;
    float bcx = (float)result->boxes[b].x + (float)result->boxes[b].w * 0.5f;
    float bcy = (float)result->boxes[b].y + (float)result->boxes[b].h * 0.5f;
    float dx = acx - bcx;
    float dy = acy - bcy;

    return sqrtf(dx * dx + dy * dy);
}

static float box_area_ratio(const ai_result_t *result, int a, int b)
{
    float area_a = (float)result->boxes[a].w * (float)result->boxes[a].h;
    float area_b = (float)result->boxes[b].w * (float)result->boxes[b].h;
    float min_area = area_a < area_b ? area_a : area_b;
    float max_area = area_a > area_b ? area_a : area_b;

    if (min_area <= 0.0f) {
        return 999.0f;
    }

    return max_area / min_area;
}

static bool boxes_look_duplicate(const ai_result_t *result, int a, int b)
{
    int short_a = result->boxes[a].w < result->boxes[a].h ? result->boxes[a].w : result->boxes[a].h;
    int short_b = result->boxes[b].w < result->boxes[b].h ? result->boxes[b].w : result->boxes[b].h;
    int min_short = short_a < short_b ? short_a : short_b;
    float near_threshold = (float)min_short * 0.22f;
    float iou = box_iou(result, a, b);
    float center_distance = box_center_distance(result, a, b);
    float area_ratio = box_area_ratio(result, a, b);

    if (iou > 0.30f) {
        return true;
    }

    return (center_distance < near_threshold) && (area_ratio < 1.8f);
}

static void swap_boxes(ai_result_t *result, int a, int b)
{
    if (!result || a == b) {
        return;
    }

    int x = result->boxes[a].x;
    int y = result->boxes[a].y;
    int w = result->boxes[a].w;
    int h = result->boxes[a].h;
    float score = result->boxes[a].score;

    result->boxes[a].x = result->boxes[b].x;
    result->boxes[a].y = result->boxes[b].y;
    result->boxes[a].w = result->boxes[b].w;
    result->boxes[a].h = result->boxes[b].h;
    result->boxes[a].score = result->boxes[b].score;

    result->boxes[b].x = x;
    result->boxes[b].y = y;
    result->boxes[b].w = w;
    result->boxes[b].h = h;
    result->boxes[b].score = score;
}

static void sort_detect_boxes(ai_result_t *result)
{
    if (!result || result->count <= 1) {
        return;
    }

    for (int i = 0; i < result->count - 1; i++) {
        for (int j = i + 1; j < result->count; j++) {
            if (box_rank_score(result, j) > box_rank_score(result, i)) {
                swap_boxes(result, i, j);
            }
        }
    }
}

static void dedup_detect_result(ai_result_t *result)
{
    bool keep[AI_RESULT_MAX_BOXES] = {0};
    int new_count = 0;

    if (!result || result->count <= 1) {
        return;
    }

    for (int i = 0; i < result->count && i < AI_RESULT_MAX_BOXES; i++) {
        keep[i] = true;
    }

    for (int i = 0; i < result->count && i < AI_RESULT_MAX_BOXES; i++) {
        if (!keep[i]) {
            continue;
        }
        for (int j = i + 1; j < result->count && j < AI_RESULT_MAX_BOXES; j++) {
            if (!keep[j]) {
                continue;
            }
            if (boxes_look_duplicate(result, i, j)) {
                keep[j] = false;
            }
        }
    }

    for (int i = 0; i < result->count && i < AI_RESULT_MAX_BOXES; i++) {
        if (!keep[i]) {
            continue;
        }
        if (new_count != i) {
            result->boxes[new_count] = result->boxes[i];
        }
        new_count++;
    }

    for (int i = new_count; i < AI_RESULT_MAX_BOXES; i++) {
        memset(&result->boxes[i], 0, sizeof(result->boxes[i]));
    }
    result->count = new_count;
}

static void limit_classify_candidates(ai_result_t *result)
{
    float primary_area = 0.0f;
    int primary_short = 0;
    int write_index = 1;

    if (!result || result->count <= 1) {
        return;
    }

    primary_area = (float)result->boxes[0].w * (float)result->boxes[0].h;
    primary_short = result->boxes[0].w < result->boxes[0].h ? result->boxes[0].w : result->boxes[0].h;

    for (int i = 1; i < result->count && i < AI_RESULT_MAX_BOXES && write_index < PRIMITIVE_MAX_HANDS; i++) {
        float area = (float)result->boxes[i].w * (float)result->boxes[i].h;
        float area_ratio = primary_area > 0.0f ? (area / primary_area) : 0.0f;
        int short_side = result->boxes[i].w < result->boxes[i].h ? result->boxes[i].w : result->boxes[i].h;
        float short_ratio = primary_short > 0 ? ((float)short_side / (float)primary_short) : 0.0f;

        if (result->boxes[i].score < SECONDARY_CLASSIFY_MIN_SCORE ||
            area_ratio < SECONDARY_CLASSIFY_MIN_AREA_RATIO ||
            short_ratio < SECONDARY_CLASSIFY_MIN_SHORT_RATIO) {
            continue;
        }

        if (write_index != i) {
            result->boxes[write_index] = result->boxes[i];
        }
        write_index++;
    }

    for (int i = write_index; i < AI_RESULT_MAX_BOXES; i++) {
        memset(&result->boxes[i], 0, sizeof(result->boxes[i]));
    }
    result->count = write_index;
}

static int box_short_side(const ai_result_t *result, int index)
{
    int w = 0;
    int h = 0;

    if (!result || index < 0 || index >= result->count) {
        return 0;
    }

    w = result->boxes[index].w;
    h = result->boxes[index].h;
    return w < h ? w : h;
}

static bool box_touches_frame_edge(const ai_result_t *result, int index)
{
    if (!result || index < 0 || index >= result->count) {
        return true;
    }

    return result->boxes[index].x <= PRIMITIVE_EDGE_MARGIN ||
           result->boxes[index].y <= PRIMITIVE_EDGE_MARGIN ||
           (result->boxes[index].x + result->boxes[index].w) >= (APP_LCD_H_RES - PRIMITIVE_EDGE_MARGIN) ||
           (result->boxes[index].y + result->boxes[index].h) >= (APP_LCD_V_RES - PRIMITIVE_EDGE_MARGIN);
}

static bool primitive_box_is_valid(const ai_result_t *result,
                                   int index,
                                   primitive_filter_stats_t *stats)
{
    int short_side = box_short_side(result, index);
    float score = 0.0f;

    if (!result || index < 0 || index >= result->count) {
        return false;
    }

    score = result->boxes[index].score;
    if (box_touches_frame_edge(result, index)) {
        if (stats) {
            stats->rejected_edge++;
        }
        return false;
    }
    if (short_side < PRIMITIVE_MIN_SHORT_SIDE) {
        if (stats) {
            stats->rejected_small++;
        }
        return false;
    }
    if (score < PRIMITIVE_MIN_SCORE ||
        (score < PRIMITIVE_WEAK_SCORE && short_side < PRIMITIVE_WEAK_MIN_SHORT_SIDE)) {
        if (stats) {
            stats->rejected_weak++;
        }
        return false;
    }

    return true;
}

static void prepare_primitive_candidates(const ai_result_t *detect_result,
                                         ai_result_t *out_result,
                                         primitive_filter_stats_t *stats)
{
    int write_index = 0;

    if (!out_result) {
        return;
    }

    memset(out_result, 0, sizeof(*out_result));
    if (stats) {
        memset(stats, 0, sizeof(*stats));
    }
    if (!detect_result || detect_result->count <= 0) {
        return;
    }

    *out_result = *detect_result;
    dedup_detect_result(out_result);
    if (stats) {
        stats->raw_count = out_result->count;
    }

    for (int i = 0; i < out_result->count && i < AI_RESULT_MAX_BOXES; i++) {
        if (!primitive_box_is_valid(out_result, i, stats)) {
            continue;
        }
        if (write_index != i) {
            out_result->boxes[write_index] = out_result->boxes[i];
        }
        write_index++;
        if (write_index >= PRIMITIVE_MAX_HANDS) {
            break;
        }
    }

    for (int i = write_index; i < AI_RESULT_MAX_BOXES; i++) {
        memset(&out_result->boxes[i], 0, sizeof(out_result->boxes[i]));
    }
    out_result->count = write_index;
    if (stats) {
        stats->filtered_count = write_index;
    }
}

static bool update_stable_primitive_candidates(const ai_result_t *raw_result,
                                               ai_result_t *stable_result)
{
    if (!stable_result) {
        return false;
    }

    if (raw_result && raw_result->count > 0) {
        s_primitive_stable_result.result = *raw_result;
        s_primitive_stable_result.miss_frames = 0;
        s_primitive_stable_result.valid = true;
        *stable_result = *raw_result;
        return false;
    }

    if (s_primitive_stable_result.valid &&
        s_primitive_stable_result.miss_frames < PRIMITIVE_MISS_GRACE_FRAMES) {
        s_primitive_stable_result.miss_frames++;
        *stable_result = s_primitive_stable_result.result;
        return true;
    }

    memset(stable_result, 0, sizeof(*stable_result));
    memset(&s_primitive_stable_result, 0, sizeof(s_primitive_stable_result));
    return false;
}

static void reset_primary_box_tracker(void)
{
    memset(&s_primary_box_tracker, 0, sizeof(s_primary_box_tracker));
}

static float tracker_center_distance(const primary_box_tracker_t *tracker,
                                     const ai_result_t *result,
                                     int index)
{
    float prev_cx = 0.0f;
    float prev_cy = 0.0f;
    float cur_cx = 0.0f;
    float cur_cy = 0.0f;
    float dx = 0.0f;
    float dy = 0.0f;

    if (!tracker || !tracker->valid || !result || index < 0 || index >= result->count) {
        return 9999.0f;
    }

    prev_cx = (float)tracker->x + (float)tracker->w * 0.5f;
    prev_cy = (float)tracker->y + (float)tracker->h * 0.5f;
    cur_cx = (float)result->boxes[index].x + (float)result->boxes[index].w * 0.5f;
    cur_cy = (float)result->boxes[index].y + (float)result->boxes[index].h * 0.5f;
    dx = cur_cx - prev_cx;
    dy = cur_cy - prev_cy;

    return sqrtf(dx * dx + dy * dy);
}

static float tracker_area_ratio(const primary_box_tracker_t *tracker,
                                const ai_result_t *result,
                                int index)
{
    float prev_area = 0.0f;
    float cur_area = 0.0f;
    float min_area = 0.0f;
    float max_area = 0.0f;

    if (!tracker || !tracker->valid || !result || index < 0 || index >= result->count) {
        return 999.0f;
    }

    prev_area = (float)tracker->w * (float)tracker->h;
    cur_area = (float)result->boxes[index].w * (float)result->boxes[index].h;
    min_area = prev_area < cur_area ? prev_area : cur_area;
    max_area = prev_area > cur_area ? prev_area : cur_area;

    if (min_area <= 0.0f) {
        return 999.0f;
    }

    return max_area / min_area;
}

static void promote_tracked_primary_box(ai_result_t *result)
{
    float best_cost = 9999.0f;
    float tracker_max_side = 0.0f;
    float max_distance = 0.0f;
    int best_index = 0;

    if (!result || result->count <= 1 || !s_primary_box_tracker.valid) {
        return;
    }

    tracker_max_side = (float)(s_primary_box_tracker.w > s_primary_box_tracker.h ?
        s_primary_box_tracker.w : s_primary_box_tracker.h);
    max_distance = tracker_max_side * PRIMARY_TRACK_MAX_DIST_SCALE;
    if (max_distance < PRIMARY_TRACK_MIN_DIST_PX) {
        max_distance = PRIMARY_TRACK_MIN_DIST_PX;
    }

    for (int i = 0; i < result->count && i < AI_RESULT_MAX_BOXES; i++) {
        float center_distance = tracker_center_distance(&s_primary_box_tracker, result, i);
        float area_ratio = tracker_area_ratio(&s_primary_box_tracker, result, i);
        float aspect_ratio = result->boxes[i].w > 0 ?
            ((float)result->boxes[i].h / (float)result->boxes[i].w) : 1.0f;
        float aspect_delta = fabsf(aspect_ratio - s_primary_box_tracker.aspect_ratio);
        float cost = 0.0f;

        if (center_distance > max_distance || area_ratio > PRIMARY_TRACK_MAX_AREA_RATIO) {
            continue;
        }

        cost = (center_distance / max_distance) +
               ((area_ratio - 1.0f) * 0.18f) +
               (aspect_delta * 0.20f) -
               (result->boxes[i].score * 0.12f);
        if (cost < best_cost) {
            best_cost = cost;
            best_index = i;
        }
    }

    if (best_index > 0) {
        swap_boxes(result, 0, best_index);
    }
}

static void smooth_primary_classify_box(ai_result_t *result)
{
    float prev_cx = 0.0f;
    float prev_cy = 0.0f;
    float cur_cx = 0.0f;
    float cur_cy = 0.0f;
    float dx = 0.0f;
    float dy = 0.0f;
    float center_distance = 0.0f;
    float max_side = 0.0f;
    float prev_area = 0.0f;
    float cur_area = 0.0f;
    float area_ratio = 999.0f;
    float prev_aspect = 1.0f;
    float cur_aspect = 1.0f;
    float aspect_delta = 0.0f;
    bool should_reset = false;

    if (!result || result->count <= 0) {
        reset_primary_box_tracker();
        return;
    }

    if (!s_primary_box_tracker.valid) {
        s_primary_box_tracker.valid = true;
        s_primary_box_tracker.x = result->boxes[0].x;
        s_primary_box_tracker.y = result->boxes[0].y;
        s_primary_box_tracker.w = result->boxes[0].w;
        s_primary_box_tracker.h = result->boxes[0].h;
        s_primary_box_tracker.aspect_ratio = result->boxes[0].w > 0 ?
            ((float)result->boxes[0].h / (float)result->boxes[0].w) : 1.0f;
        return;
    }

    prev_cx = (float)s_primary_box_tracker.x + (float)s_primary_box_tracker.w * 0.5f;
    prev_cy = (float)s_primary_box_tracker.y + (float)s_primary_box_tracker.h * 0.5f;
    cur_cx = (float)result->boxes[0].x + (float)result->boxes[0].w * 0.5f;
    cur_cy = (float)result->boxes[0].y + (float)result->boxes[0].h * 0.5f;
    dx = cur_cx - prev_cx;
    dy = cur_cy - prev_cy;
    center_distance = sqrtf(dx * dx + dy * dy);
    max_side = (float)(s_primary_box_tracker.w > s_primary_box_tracker.h ?
        s_primary_box_tracker.w : s_primary_box_tracker.h);
    prev_area = (float)s_primary_box_tracker.w * (float)s_primary_box_tracker.h;
    cur_area = (float)result->boxes[0].w * (float)result->boxes[0].h;
    prev_aspect = s_primary_box_tracker.aspect_ratio > 0.0f ?
        s_primary_box_tracker.aspect_ratio : 1.0f;
    cur_aspect = result->boxes[0].w > 0 ?
        ((float)result->boxes[0].h / (float)result->boxes[0].w) : 1.0f;
    aspect_delta = fabsf(cur_aspect - prev_aspect);

    // Slender gestures like `one` are more sensitive to vertical truncation than
    // to small jitter, so prefer the current detect box over historical smoothing.
    if (cur_aspect > 1.35f || prev_aspect > 1.35f) {
        s_primary_box_tracker.x = result->boxes[0].x;
        s_primary_box_tracker.y = result->boxes[0].y;
        s_primary_box_tracker.w = result->boxes[0].w;
        s_primary_box_tracker.h = result->boxes[0].h;
        s_primary_box_tracker.aspect_ratio = cur_aspect;
        return;
    }

    if (prev_area > 0.0f && cur_area > 0.0f) {
        float min_area = prev_area < cur_area ? prev_area : cur_area;
        float max_area = prev_area > cur_area ? prev_area : cur_area;
        area_ratio = max_area / min_area;
    }

    should_reset = center_distance > (0.45f * max_side) || area_ratio > 2.2f;
    if (!should_reset && cur_aspect > 1.35f && aspect_delta > 0.28f) {
        should_reset = true;
    }

    if (should_reset) {
        s_primary_box_tracker.x = result->boxes[0].x;
        s_primary_box_tracker.y = result->boxes[0].y;
        s_primary_box_tracker.w = result->boxes[0].w;
        s_primary_box_tracker.h = result->boxes[0].h;
        s_primary_box_tracker.aspect_ratio = cur_aspect;
        return;
    }

    s_primary_box_tracker.x = (int)((float)s_primary_box_tracker.x * 0.45f +
                                    (float)result->boxes[0].x * 0.55f + 0.5f);
    s_primary_box_tracker.y = (int)((float)s_primary_box_tracker.y * 0.45f +
                                    (float)result->boxes[0].y * 0.55f + 0.5f);
    s_primary_box_tracker.w = (int)((float)s_primary_box_tracker.w * 0.35f +
                                    (float)result->boxes[0].w * 0.65f + 0.5f);
    s_primary_box_tracker.h = (int)((float)s_primary_box_tracker.h * 0.35f +
                                    (float)result->boxes[0].h * 0.65f + 0.5f);
    s_primary_box_tracker.aspect_ratio = s_primary_box_tracker.w > 0 ?
        ((float)s_primary_box_tracker.h / (float)s_primary_box_tracker.w) : cur_aspect;

    result->boxes[0].x = s_primary_box_tracker.x;
    result->boxes[0].y = s_primary_box_tracker.y;
    result->boxes[0].w = s_primary_box_tracker.w;
    result->boxes[0].h = s_primary_box_tracker.h;
}

static bool classify_boxes_changed(const ai_result_t *raw_result, const ai_result_t *classify_result)
{
    if (!raw_result || !classify_result) {
        return false;
    }

    if (raw_result->count != classify_result->count) {
        return true;
    }

    for (int i = 0; i < classify_result->count && i < AI_RESULT_MAX_BOXES; i++) {
        if (raw_result->boxes[i].x != classify_result->boxes[i].x ||
            raw_result->boxes[i].y != classify_result->boxes[i].y ||
            raw_result->boxes[i].w != classify_result->boxes[i].w ||
            raw_result->boxes[i].h != classify_result->boxes[i].h) {
            return true;
        }
    }

    return false;
}

static void log_classify_boxes(const ai_result_t *raw_result, const ai_result_t *classify_result)
{
    bool changed = false;

    if (!raw_result || !classify_result || classify_result->count <= 0) {
        return;
    }

    changed = classify_boxes_changed(raw_result, classify_result);
    s_classify_box_log_counter++;
    if ((raw_result->count == classify_result->count) &&
        (s_classify_box_log_counter % RAW_LOG_INTERVAL) != 0) {
        return;
    }

    ESP_LOGI(TAG, "classify_boxes: raw=%d classify=%d changed=%d",
             raw_result->count, classify_result->count, changed ? 1 : 0);
    for (int i = 0; i < classify_result->count && i < AI_RESULT_MAX_BOXES; i++) {
        int raw_index = i < raw_result->count ? i : (raw_result->count - 1);
        if (raw_index < 0) {
            raw_index = 0;
        }
        ESP_LOGI(TAG,
                 "classify[%d]: raw=(x=%d y=%d w=%d h=%d) cls=(x=%d y=%d w=%d h=%d)",
                 i,
                 raw_result->boxes[raw_index].x,
                 raw_result->boxes[raw_index].y,
                 raw_result->boxes[raw_index].w,
                 raw_result->boxes[raw_index].h,
                 classify_result->boxes[i].x,
                 classify_result->boxes[i].y,
                 classify_result->boxes[i].w,
                 classify_result->boxes[i].h);
    }
}

static bool gesture_is_non_stable_state(gesture_id_t gesture_id)
{
    return gesture_id == GESTURE_ID_NO_GESTURE || gesture_id == GESTURE_ID_NO_HAND;
}

static bool should_hold_previous_stable(gesture_id_t raw_gesture, float score)
{
    // Keep the last stable class only for ambiguous/weak transition frames.
    // When the classifier explicitly returns `no_hand` while a box is still being
    // classified, releasing faster makes gesture-to-gesture switching feel less sticky.
    return raw_gesture == GESTURE_ID_NO_GESTURE || score < MIN_GESTURE_SCORE;
}

static const char *signer_side_name(app_signer_side_t side)
{
    switch (side) {
    case APP_SIGNER_SIDE_LEFT:
        return "signer_left";
    case APP_SIGNER_SIDE_RIGHT:
        return "signer_right";
    default:
        return "none";
    }
}

static const char *bimanual_relation_name(app_bimanual_relation_t relation)
{
    switch (relation) {
    case APP_BIMANUAL_RELATION_DUAL_HAND:
        return "dual_hand";
    case APP_BIMANUAL_RELATION_SAME_SHAPE:
        return "same_shape";
    case APP_BIMANUAL_RELATION_DIFFERENT_SHAPE:
        return "different_shape";
    case APP_BIMANUAL_RELATION_SINGLE_HAND:
    default:
        return "single_hand";
    }
}

static const char *movement_name(app_movement_t movement)
{
    switch (movement) {
    case APP_MOVEMENT_LEFT_RIGHT:
        return "left_right";
    case APP_MOVEMENT_UP_DOWN:
        return "up_down";
    case APP_MOVEMENT_TOWARD_AWAY:
        return "toward_away";
    case APP_MOVEMENT_OPEN_CLOSE:
        return "open_close";
    case APP_MOVEMENT_REPEAT:
        return "repeat";
    case APP_MOVEMENT_HOLD:
    default:
        return "hold";
    }
}

static const char *relative_motion_name(app_relative_motion_t relative_motion)
{
    switch (relative_motion) {
    case APP_RELATIVE_MOTION_LEFT_RIGHT:
        return "left_right";
    case APP_RELATIVE_MOTION_LEFT_TO_RIGHT:
        return "left_to_right";
    case APP_RELATIVE_MOTION_RIGHT_TO_LEFT:
        return "right_to_left";
    case APP_RELATIVE_MOTION_UP_DOWN:
        return "up_down";
    case APP_RELATIVE_MOTION_UP_TO_DOWN:
        return "up_to_down";
    case APP_RELATIVE_MOTION_DOWN_TO_UP:
        return "down_to_up";
    case APP_RELATIVE_MOTION_TOWARD_AWAY:
        return "toward_away";
    case APP_RELATIVE_MOTION_TOWARD:
        return "toward";
    case APP_RELATIVE_MOTION_AWAY:
        return "away";
    case APP_RELATIVE_MOTION_OPEN_CLOSE:
        return "open_close";
    case APP_RELATIVE_MOTION_REPEAT:
        return "repeat";
    case APP_RELATIVE_MOTION_UNKNOWN:
        return "unknown";
    case APP_RELATIVE_MOTION_HOLD:
    default:
        return "hold";
    }
}

static app_relative_motion_t relative_motion_for_raw(app_movement_t movement,
                                                     float dx,
                                                     float dy,
                                                     float area_ratio,
                                                     float first_area,
                                                     float last_area)
{
    switch (movement) {
    case APP_MOVEMENT_LEFT_RIGHT:
        if (dx > 0.0f) {
            return APP_RELATIVE_MOTION_RIGHT_TO_LEFT;
        }
        if (dx < 0.0f) {
            return APP_RELATIVE_MOTION_LEFT_TO_RIGHT;
        }
        return APP_RELATIVE_MOTION_LEFT_RIGHT;
    case APP_MOVEMENT_UP_DOWN:
        if (dy > 0.0f) {
            return APP_RELATIVE_MOTION_UP_TO_DOWN;
        }
        if (dy < 0.0f) {
            return APP_RELATIVE_MOTION_DOWN_TO_UP;
        }
        return APP_RELATIVE_MOTION_UP_DOWN;
    case APP_MOVEMENT_TOWARD_AWAY:
        if (area_ratio > 1.0f && last_area > first_area) {
            return APP_RELATIVE_MOTION_TOWARD;
        }
        if (area_ratio > 1.0f && last_area < first_area) {
            return APP_RELATIVE_MOTION_AWAY;
        }
        return APP_RELATIVE_MOTION_TOWARD_AWAY;
    case APP_MOVEMENT_OPEN_CLOSE:
        return APP_RELATIVE_MOTION_OPEN_CLOSE;
    case APP_MOVEMENT_REPEAT:
        return APP_RELATIVE_MOTION_REPEAT;
    case APP_MOVEMENT_HOLD:
    default:
        return APP_RELATIVE_MOTION_HOLD;
    }
}

static const char *location_name(app_location_t location)
{
    switch (location) {
    case APP_LOCATION_SIGNER_LEFT_UPPER:
        return "signer_left_upper";
    case APP_LOCATION_SIGNER_LEFT_MIDDLE:
        return "signer_left_middle";
    case APP_LOCATION_SIGNER_LEFT_LOWER:
        return "signer_left_lower";
    case APP_LOCATION_SIGNER_CENTER_UPPER:
        return "signer_center_upper";
    case APP_LOCATION_SIGNER_CENTER_MIDDLE:
        return "signer_center_middle";
    case APP_LOCATION_SIGNER_CENTER_LOWER:
        return "signer_center_lower";
    case APP_LOCATION_SIGNER_RIGHT_UPPER:
        return "signer_right_upper";
    case APP_LOCATION_SIGNER_RIGHT_MIDDLE:
        return "signer_right_middle";
    case APP_LOCATION_SIGNER_RIGHT_LOWER:
        return "signer_right_lower";
    case APP_LOCATION_UNKNOWN:
    default:
        return "unknown";
    }
}

static bool gesture_is_concrete_shape(gesture_id_t gesture_id)
{
    return gesture_id != GESTURE_ID_NO_GESTURE && gesture_id != GESTURE_ID_NO_HAND;
}

static primitive_side_stability_t *primitive_side_stability(app_signer_side_t side)
{
    if (side == APP_SIGNER_SIDE_LEFT) {
        return &s_primitive_left_stability;
    }
    if (side == APP_SIGNER_SIDE_RIGHT) {
        return &s_primitive_right_stability;
    }
    return NULL;
}

static void reset_primitive_side_stability(app_signer_side_t side)
{
    primitive_side_stability_t *stability = primitive_side_stability(side);

    if (!stability) {
        return;
    }

    stability->candidate = GESTURE_ID_NO_GESTURE;
    stability->stable = GESTURE_ID_NO_HAND;
    stability->stable_score = 0.0f;
    stability->candidate_frames = 0;
    stability->miss_frames = 0;
}

static gesture_id_t update_primitive_side_stability(app_signer_side_t side,
                                                    gesture_id_t raw_gesture,
                                                    float score,
                                                    bool present)
{
    primitive_side_stability_t *stability = primitive_side_stability(side);

    if (!stability) {
        return GESTURE_ID_NO_HAND;
    }

    if (!present || raw_gesture == GESTURE_ID_NO_HAND) {
        reset_primitive_side_stability(side);
        return GESTURE_ID_NO_HAND;
    }

    if (raw_gesture == GESTURE_ID_NO_GESTURE || score < MIN_GESTURE_SCORE) {
        stability->candidate = raw_gesture;
        stability->candidate_frames = 0;
        if (gesture_is_concrete_shape(stability->stable) &&
            stability->miss_frames < PRIMARY_STABLE_MISS_GRACE) {
            stability->miss_frames++;
            return stability->stable;
        }
        stability->stable = GESTURE_ID_NO_GESTURE;
        stability->stable_score = 0.0f;
        return GESTURE_ID_NO_GESTURE;
    }

    stability->miss_frames = 0;
    if (raw_gesture == stability->candidate) {
        stability->candidate_frames++;
    } else {
        stability->candidate = raw_gesture;
        stability->candidate_frames = 1;
    }

    if (stability->candidate_frames >= STABLE_FRAMES) {
        stability->stable = raw_gesture;
        stability->stable_score = score;
    }

    return gesture_is_concrete_shape(stability->stable) ?
        stability->stable : GESTURE_ID_NO_GESTURE;
}

static float hand_box_center_x(const ai_result_t *result, int index)
{
    if (!result || index < 0 || index >= result->count) {
        return 0.0f;
    }
    return (float)result->boxes[index].x + (float)result->boxes[index].w * 0.5f;
}

static float hand_box_center_y(const ai_result_t *result, int index)
{
    if (!result || index < 0 || index >= result->count) {
        return 0.0f;
    }
    return (float)result->boxes[index].y + (float)result->boxes[index].h * 0.5f;
}

static float hand_box_center_distance_sq(const ai_result_t *a,
                                         int a_index,
                                         const ai_result_t *b,
                                         int b_index)
{
    float dx = hand_box_center_x(a, a_index) - hand_box_center_x(b, b_index);
    float dy = hand_box_center_y(a, a_index) - hand_box_center_y(b, b_index);

    return dx * dx + dy * dy;
}

static int fill_primitive_hand_slots(const ai_result_t *primitive_result,
                                     primitive_hand_slot_t slots[PRIMITIVE_MAX_HANDS])
{
    int count = 0;

    if (!primitive_result || !slots || primitive_result->count <= 0) {
        return 0;
    }

    count = primitive_result->count;
    if (count > PRIMITIVE_MAX_HANDS) {
        count = PRIMITIVE_MAX_HANDS;
    }

    memset(slots, 0, sizeof(primitive_hand_slot_t) * PRIMITIVE_MAX_HANDS);
    for (int i = 0; i < PRIMITIVE_MAX_HANDS; i++) {
        slots[i].signer_side = APP_SIGNER_SIDE_NONE;
        slots[i].camera_side_name = "unknown";
        slots[i].box_index = -1;
        slots[i].classify_index = -1;
        slots[i].stable_shape = GESTURE_ID_NO_HAND;
    }

    if (count == 1) {
        float cx = hand_box_center_x(primitive_result, 0);
        bool is_camera_left = cx < ((float)APP_LCD_H_RES * 0.5f);

        slots[0].box_index = 0;
        slots[0].camera_side_name = is_camera_left ? "camera_left" : "camera_right";
        slots[0].signer_side = is_camera_left ? APP_SIGNER_SIDE_RIGHT : APP_SIGNER_SIDE_LEFT;
        return 1;
    }

    if (count >= 2) {
        int left_index = hand_box_center_x(primitive_result, 0) <=
            hand_box_center_x(primitive_result, 1) ? 0 : 1;
        int right_index = left_index == 0 ? 1 : 0;

        slots[0].box_index = left_index;
        slots[0].camera_side_name = "camera_left";
        slots[0].signer_side = APP_SIGNER_SIDE_RIGHT;

        slots[1].box_index = right_index;
        slots[1].camera_side_name = "camera_right";
        slots[1].signer_side = APP_SIGNER_SIDE_LEFT;
        return 2;
    }

    return 0;
}

static void match_primitive_slots_to_classify(const ai_result_t *primitive_result,
                                              const ai_result_t *classify_result,
                                              int classify_hand_count,
                                              primitive_hand_slot_t slots[PRIMITIVE_MAX_HANDS],
                                              int slot_count)
{
    bool used[AI_RESULT_MAX_BOXES] = {0};

    if (!primitive_result || !classify_result || !slots ||
        classify_hand_count <= 0 || slot_count <= 0) {
        return;
    }

    if (classify_hand_count > classify_result->count) {
        classify_hand_count = classify_result->count;
    }
    if (classify_hand_count > AI_RESULT_MAX_BOXES) {
        classify_hand_count = AI_RESULT_MAX_BOXES;
    }

    for (int i = 0; i < slot_count && i < PRIMITIVE_MAX_HANDS; i++) {
        int best_index = -1;
        float best_dist_sq = 0.0f;
        int primitive_index = slots[i].box_index;
        int primitive_short = box_short_side(primitive_result, primitive_index);

        for (int j = 0; j < classify_hand_count; j++) {
            int classify_short = box_short_side(classify_result, j);
            int ref_short = primitive_short > classify_short ? primitive_short : classify_short;
            float threshold = (float)ref_short * 0.85f;
            float dist_sq = 0.0f;

            if (used[j] || primitive_index < 0) {
                continue;
            }
            if (threshold < 100.0f) {
                threshold = 100.0f;
            }

            dist_sq = hand_box_center_distance_sq(primitive_result, primitive_index,
                                                  classify_result, j);
            if (dist_sq <= threshold * threshold &&
                (best_index < 0 || dist_sq < best_dist_sq)) {
                best_index = j;
                best_dist_sq = dist_sq;
            }
        }

        if (best_index >= 0) {
            slots[i].classify_index = best_index;
            used[best_index] = true;
        }
    }
}

static app_location_t primitive_location_from_box(const ai_result_t *result, int index)
{
    float cx = 0.0f;
    float cy = 0.0f;
    int vertical = 0;
    int signer_horizontal = 0;

    if (!result || index < 0 || index >= result->count ||
        result->boxes[index].w <= 0 || result->boxes[index].h <= 0) {
        return APP_LOCATION_UNKNOWN;
    }

    cx = (float)result->boxes[index].x + (float)result->boxes[index].w * 0.5f;
    cy = (float)result->boxes[index].y + (float)result->boxes[index].h * 0.5f;

    if (cx < ((float)APP_LCD_H_RES * 0.50f)) {
        signer_horizontal = 2;  // camera_left -> signer_right
    } else {
        signer_horizontal = 0;  // camera_right -> signer_left
    }

    if (cy < ((float)APP_LCD_V_RES * 0.50f)) {
        vertical = 0;
    } else {
        vertical = 2;
    }

    if (signer_horizontal == 0) {
        return vertical == 0 ? APP_LOCATION_SIGNER_LEFT_UPPER :
            (vertical == 1 ? APP_LOCATION_SIGNER_LEFT_MIDDLE : APP_LOCATION_SIGNER_LEFT_LOWER);
    }
    return vertical == 0 ? APP_LOCATION_SIGNER_RIGHT_UPPER :
        (vertical == 1 ? APP_LOCATION_SIGNER_RIGHT_MIDDLE : APP_LOCATION_SIGNER_RIGHT_LOWER);
}

static void reset_primitive_motion_history(void)
{
    memset(&s_primitive_motion, 0, sizeof(s_primitive_motion));
    s_primitive_motion.dominant_side = APP_SIGNER_SIDE_NONE;
    s_primitive_motion.latched_movement = APP_MOVEMENT_HOLD;
    s_primitive_motion.latched_relative_motion = APP_RELATIVE_MOTION_HOLD;
}

static app_movement_t apply_primitive_movement_latch(app_movement_t movement,
                                                     app_relative_motion_t relative_motion)
{
    if (movement != APP_MOVEMENT_HOLD) {
        s_primitive_motion.latched_movement = movement;
        s_primitive_motion.latched_relative_motion = relative_motion;
        s_primitive_motion.hold_grace_frames = PRIMITIVE_MOVEMENT_HOLD_GRACE_FRAMES;
        return movement;
    }

    if (s_primitive_motion.latched_movement != APP_MOVEMENT_HOLD &&
        s_primitive_motion.hold_grace_frames > 0) {
        s_primitive_motion.hold_grace_frames--;
        return s_primitive_motion.latched_movement;
    }

    s_primitive_motion.latched_movement = APP_MOVEMENT_HOLD;
    s_primitive_motion.latched_relative_motion = APP_RELATIVE_MOTION_HOLD;
    s_primitive_motion.hold_grace_frames = 0;
    return APP_MOVEMENT_HOLD;
}

static primitive_motion_sample_t primitive_motion_sample_at(int logical_index)
{
    int idx = 0;

    if (s_primitive_motion.count <= 0 || logical_index < 0 ||
        logical_index >= s_primitive_motion.count) {
        primitive_motion_sample_t empty = {0};
        return empty;
    }

    if (s_primitive_motion.count < PRIMITIVE_MOVEMENT_HISTORY) {
        idx = logical_index;
    } else {
        idx = (s_primitive_motion.next + logical_index) % PRIMITIVE_MOVEMENT_HISTORY;
    }

    return s_primitive_motion.samples[idx];
}

static void log_primitive_motion_debug(uint32_t frame_seq,
                                       float dx_norm,
                                       float dy_norm,
                                       float area_ratio,
                                       bool center_small,
                                       bool center_depth,
                                       app_movement_t raw_movement,
                                       app_movement_t latched_movement,
                                       app_relative_motion_t relative_motion)
{
    if (!CONFIG_PRIMITIVE_MOTION_DEBUG_LOG) {
        return;
    }

    s_primitive_motion_debug_log_counter++;
    if (raw_movement == APP_MOVEMENT_HOLD &&
        latched_movement == APP_MOVEMENT_HOLD &&
        (s_primitive_motion_debug_log_counter % PRIMITIVE_MOTION_DEBUG_LOG_INTERVAL) != 0) {
        return;
    }

    ESP_LOGI(TAG,
             "motion_debug: frame=%" PRIu32 " dx_norm=%.2f dy_norm=%.2f area_ratio=%.2f center_small=%d center_depth=%d raw=%s latched=%s rel=%s",
             frame_seq,
             dx_norm,
             dy_norm,
             area_ratio,
             center_small ? 1 : 0,
             center_depth ? 1 : 0,
             movement_name(raw_movement),
             movement_name(latched_movement),
             relative_motion_name(relative_motion));
}

static app_movement_t update_primitive_movement(app_signer_side_t dominant_side,
                                                uint32_t frame_seq,
                                                const ai_result_t *result,
                                                int box_index)
{
    primitive_motion_sample_t sample = {0};
    primitive_motion_sample_t first = {0};
    primitive_motion_sample_t last = {0};
    float dx = 0.0f;
    float dy = 0.0f;
    float abs_dx = 0.0f;
    float abs_dy = 0.0f;
    float min_area = 0.0f;
    float max_area = 0.0f;
    float area_ratio = 1.0f;
    float ref_w = 1.0f;
    float ref_h = 1.0f;
    bool center_small = false;
    bool center_depth = false;
    app_movement_t raw_movement = APP_MOVEMENT_HOLD;
    app_movement_t latched_movement = APP_MOVEMENT_HOLD;
    app_relative_motion_t raw_relative_motion = APP_RELATIVE_MOTION_HOLD;

    if (dominant_side == APP_SIGNER_SIDE_NONE || !result ||
        box_index < 0 || box_index >= result->count ||
        result->boxes[box_index].w <= 0 || result->boxes[box_index].h <= 0) {
        reset_primitive_motion_history();
        return APP_MOVEMENT_HOLD;
    }

    if (s_primitive_motion.dominant_side != dominant_side) {
        reset_primitive_motion_history();
        s_primitive_motion.dominant_side = dominant_side;
    }

    sample.valid = true;
    sample.cx = (float)result->boxes[box_index].x + (float)result->boxes[box_index].w * 0.5f;
    sample.cy = (float)result->boxes[box_index].y + (float)result->boxes[box_index].h * 0.5f;
    sample.area = (float)result->boxes[box_index].w * (float)result->boxes[box_index].h;
    sample.w = result->boxes[box_index].w;
    sample.h = result->boxes[box_index].h;
    sample.timestamp_us = esp_timer_get_time();

    s_primitive_motion.samples[s_primitive_motion.next] = sample;
    s_primitive_motion.next = (s_primitive_motion.next + 1) % PRIMITIVE_MOVEMENT_HISTORY;
    if (s_primitive_motion.count < PRIMITIVE_MOVEMENT_HISTORY) {
        s_primitive_motion.count++;
    }

    if (s_primitive_motion.count < 2) {
        return APP_MOVEMENT_HOLD;
    }

    first = primitive_motion_sample_at(0);
    last = primitive_motion_sample_at(s_primitive_motion.count - 1);
    if (!first.valid || !last.valid || first.area <= 0.0f || last.area <= 0.0f) {
        return APP_MOVEMENT_HOLD;
    }

    dx = last.cx - first.cx;
    dy = last.cy - first.cy;
    abs_dx = fabsf(dx);
    abs_dy = fabsf(dy);
    min_area = first.area < last.area ? first.area : last.area;
    max_area = first.area > last.area ? first.area : last.area;
    if (min_area > 0.0f) {
        area_ratio = max_area / min_area;
    }
    ref_w = last.w > 1 ? (float)last.w : 1.0f;
    ref_h = last.h > 1 ? (float)last.h : 1.0f;
    center_small = abs_dx < (PRIMITIVE_MOVEMENT_CENTER_SMALL_SCALE * ref_w) &&
                   abs_dy < (PRIMITIVE_MOVEMENT_CENTER_SMALL_SCALE * ref_h);
    center_depth = abs_dx < (PRIMITIVE_MOVEMENT_STRONG_TOWARD_AWAY_CENTER_SCALE * ref_w) &&
                   abs_dy < (PRIMITIVE_MOVEMENT_STRONG_TOWARD_AWAY_CENTER_SCALE * ref_h);

    if (center_depth &&
        area_ratio > PRIMITIVE_MOVEMENT_STRONG_TOWARD_AWAY_AREA_RATIO) {
        raw_movement = APP_MOVEMENT_TOWARD_AWAY;
    } else if (abs_dx > (PRIMITIVE_MOVEMENT_AXIS_MIN_SCALE * ref_w) &&
        abs_dx > (PRIMITIVE_MOVEMENT_AXIS_DOMINANCE * abs_dy)) {
        raw_movement = APP_MOVEMENT_LEFT_RIGHT;
    } else if (abs_dy > (PRIMITIVE_MOVEMENT_AXIS_MIN_SCALE * ref_h) &&
               abs_dy > (PRIMITIVE_MOVEMENT_AXIS_DOMINANCE * abs_dx)) {
        raw_movement = APP_MOVEMENT_UP_DOWN;
    } else if (center_small && area_ratio > PRIMITIVE_MOVEMENT_TOWARD_AWAY_AREA_RATIO) {
        raw_movement = APP_MOVEMENT_TOWARD_AWAY;
    } else if (abs_dx < (PRIMITIVE_MOVEMENT_HOLD_SCALE * ref_w) &&
               abs_dy < (PRIMITIVE_MOVEMENT_HOLD_SCALE * ref_h) &&
               area_ratio < PRIMITIVE_MOVEMENT_HOLD_MAX_AREA_RATIO) {
        raw_movement = APP_MOVEMENT_HOLD;
    } else {
        raw_movement = APP_MOVEMENT_HOLD;
    }

    raw_relative_motion = relative_motion_for_raw(raw_movement, dx, dy, area_ratio, first.area, last.area);
    latched_movement = apply_primitive_movement_latch(raw_movement, raw_relative_motion);
    log_primitive_motion_debug(frame_seq,
                               dx / ref_w,
                               dy / ref_h,
                               area_ratio,
                               center_small,
                               center_depth,
                               raw_movement,
                               latched_movement,
                               s_primitive_motion.latched_relative_motion);

    return latched_movement;
}

static int find_primitive_slot_by_side(const primitive_hand_slot_t slots[PRIMITIVE_MAX_HANDS],
                                       int slot_count,
                                       app_signer_side_t side)
{
    for (int i = 0; i < slot_count && i < PRIMITIVE_MAX_HANDS; i++) {
        if (slots[i].signer_side == side) {
            return i;
        }
    }
    return -1;
}

static app_primitive_state_t update_primitive_state(uint32_t frame_seq,
                                                    const ai_result_t *primitive_result,
                                                    int raw_hand_count,
                                                    const ai_result_t *classify_result,
                                                    const gesture_result_t *gestures,
                                                    int classify_hand_count,
                                                    primitive_hand_slot_t slots[PRIMITIVE_MAX_HANDS],
                                                    int *out_slot_count)
{
    app_primitive_state_t primitive = {
        .raw_hand_count = raw_hand_count,
        .hand_count = 0,
        .dominant_shape = GESTURE_ID_NO_HAND,
        .nondominant_shape = GESTURE_ID_NO_HAND,
        .bimanual_relation = APP_BIMANUAL_RELATION_SINGLE_HAND,
        .movement = APP_MOVEMENT_HOLD,
        .relative_motion = APP_RELATIVE_MOTION_HOLD,
        .location = APP_LOCATION_UNKNOWN,
        .dominant_side = APP_SIGNER_SIDE_NONE,
    };
    bool signer_left_present = false;
    bool signer_right_present = false;
    int slot_count = 0;
    int dominant_slot = -1;
    int nondominant_slot = -1;

    (void)frame_seq;
    slot_count = fill_primitive_hand_slots(primitive_result, slots);
    match_primitive_slots_to_classify(primitive_result,
                                      classify_result,
                                      classify_hand_count,
                                      slots,
                                      slot_count);
    if (out_slot_count) {
        *out_slot_count = slot_count;
    }

    if (slot_count <= 0) {
        reset_primitive_side_stability(APP_SIGNER_SIDE_LEFT);
        reset_primitive_side_stability(APP_SIGNER_SIDE_RIGHT);
        reset_primitive_motion_history();
        return primitive;
    }

    for (int i = 0; i < slot_count && i < PRIMITIVE_MAX_HANDS; i++) {
        int gesture_index = slots[i].classify_index;
        gesture_id_t raw = GESTURE_ID_NO_GESTURE;
        float score = 0.0f;
        bool no_classify_update = !gestures && classify_hand_count <= 0;

        if (no_classify_update) {
            primitive_side_stability_t *stability =
                primitive_side_stability(slots[i].signer_side);

            slots[i].stable_shape = (stability &&
                                     gesture_is_concrete_shape(stability->stable)) ?
                stability->stable : GESTURE_ID_NO_GESTURE;
            if (slots[i].signer_side == APP_SIGNER_SIDE_LEFT) {
                signer_left_present = true;
            } else if (slots[i].signer_side == APP_SIGNER_SIDE_RIGHT) {
                signer_right_present = true;
            }
            continue;
        }

        if (gestures && gesture_index >= 0 && gesture_index < classify_hand_count) {
            raw = gestures[gesture_index].gesture_id;
            score = gestures[gesture_index].score;
        }

        slots[i].stable_shape = update_primitive_side_stability(slots[i].signer_side,
                                                                raw,
                                                                score,
                                                                true);
        if (slots[i].signer_side == APP_SIGNER_SIDE_LEFT) {
            signer_left_present = true;
        } else if (slots[i].signer_side == APP_SIGNER_SIDE_RIGHT) {
            signer_right_present = true;
        }
    }

    if (!signer_left_present) {
        reset_primitive_side_stability(APP_SIGNER_SIDE_LEFT);
    }
    if (!signer_right_present) {
        reset_primitive_side_stability(APP_SIGNER_SIDE_RIGHT);
    }

    primitive.hand_count = slot_count;
    if (slot_count == 1) {
        dominant_slot = 0;
    } else {
        dominant_slot = find_primitive_slot_by_side(slots, slot_count, APP_SIGNER_SIDE_RIGHT);
        if (dominant_slot < 0) {
            dominant_slot = 0;
        }
        nondominant_slot = dominant_slot == 0 ? 1 : 0;
    }

    if (dominant_slot >= 0) {
        primitive.dominant_side = slots[dominant_slot].signer_side;
        primitive.dominant_shape = slots[dominant_slot].stable_shape;
        primitive.location = primitive_location_from_box(primitive_result, slots[dominant_slot].box_index);
        primitive.movement = update_primitive_movement(primitive.dominant_side,
                                                       frame_seq,
                                                       primitive_result,
                                                       slots[dominant_slot].box_index);
        primitive.relative_motion = s_primitive_motion.latched_relative_motion;
    }

    if (slot_count == 1) {
        primitive.nondominant_shape = GESTURE_ID_NO_HAND;
        primitive.bimanual_relation = APP_BIMANUAL_RELATION_SINGLE_HAND;
        return primitive;
    }

    if (nondominant_slot >= 0) {
        primitive.nondominant_shape = slots[nondominant_slot].stable_shape;
    }
    if (gesture_is_concrete_shape(primitive.dominant_shape) &&
        gesture_is_concrete_shape(primitive.nondominant_shape)) {
        primitive.bimanual_relation =
            primitive.dominant_shape == primitive.nondominant_shape ?
            APP_BIMANUAL_RELATION_SAME_SHAPE :
            APP_BIMANUAL_RELATION_DIFFERENT_SHAPE;
    } else {
        primitive.bimanual_relation = APP_BIMANUAL_RELATION_DUAL_HAND;
    }

    return primitive;
}

static bool primitive_state_equal(const app_primitive_state_t *a,
                                  const app_primitive_state_t *b)
{
    if (!a || !b) {
        return false;
    }

    return a->raw_hand_count == b->raw_hand_count &&
           a->hand_count == b->hand_count &&
           a->dominant_shape == b->dominant_shape &&
           a->nondominant_shape == b->nondominant_shape &&
           a->bimanual_relation == b->bimanual_relation &&
           a->movement == b->movement &&
           a->location == b->location &&
           a->dominant_side == b->dominant_side;
}

static bool should_skip_active_classify(void)
{
    return s_active_motion_classify_warmup_frames >= CLASSIFY_SKIP_ACTIVE_WARMUP_FRAMES &&
           s_primitive_motion.latched_movement != APP_MOVEMENT_HOLD &&
           s_primitive_motion.hold_grace_frames >=
               (PRIMITIVE_MOVEMENT_HOLD_GRACE_FRAMES - 1);
}

static void update_active_classify_warmup(const app_primitive_state_t *primitive)
{
    if (primitive && primitive->hand_count > 0 &&
        primitive->movement != APP_MOVEMENT_HOLD) {
        if (s_active_motion_classify_warmup_frames < 1000) {
            s_active_motion_classify_warmup_frames++;
        }
        return;
    }

    s_active_motion_classify_warmup_frames = 0;
}

static void log_classify_skip_active(const app_primitive_state_t *primitive,
                                     uint32_t frame_seq)
{
    int64_t now_us = esp_timer_get_time();

    if (!primitive ||
        now_us - s_last_classify_skip_log_us <
            (int64_t)CLASSIFY_SKIP_ACTIVE_LOG_MS * 1000LL) {
        return;
    }

    ESP_LOGI(TAG,
             "classify skip active seq=%" PRIu32 " move=%s rel=%s shape=%s",
             frame_seq,
             movement_name(primitive->movement),
             relative_motion_name(primitive->relative_motion),
             app_gesture_name(primitive->dominant_shape));
    s_last_classify_skip_log_us = now_us;
}

static void log_primitive_debug(uint32_t frame_seq,
                                const ai_result_t *primitive_result,
                                const primitive_filter_stats_t *filter_stats,
                                bool primitive_held,
                                const ai_result_t *classify_result,
                                const gesture_result_t *gestures,
                                const gesture_debug_info_t *debug_infos,
                                int classify_hand_count,
                                const primitive_hand_slot_t slots[PRIMITIVE_MAX_HANDS],
                                int slot_count,
                                const app_primitive_state_t *primitive)
{
    bool changed = false;
    bool periodic = false;
    const char *relation = "none";

    if (!primitive) {
        return;
    }

    s_primitive_log_counter++;
    changed = !s_last_primitive_valid ||
        !primitive_state_equal(primitive, &s_last_primitive_state);
    periodic = PRIMITIVE_LOG_INTERVAL > 0 &&
        (s_primitive_log_counter % PRIMITIVE_LOG_INTERVAL) == 0;

    if (!changed && !periodic) {
        return;
    }

    if (changed) {
        int rejected_edge = filter_stats ? filter_stats->rejected_edge : 0;
        int rejected_small = filter_stats ? filter_stats->rejected_small : 0;
        int rejected_weak = filter_stats ? filter_stats->rejected_weak : 0;
        int filtered_count = filter_stats ? filter_stats->filtered_count : primitive->hand_count;

        ESP_LOGI(TAG,
                 "hands_raw: frame=%" PRIu32 " raw_hand_count=%d filtered=%d hand_count=%d classify=%d held=%d rejected(edge=%d small=%d weak=%d)",
                 frame_seq,
                 primitive->raw_hand_count,
                 filtered_count,
                 primitive->hand_count,
                 classify_hand_count,
                 primitive_held ? 1 : 0,
                 rejected_edge,
                 rejected_small,
                 rejected_weak);
        for (int i = 0; i < slot_count && i < PRIMITIVE_MAX_HANDS; i++) {
            int box_index = slots[i].box_index;
            int classify_index = slots[i].classify_index;
            const char *raw_name = "-";
            float score = 0.0f;
            float detect_score = 0.0f;
            const gesture_debug_info_t *debug_info = NULL;

            if (gestures && classify_index >= 0 && classify_index < classify_hand_count) {
                raw_name = app_gesture_name(gestures[classify_index].gesture_id);
                score = gestures[classify_index].score;
            }
            if (debug_infos && classify_index >= 0 && classify_index < classify_hand_count &&
                debug_infos[classify_index].valid) {
                debug_info = &debug_infos[classify_index];
            }
            if (primitive_result && box_index >= 0 && box_index < primitive_result->count) {
                detect_score = primitive_result->boxes[box_index].score;
                ESP_LOGI(TAG,
                         "hands_raw[%d]: camera=%s signer=%s box=(x=%d y=%d w=%d h=%d score=%.2f) classify_idx=%d crop=(x=%d y=%d w=%d h=%d) profile=%s aspect=%.2f long_ratio=%.2f clamp=%d raw=%s score=%.2f stable=%s",
                         i,
                         slots[i].camera_side_name,
                         signer_side_name(slots[i].signer_side),
                         primitive_result->boxes[box_index].x,
                         primitive_result->boxes[box_index].y,
                         primitive_result->boxes[box_index].w,
                         primitive_result->boxes[box_index].h,
                         detect_score,
                         classify_index,
                         debug_info ? debug_info->crop_x : -1,
                         debug_info ? debug_info->crop_y : -1,
                         debug_info ? debug_info->crop_w : 0,
                         debug_info ? debug_info->crop_h : 0,
                         debug_info ? debug_info->profile_name : "-",
                         debug_info ? debug_info->aspect_ratio : 0.0f,
                         debug_info ? debug_info->crop_long_ratio : 0.0f,
                         debug_info && debug_info->clamped ? 1 : 0,
                         raw_name,
                         score,
                         app_gesture_name(slots[i].stable_shape));
            }
        }
    }

    relation = primitive->hand_count > 0 ?
        bimanual_relation_name(primitive->bimanual_relation) : "none";
    ESP_LOGI(TAG,
             "primitive%s: frame=%" PRIu32 " raw_hand_count=%d hand_count=%d dominant_side=%s dominant_shape=%s nondominant_shape=%s bimanual_relation=%s location=%s movement=%s",
             changed ? "_change" : "_summary",
             frame_seq,
             primitive->raw_hand_count,
             primitive->hand_count,
             signer_side_name(primitive->dominant_side),
             app_gesture_name(primitive->dominant_shape),
             app_gesture_name(primitive->nondominant_shape),
             relation,
             location_name(primitive->location),
             movement_name(primitive->movement));

    if (changed) {
        s_last_primitive_state = *primitive;
        s_last_primitive_valid = true;
    }
}

static void publish_primitive_output(const app_primitive_state_t *primitive,
                                     uint32_t frame_seq,
                                     int classify_hand_count,
                                     bool primitive_held,
                                     const primitive_filter_stats_t *filter_stats)
{
    int rejected_edge = filter_stats ? filter_stats->rejected_edge : 0;
    int rejected_small = filter_stats ? filter_stats->rejected_small : 0;
    int rejected_weak = filter_stats ? filter_stats->rejected_weak : 0;

    if (!primitive) {
        return;
    }

    app_output_set_primitive_state(primitive->raw_hand_count,
                                   primitive->hand_count,
                                   classify_hand_count,
                                   primitive_held,
                                   rejected_edge,
                                   rejected_small,
                                   rejected_weak,
                                   signer_side_name(primitive->dominant_side),
                                   location_name(primitive->location),
                                   movement_name(primitive->movement),
                                   primitive->hand_count > 0 ?
                                       bimanual_relation_name(primitive->bimanual_relation) :
                                       "none",
                                   app_gesture_name(primitive->dominant_shape),
                                   app_gesture_name(primitive->nondominant_shape));

    if (primitive->hand_count > 0) {
        app_cloud_frame_t cloud_frame = {
            .frame_seq = frame_seq,
            .raw_hand_count = primitive->raw_hand_count,
            .hand_count = primitive->hand_count,
            .dominant_side = primitive->dominant_side,
            .location = primitive->location,
            .movement = primitive->movement,
            .relative_motion = primitive->relative_motion,
            .bimanual_relation = primitive->bimanual_relation,
            .dominant_shape = primitive->dominant_shape,
            .nondominant_shape = primitive->nondominant_shape,
        };
        app_cloud_submit_frame(&cloud_frame);
    }
}

static void log_detect_result(const ai_result_t *result)
{
    if (!result) {
        return;
    }

    s_detect_log_counter++;
    if ((s_detect_log_counter % RAW_LOG_INTERVAL) != 0) {
        return;
    }

    ESP_LOGI(TAG, "detect: hands=%d", result->count);
    for (int i = 0; i < result->count && i < AI_RESULT_MAX_BOXES; i++) {
        ESP_LOGI(TAG, "detect[%d]: x=%d y=%d w=%d h=%d score=%.2f",
                 i,
                 result->boxes[i].x,
                 result->boxes[i].y,
                 result->boxes[i].w,
                 result->boxes[i].h,
                 result->boxes[i].score);
    }
}

static gesture_id_t update_primary_stability(gesture_result_t *gestures, int hand_count)
{
    if (!gestures || hand_count <= 0) {
        s_primary_candidate = GESTURE_ID_NO_GESTURE;
        s_primary_candidate_frames = 0;
        s_stable_primary = GESTURE_ID_NO_GESTURE;
        s_stable_primary_score = 0.0f;
        s_stable_miss_frames = 0;
        reset_primary_box_tracker();
        return GESTURE_ID_NO_GESTURE;
    }

    gesture_id_t primary = gestures[0].gesture_id;
    float score = gestures[0].score;

    if (gesture_is_non_stable_state(primary) || score < MIN_GESTURE_SCORE) {
        s_primary_candidate = primary;
        s_primary_candidate_frames = 0;
        if (s_stable_primary != GESTURE_ID_NO_GESTURE &&
            s_stable_miss_frames < PRIMARY_STABLE_MISS_GRACE &&
            should_hold_previous_stable(primary, score)) {
            s_stable_miss_frames++;
            ESP_LOGI(TAG, "stable_hold: primary=%s miss=%d raw=%s score=%.2f",
                     app_gesture_name(s_stable_primary),
                     s_stable_miss_frames,
                     app_gesture_name(primary),
                     score);
            return s_stable_primary;
        }
        s_stable_primary = GESTURE_ID_NO_GESTURE;
        s_stable_primary_score = 0.0f;
        s_stable_miss_frames = 0;
        return GESTURE_ID_NO_GESTURE;
    }

    s_stable_miss_frames = 0;

    if (primary == s_primary_candidate) {
        s_primary_candidate_frames++;
    } else {
        s_primary_candidate = primary;
        s_primary_candidate_frames = 1;
    }

    gestures[0].stable_count = s_primary_candidate_frames;
    gestures[0].stable = s_primary_candidate_frames >= STABLE_FRAMES;

    if (gestures[0].stable) {
        if (s_stable_primary != primary) {
            ESP_LOGI(TAG, "stable: primary=%s score=%.2f frames=%d",
                     app_gesture_name(primary), score, s_primary_candidate_frames);
        }
        s_stable_primary = primary;
        s_stable_primary_score = score;
        return primary;
    }

    return GESTURE_ID_NO_GESTURE;
}

static void log_gesture_result(const gesture_result_t *gestures, int hand_count)
{
    if (!gestures || hand_count <= 0) {
        return;
    }

    s_classify_log_counter++;
    if ((s_classify_log_counter % RAW_LOG_INTERVAL) != 0) {
        return;
    }

    for (int i = 0; i < hand_count && i < AI_RESULT_MAX_BOXES; i++) {
        ESP_LOGI(TAG, "raw[%d]: gesture=%s score=%.2f stable=%d count=%d",
                 i,
                 app_gesture_name(gestures[i].gesture_id),
                 gestures[i].score,
                 gestures[i].stable ? 1 : 0,
                 gestures[i].stable_count);
    }
}

static const char *classify_reason_name(const gesture_result_t *gesture,
                                        const gesture_debug_info_t *debug_info,
                                        bool profile_switched)
{
    if (debug_info && debug_info->clamped) {
        return "clamped";
    }
    if (profile_switched) {
        return "profile_switch";
    }
    if (!gesture) {
        return "stale_drop";
    }
    if (gesture->gesture_id == GESTURE_ID_NO_GESTURE) {
        return "no_gesture";
    }
    if (gesture->gesture_id == GESTURE_ID_NO_HAND) {
        return "no_hand";
    }
    if (gesture->score < MIN_GESTURE_SCORE) {
        return "low_score";
    }
    return "ok";
}

static void update_primary_summary_counts(gesture_id_t gesture_id)
{
    switch (gesture_id) {
    case GESTURE_ID_ONE:
        s_summary_one++;
        break;
    case GESTURE_ID_TWO:
        s_summary_two++;
        break;
    case GESTURE_ID_THREE:
        s_summary_three++;
        break;
    case GESTURE_ID_FOUR:
        s_summary_four++;
        break;
    case GESTURE_ID_FIVE:
        s_summary_five++;
        break;
    case GESTURE_ID_LIKE:
        s_summary_like++;
        break;
    case GESTURE_ID_OK:
        s_summary_ok++;
        break;
    case GESTURE_ID_CALL:
        s_summary_call++;
        break;
    case GESTURE_ID_DISLIKE:
        s_summary_dislike++;
        break;
    case GESTURE_ID_NO_GESTURE:
        s_summary_no_gesture++;
        break;
    case GESTURE_ID_NO_HAND:
        s_summary_no_hand++;
        break;
    default:
        s_summary_other++;
        break;
    }
}

static void log_primary_debug_summary_if_needed(void)
{
    if (s_primary_debug_frame_counter <= 0 ||
        (s_primary_debug_frame_counter % DEBUG_SUMMARY_INTERVAL) != 0) {
        return;
    }

    ESP_LOGI(TAG,
             "primary_summary: frames=%d one=%d two=%d three=%d four=%d five=%d like=%d ok=%d call=%d dislike=%d no_gesture=%d no_hand=%d other=%d",
             s_primary_debug_frame_counter,
             s_summary_one,
             s_summary_two,
             s_summary_three,
             s_summary_four,
             s_summary_five,
             s_summary_like,
             s_summary_ok,
             s_summary_call,
             s_summary_dislike,
             s_summary_no_gesture,
             s_summary_no_hand,
             s_summary_other);

    s_primary_debug_frame_counter = 0;
    s_summary_one = 0;
    s_summary_two = 0;
    s_summary_three = 0;
    s_summary_four = 0;
    s_summary_five = 0;
    s_summary_like = 0;
    s_summary_ok = 0;
    s_summary_call = 0;
    s_summary_dislike = 0;
    s_summary_no_gesture = 0;
    s_summary_no_hand = 0;
    s_summary_other = 0;
}

static void log_primary_debug_frame(uint32_t frame_seq,
                                    const ai_result_t *detect_result,
                                    const ai_result_t *classify_result,
                                    const gesture_result_t *gesture,
                                    const gesture_debug_info_t *debug_info,
                                    const char *stable_name,
                                    const char *reason)
{
    int detect_x = -1;
    int detect_y = -1;
    int detect_w = 0;
    int detect_h = 0;
    int classify_x = -1;
    int classify_y = -1;
    int classify_w = 0;
    int classify_h = 0;

    if (detect_result && detect_result->count > 0) {
        detect_x = detect_result->boxes[0].x;
        detect_y = detect_result->boxes[0].y;
        detect_w = detect_result->boxes[0].w;
        detect_h = detect_result->boxes[0].h;
    }
    if (classify_result && classify_result->count > 0) {
        classify_x = classify_result->boxes[0].x;
        classify_y = classify_result->boxes[0].y;
        classify_w = classify_result->boxes[0].w;
        classify_h = classify_result->boxes[0].h;
    }

    ESP_LOGI(TAG,
             "primary_debug: frame=%" PRIu32 " detect=(x=%d y=%d w=%d h=%d) classify=(x=%d y=%d w=%d h=%d) crop=(x=%d y=%d w=%d h=%d) profile=%s bucket=%s blend=%.2f short_ratio=%.2f long_ratio=%.2f area_ratio=%.2f center_y_bias=%.2f clamp=%d raw=%s score=%.2f stable_count=%d stable=%s reason=%s",
             frame_seq,
             detect_x, detect_y, detect_w, detect_h,
             classify_x, classify_y, classify_w, classify_h,
             debug_info ? debug_info->crop_x : -1,
             debug_info ? debug_info->crop_y : -1,
             debug_info ? debug_info->crop_w : 0,
             debug_info ? debug_info->crop_h : 0,
             (debug_info && debug_info->valid) ? debug_info->profile_name : "-",
             (debug_info && debug_info->valid) ? debug_info->aspect_bucket : "-",
             debug_info ? debug_info->slender_blend : 0.0f,
             debug_info ? debug_info->crop_short_ratio : 0.0f,
             debug_info ? debug_info->crop_long_ratio : 0.0f,
             debug_info ? debug_info->crop_area_ratio : 0.0f,
             debug_info ? debug_info->center_y_bias : 0.0f,
             (debug_info && debug_info->clamped) ? 1 : 0,
             gesture ? app_gesture_name(gesture->gesture_id) : "-",
             gesture ? gesture->score : 0.0f,
             gesture ? gesture->stable_count : 0,
             stable_name ? stable_name : "-",
             reason ? reason : "-");
}

static bool should_log_primary_debug(const gesture_result_t *gesture,
                                     const char *reason)
{
    s_primary_debug_log_counter++;
    if ((s_primary_debug_log_counter % DEBUG_SUMMARY_INTERVAL) == 0) {
        return true;
    }
    if (!gesture) {
        return false;
    }
    if (gesture_is_concrete_shape(gesture->gesture_id)) {
        return true;
    }
    if (reason && strcmp(reason, "profile_switch") == 0) {
        return true;
    }
    if (reason && strcmp(reason, "clamped") == 0) {
        return true;
    }
    return false;
}

static void log_post_latest_only_drop(uint32_t frame_seq, uint32_t latest_seq)
{
    s_stale_drop_log_counter++;
    if ((s_stale_drop_log_counter % DEBUG_SUMMARY_INTERVAL) != 0) {
        return;
    }
    ESP_LOGI(TAG,
             "post stale drop latest_only seq=%" PRIu32 " latest=%" PRIu32 " drops=%d",
             frame_seq,
             latest_seq,
             s_stale_drop_log_counter);
}

static void present_camera_frame(app_system_context_t *ctx)
{
    uint16_t *src = (uint16_t *)ctx->camera_buffer;
    uint16_t *dst = (uint16_t *)ctx->frame_buffer;
    const int panel_x2 = APP_UI_PANEL_X + APP_UI_PANEL_W;
    const int panel_y2 = APP_UI_PANEL_Y + APP_UI_PANEL_H;

    if (!src || !dst) {
        return;
    }

    for (int y = 0; y < APP_LCD_V_RES; y++) {
        uint16_t *src_row = src + y * APP_LCD_H_RES;
        uint16_t *dst_row = dst + y * APP_LCD_H_RES;

        if (y < APP_UI_PANEL_Y || y >= panel_y2) {
            memcpy(dst_row, src_row, APP_LCD_H_RES * sizeof(uint16_t));
            continue;
        }

        if (APP_UI_PANEL_X > 0) {
            memcpy(dst_row, src_row, APP_UI_PANEL_X * sizeof(uint16_t));
        }
        if (panel_x2 < APP_LCD_H_RES) {
            memcpy(dst_row + panel_x2, src_row + panel_x2,
                   (APP_LCD_H_RES - panel_x2) * sizeof(uint16_t));
        }
    }
}

static void plot_bbox_pixel_avoid_panel(uint16_t *fb,
                                        int fb_w,
                                        int fb_h,
                                        int x,
                                        int y,
                                        uint16_t color)
{
    if (!fb || x < 0 || x >= fb_w || y < 0 || y >= fb_h) {
        return;
    }
    if (app_ui_panel_contains(x, y)) {
        return;
    }
    fb[y * fb_w + x] = color;
}

static void draw_bbox_rgb565_avoid_panel(uint16_t *fb,
                                         int fb_w,
                                         int fb_h,
                                         int x,
                                         int y,
                                         int bw,
                                         int bh,
                                         uint16_t color)
{
    int x0 = (x < 0) ? 0 : x;
    int y0 = (y < 0) ? 0 : y;
    int x1 = (x + bw > fb_w) ? fb_w : x + bw;
    int y1 = (y + bh > fb_h) ? fb_h : y + bh;
    const int thickness = 2;

    for (int i = x0; i < x1; i++) {
        for (int t = 0; t < thickness; t++) {
            plot_bbox_pixel_avoid_panel(fb, fb_w, fb_h, i, y0 + t, color);
            plot_bbox_pixel_avoid_panel(fb, fb_w, fb_h, i, y1 - 1 - t, color);
        }
    }
    for (int j = y0; j < y1; j++) {
        for (int t = 0; t < thickness; t++) {
            plot_bbox_pixel_avoid_panel(fb, fb_w, fb_h, x0 + t, j, color);
            plot_bbox_pixel_avoid_panel(fb, fb_w, fb_h, x1 - 1 - t, j, color);
        }
    }
}

static void draw_overlay_state(app_system_context_t *ctx, const overlay_state_t *overlay)
{
    uint16_t *fb = (uint16_t *)ctx->frame_buffer;

    if (!fb || !overlay) {
        return;
    }

    for (int i = 0; i < overlay->hand_count; i++) {
        draw_bbox_rgb565_avoid_panel(fb, APP_LCD_H_RES, APP_LCD_V_RES,
                                     overlay->detect_result.boxes[i].x,
                                     overlay->detect_result.boxes[i].y,
                                     overlay->detect_result.boxes[i].w,
                                     overlay->detect_result.boxes[i].h,
                                     RGB565_GREEN);
    }

    if (overlay->classify_hand_count > 0 &&
        overlay->primary_index >= 0 &&
        overlay->primary_index < overlay->classify_hand_count) {
        draw_bbox_rgb565_avoid_panel(fb, APP_LCD_H_RES, APP_LCD_V_RES,
                                     overlay->classify_result.boxes[overlay->primary_index].x,
                                     overlay->classify_result.boxes[overlay->primary_index].y,
                                     overlay->classify_result.boxes[overlay->primary_index].w,
                                     overlay->classify_result.boxes[overlay->primary_index].h,
                                     RGB565_YELLOW);
    }

    cache_msync_aligned(ctx->frame_buffer, ctx->frame_buffer_size,
                        ESP_CACHE_MSYNC_FLAG_DIR_C2M);
}

static int detect_acquire_free_slot(app_system_context_t *ctx)
{
    int slot_id = -1;

    if (!ctx || !ctx->detect_slot_mutex) {
        return -1;
    }

    if (xSemaphoreTake(ctx->detect_slot_mutex, pdMS_TO_TICKS(5)) != pdTRUE) {
        return -1;
    }

    for (int i = 0; i < AI_PIPELINE_SLOT_COUNT; i++) {
        if (ctx->detect_slot_states[i] == DETECT_SLOT_FREE) {
            ctx->detect_slot_states[i] = DETECT_SLOT_FILLING;
            slot_id = i;
            break;
        }
    }

    if (slot_id < 0) {
        int recycle = ctx->latest_ready_slot;
        if (recycle < 0 || recycle >= AI_PIPELINE_SLOT_COUNT ||
            ctx->detect_slot_states[recycle] != DETECT_SLOT_READY) {
            recycle = -1;
            for (int i = 0; i < AI_PIPELINE_SLOT_COUNT; i++) {
                if (ctx->detect_slot_states[i] == DETECT_SLOT_READY) {
                    recycle = i;
                    break;
                }
            }
        }
        if (recycle >= 0) {
            ctx->detect_slot_states[recycle] = DETECT_SLOT_FILLING;
            if (ctx->latest_ready_slot == recycle) {
                ctx->latest_ready_slot = -1;
            }
            slot_id = recycle;
        }
    }

    xSemaphoreGive(ctx->detect_slot_mutex);
    return slot_id;
}

static void detect_publish_ready_slot(app_system_context_t *ctx, int slot_id)
{
    uint8_t queue_value = (uint8_t)slot_id;

    if (!ctx || slot_id < 0 || slot_id >= AI_PIPELINE_SLOT_COUNT) {
        return;
    }

    if (ctx->detect_slot_mutex &&
        xSemaphoreTake(ctx->detect_slot_mutex, pdMS_TO_TICKS(5)) == pdTRUE) {
        int prev = ctx->latest_ready_slot;

        if (prev >= 0 && prev < AI_PIPELINE_SLOT_COUNT &&
            prev != slot_id && ctx->detect_slot_states[prev] == DETECT_SLOT_READY) {
            ctx->detect_slot_states[prev] = DETECT_SLOT_FREE;
        }

        ctx->detect_slot_states[slot_id] = DETECT_SLOT_READY;
        ctx->latest_ready_slot = slot_id;
        xSemaphoreGive(ctx->detect_slot_mutex);
    }

    xQueueOverwrite(ctx->detect_slot_queue, &queue_value);
}

static bool detect_claim_ready_slot(app_system_context_t *ctx, int *out_slot_id)
{
    uint8_t queue_value = 0;

    if (!ctx || !out_slot_id) {
        return false;
    }

    if (xQueueReceive(ctx->detect_slot_queue, &queue_value, portMAX_DELAY) != pdTRUE) {
        return false;
    }

    if (!ctx->detect_slot_mutex ||
        xSemaphoreTake(ctx->detect_slot_mutex, pdMS_TO_TICKS(5)) != pdTRUE) {
        return false;
    }

    int slot_id = (int)queue_value;
    int latest_slot = ctx->latest_ready_slot;

    if (latest_slot >= 0 && latest_slot < AI_PIPELINE_SLOT_COUNT &&
        ctx->detect_slot_states[latest_slot] == DETECT_SLOT_READY) {
        slot_id = latest_slot;
    }

    if (slot_id < 0 || slot_id >= AI_PIPELINE_SLOT_COUNT ||
        ctx->detect_slot_states[slot_id] != DETECT_SLOT_READY) {
        xSemaphoreGive(ctx->detect_slot_mutex);
        return false;
    }

    for (int i = 0; i < AI_PIPELINE_SLOT_COUNT; i++) {
        if (i != slot_id && ctx->detect_slot_states[i] == DETECT_SLOT_READY) {
            log_post_latest_only_drop(ctx->detect_slots[i].frame_seq,
                                      ctx->detect_slots[slot_id].frame_seq);
            ctx->detect_slot_states[i] = DETECT_SLOT_FREE;
        }
    }

    ctx->detect_slot_states[slot_id] = DETECT_SLOT_BUSY;
    if (ctx->latest_ready_slot == slot_id) {
        ctx->latest_ready_slot = -1;
    }
    xSemaphoreGive(ctx->detect_slot_mutex);

    *out_slot_id = slot_id;
    return true;
}

static void detect_release_slot(app_system_context_t *ctx, int slot_id)
{
    if (!ctx || !ctx->detect_slot_mutex || slot_id < 0 || slot_id >= AI_PIPELINE_SLOT_COUNT) {
        return;
    }

    if (xSemaphoreTake(ctx->detect_slot_mutex, pdMS_TO_TICKS(5)) == pdTRUE) {
        ctx->detect_slot_states[slot_id] = DETECT_SLOT_FREE;
        xSemaphoreGive(ctx->detect_slot_mutex);
    }
}

static void overlay_snapshot(app_system_context_t *ctx, overlay_state_t *out_overlay)
{
    if (!ctx || !out_overlay || !ctx->overlay_mutex) {
        return;
    }

    if (xSemaphoreTake(ctx->overlay_mutex, pdMS_TO_TICKS(5)) == pdTRUE) {
        *out_overlay = ctx->overlay_state;
        xSemaphoreGive(ctx->overlay_mutex);
    }
}

static uint32_t overlay_current_frame_seq(app_system_context_t *ctx)
{
    uint32_t frame_seq = 0;

    if (!ctx || !ctx->overlay_mutex) {
        return 0;
    }

    if (xSemaphoreTake(ctx->overlay_mutex, pdMS_TO_TICKS(5)) == pdTRUE) {
        frame_seq = ctx->overlay_state.frame_seq;
        xSemaphoreGive(ctx->overlay_mutex);
    }

    return frame_seq;
}

static void overlay_update(app_system_context_t *ctx,
                           const detect_packet_t *packet,
                           const ai_result_t *primitive_result,
                           const ai_result_t *classify_result,
                           int classify_hand_count,
                           const gesture_result_t *gestures,
                           int primary_index,
                           int stable_primary_index)
{
    if (!ctx || !packet || !ctx->overlay_mutex) {
        return;
    }

    if (xSemaphoreTake(ctx->overlay_mutex, pdMS_TO_TICKS(5)) != pdTRUE) {
        return;
    }

    ctx->overlay_state.frame_seq = packet->frame_seq;
    if (primitive_result) {
        ctx->overlay_state.detect_result = *primitive_result;
        ctx->overlay_state.hand_count = primitive_result->count;
    } else {
        ctx->overlay_state.detect_result = packet->detect_result;
        ctx->overlay_state.hand_count = packet->hand_count;
    }
    if (classify_result) {
        ctx->overlay_state.classify_result = *classify_result;
        ctx->overlay_state.classify_hand_count = classify_hand_count;
    } else {
        memset(&ctx->overlay_state.classify_result, 0, sizeof(ctx->overlay_state.classify_result));
        ctx->overlay_state.classify_hand_count = 0;
    }
    ctx->overlay_state.primary_index = primary_index;
    ctx->overlay_state.stable_primary_index = stable_primary_index;

    for (int i = 0; i < AI_RESULT_MAX_BOXES; i++) {
        if (gestures && i < classify_hand_count) {
            ctx->overlay_state.gestures[i] = gestures[i];
        } else {
            memset(&ctx->overlay_state.gestures[i], 0, sizeof(ctx->overlay_state.gestures[i]));
        }
    }

    xSemaphoreGive(ctx->overlay_mutex);
}

static void overlay_update_detect_only(app_system_context_t *ctx,
                                       uint32_t frame_seq,
                                       const ai_result_t *detect_result)
{
    if (!ctx || !detect_result || !ctx->overlay_mutex) {
        return;
    }

    if (xSemaphoreTake(ctx->overlay_mutex, pdMS_TO_TICKS(5)) != pdTRUE) {
        return;
    }

    if (detect_result->count <= 0) {
        xSemaphoreGive(ctx->overlay_mutex);
        return;
    }

    ctx->overlay_state.frame_seq = frame_seq;
    ctx->overlay_state.detect_result = *detect_result;
    ctx->overlay_state.hand_count = detect_result->count;
    memset(&ctx->overlay_state.classify_result, 0, sizeof(ctx->overlay_state.classify_result));
    ctx->overlay_state.classify_hand_count = 0;
    ctx->overlay_state.primary_index = -1;
    ctx->overlay_state.stable_primary_index = -1;
    memset(ctx->overlay_state.gestures, 0, sizeof(ctx->overlay_state.gestures));

    xSemaphoreGive(ctx->overlay_mutex);
}

static void ai_detect_task(void *arg)
{
    app_system_context_t *ctx = (app_system_context_t *)arg;
    uint16_t *camera_frame = (uint16_t *)ctx->camera_buffer;
    int detect_cycle = 0;
    uint32_t frame_seq = 0;
    int64_t last_detect_us = 0;

    ESP_LOGI(TAG, "AI detect task started on core %d", xPortGetCoreID());

    if (app_hand_detect_init() != ESP_OK) {
        ESP_LOGE(TAG, "Hand detect init failed, task exiting");
        vTaskDelete(NULL);
        return;
    }

    while (1) {
        if (ctx->frame_ready_sem) {
            xSemaphoreTake(ctx->frame_ready_sem, pdMS_TO_TICKS(DETECT_INTERVAL_MS));
        } else {
            vTaskDelay(pdMS_TO_TICKS(DETECT_INTERVAL_MS));
        }

        int64_t now_us = esp_timer_get_time();
        if ((now_us - last_detect_us) < (DETECT_INTERVAL_MS * 1000LL)) {
            vTaskDelay(1);
            continue;
        }
        last_detect_us = now_us;

        cache_msync_aligned(ctx->camera_buffer, ctx->camera_buffer_size,
                            ESP_CACHE_MSYNC_FLAG_DIR_M2C);
        app_camera_auto_adjust(ctx, camera_frame, APP_LCD_H_RES, APP_LCD_V_RES);

        detect_cycle++;

        ai_result_t result = {0};
        int64_t t0 = esp_timer_get_time();
        int count = app_hand_detect_run(camera_frame, APP_LCD_H_RES, APP_LCD_V_RES, &result);
        int64_t t1 = esp_timer_get_time();
        sort_detect_boxes(&result);
        dedup_detect_result(&result);
        count = result.count;
        log_detect_result(&result);
        overlay_update_detect_only(ctx, frame_seq + 1, &result);

        if (detect_cycle <= 10 || (detect_cycle % 30) == 0) {
            ESP_LOGI(TAG, "Cycle %d: detect=%d hands, %.1fms",
                     detect_cycle, count, (t1 - t0) / 1000.0f);
        }

        int slot_id = detect_acquire_free_slot(ctx);
        if (slot_id < 0) {
            s_drop_detect_counter++;
            if (detect_cycle <= 10 || (detect_cycle % 20) == 0 || (s_drop_detect_counter % 5) == 0) {
                ESP_LOGW(TAG, "Drop detect packet: no free slot (drops=%d)", s_drop_detect_counter);
            }
            vTaskDelay(1);
            continue;
        }

        detect_packet_t *packet = &ctx->detect_slots[slot_id];
        uint16_t *frame_snapshot = packet->frame_rgb565;
        memset(packet, 0, sizeof(*packet));
        packet->frame_rgb565 = frame_snapshot;
        packet->frame_seq = ++frame_seq;
        packet->detect_result = result;
        packet->hand_count = result.count;
        if (packet->frame_rgb565 && result.count > 0) {
            memcpy(packet->frame_rgb565, camera_frame, ctx->camera_buffer_size);
            cache_msync_aligned(packet->frame_rgb565, ctx->camera_buffer_size,
                                ESP_CACHE_MSYNC_FLAG_DIR_C2M);
        }

        detect_publish_ready_slot(ctx, slot_id);
        vTaskDelay(1);
    }
}

static void ai_post_task(void *arg)
{
    app_system_context_t *ctx = (app_system_context_t *)arg;

    ESP_LOGI(TAG, "AI post task started on core %d", xPortGetCoreID());

    if (app_hand_gesture_init() != ESP_OK) {
        ESP_LOGE(TAG, "Hand gesture init failed, task exiting");
        vTaskDelete(NULL);
        return;
    }

    while (1) {
        int slot_id = -1;
        if (!detect_claim_ready_slot(ctx, &slot_id)) {
            vTaskDelay(1);
            continue;
        }

        detect_packet_t *packet = &ctx->detect_slots[slot_id];
        if (packet->frame_seq < overlay_current_frame_seq(ctx)) {
            log_post_latest_only_drop(packet->frame_seq, overlay_current_frame_seq(ctx));
            detect_release_slot(ctx, slot_id);
            vTaskDelay(1);
            continue;
        }

        ai_result_t classify_result = {0};
        gesture_result_t local_gestures[AI_RESULT_MAX_BOXES] = {0};
        gesture_debug_info_t local_debug_infos[AI_RESULT_MAX_BOXES] = {0};
        const char *stable_name = "-";
        const char *classify_reason = "-";
        int classify_hand_count = 0;
        int primary_index = -1;
        int stable_primary_index = -1;
        gesture_id_t stable_primary = GESTURE_ID_NO_GESTURE;
        bool profile_switched = false;
        ai_result_t primitive_raw_result = {0};
        ai_result_t primitive_result = {0};
        primitive_filter_stats_t primitive_filter_stats = {0};
        bool primitive_held = false;
        primitive_hand_slot_t primitive_slots[PRIMITIVE_MAX_HANDS] = {0};
        int primitive_slot_count = 0;
        app_primitive_state_t primitive_state = {0};
        bool skip_classify = packet->hand_count > 0 &&
                             packet->frame_rgb565 &&
                             should_skip_active_classify();

        prepare_primitive_candidates(&packet->detect_result,
                                     &primitive_raw_result,
                                     &primitive_filter_stats);
        primitive_held = update_stable_primitive_candidates(&primitive_raw_result,
                                                            &primitive_result);

        if (skip_classify) {
            primitive_state = update_primitive_state(packet->frame_seq,
                                                     &primitive_result,
                                                     primitive_filter_stats.raw_count,
                                                     NULL,
                                                     NULL,
                                                     0,
                                                     primitive_slots,
                                                     &primitive_slot_count);
            log_primitive_debug(packet->frame_seq,
                                &primitive_result,
                                &primitive_filter_stats,
                                primitive_held,
                                NULL,
                                NULL,
                                NULL,
                                0,
                                primitive_slots,
                                primitive_slot_count,
                                &primitive_state);
            log_classify_skip_active(&primitive_state, packet->frame_seq);
        } else if (packet->hand_count > 0 && packet->frame_rgb565) {
            int recognized_count = 0;

            classify_result = packet->detect_result;
            dedup_detect_result(&classify_result);
            promote_tracked_primary_box(&classify_result);
            smooth_primary_classify_box(&classify_result);
            limit_classify_candidates(&classify_result);
            classify_hand_count = classify_result.count;
            log_classify_boxes(&packet->detect_result, &classify_result);
            primary_index = classify_hand_count > 0 ? 0 : -1;

            cache_msync_aligned(packet->frame_rgb565, ctx->camera_buffer_size,
                                ESP_CACHE_MSYNC_FLAG_DIR_M2C);
            recognized_count = app_hand_gesture_recognize(packet->frame_rgb565,
                                                          APP_LCD_H_RES,
                                                          APP_LCD_V_RES,
                                                          &classify_result,
                                                          local_gestures,
                                                          AI_RESULT_MAX_BOXES,
                                                          local_debug_infos,
                                                          AI_RESULT_MAX_BOXES);
            if (recognized_count < classify_hand_count) {
                classify_hand_count = recognized_count;
            }
            primitive_state = update_primitive_state(packet->frame_seq,
                                                     &primitive_result,
                                                     primitive_filter_stats.raw_count,
                                                     &classify_result,
                                                     local_gestures,
                                                     classify_hand_count,
                                                     primitive_slots,
                                                     &primitive_slot_count);
            log_primitive_debug(packet->frame_seq,
                                &primitive_result,
                                &primitive_filter_stats,
                                primitive_held,
                                &classify_result,
                                local_gestures,
                                local_debug_infos,
                                classify_hand_count,
                                primitive_slots,
                                primitive_slot_count,
                                &primitive_state);
            stable_primary = update_primary_stability(local_gestures, classify_hand_count);
            log_gesture_result(local_gestures, classify_hand_count);
            if (classify_hand_count > 0 && local_debug_infos[0].valid) {
                profile_switched = (s_last_primary_profile[0] != '\0') &&
                    (strcmp(s_last_primary_profile, local_debug_infos[0].profile_name) != 0);
                strncpy(s_last_primary_profile, local_debug_infos[0].profile_name,
                        sizeof(s_last_primary_profile) - 1);
                s_last_primary_profile[sizeof(s_last_primary_profile) - 1] = '\0';
            }
            if (stable_primary != GESTURE_ID_NO_GESTURE) {
                stable_name = app_gesture_name(stable_primary);
                stable_primary_index = 0;
                if (classify_hand_count <= 0 ||
                    gesture_is_non_stable_state(local_gestures[0].gesture_id) ||
                    local_gestures[0].score < MIN_GESTURE_SCORE) {
                    stable_primary_index = 0;
                }
            }
            if (classify_hand_count > 0) {
                classify_reason = classify_reason_name(&local_gestures[0],
                                                       &local_debug_infos[0],
                                                       profile_switched);
                if (should_log_primary_debug(&local_gestures[0], classify_reason)) {
                    log_primary_debug_frame(packet->frame_seq,
                                            &packet->detect_result,
                                            &classify_result,
                                            &local_gestures[0],
                                            &local_debug_infos[0],
                                            stable_name,
                                            classify_reason);
                }
                update_primary_summary_counts(local_gestures[0].gesture_id);
                s_primary_debug_frame_counter++;
                log_primary_debug_summary_if_needed();
            }
        } else {
            s_primary_candidate = GESTURE_ID_NO_GESTURE;
            s_primary_candidate_frames = 0;
            s_stable_primary = GESTURE_ID_NO_GESTURE;
            s_stable_primary_score = 0.0f;
            s_stable_miss_frames = 0;
            s_last_primary_profile[0] = '\0';
            reset_primary_box_tracker();
            primitive_state = update_primitive_state(packet->frame_seq,
                                                     &primitive_result,
                                                     primitive_filter_stats.raw_count,
                                                     &classify_result,
                                                     local_gestures,
                                                     0,
                                                     primitive_slots,
                                                     &primitive_slot_count);
            log_primitive_debug(packet->frame_seq,
                                &primitive_result,
                                &primitive_filter_stats,
                                primitive_held,
                                &classify_result,
                                local_gestures,
                                NULL,
                                0,
                                primitive_slots,
                                primitive_slot_count,
                                &primitive_state);
        }

        update_active_classify_warmup(&primitive_state);
        publish_primitive_output(&primitive_state,
                                 packet->frame_seq,
                                 classify_hand_count,
                                 primitive_held,
                                 &primitive_filter_stats);

        if (packet->frame_seq < overlay_current_frame_seq(ctx)) {
            log_post_latest_only_drop(packet->frame_seq, overlay_current_frame_seq(ctx));
            detect_release_slot(ctx, slot_id);
            vTaskDelay(1);
            continue;
        }

        overlay_update(ctx,
                       packet,
                       &primitive_result,
                       classify_result.count > 0 ? &classify_result : NULL,
                       classify_result.count,
                       local_gestures,
                       primary_index,
                       stable_primary_index);
        detect_release_slot(ctx, slot_id);
        vTaskDelay(1);
    }
}

static void display_compose_task(void *arg)
{
    app_system_context_t *ctx = (app_system_context_t *)arg;
    overlay_state_t overlay = {0};

    ESP_LOGI(TAG, "Display compose task started on core %d", xPortGetCoreID());

    while (1) {
        cache_msync_aligned(ctx->camera_buffer, ctx->camera_buffer_size,
                            ESP_CACHE_MSYNC_FLAG_DIR_M2C);
        present_camera_frame(ctx);
        overlay_snapshot(ctx, &overlay);

        if (overlay.hand_count > 0) {
            draw_overlay_state(ctx, &overlay);
        } else {
            cache_msync_aligned(ctx->frame_buffer, ctx->frame_buffer_size,
                                ESP_CACHE_MSYNC_FLAG_DIR_C2M);
        }

        vTaskDelay(pdMS_TO_TICKS(DISPLAY_INTERVAL_MS));
    }
}

static esp_err_t init_detect_slots(app_system_context_t *ctx)
{
    ctx->detect_slots = heap_caps_calloc(AI_PIPELINE_SLOT_COUNT,
                                         sizeof(detect_packet_t),
                                         MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!ctx->detect_slots) {
        ESP_LOGE(TAG, "Failed to allocate detect slot table");
        return ESP_ERR_NO_MEM;
    }

    for (int i = 0; i < AI_PIPELINE_SLOT_COUNT; i++) {
        ctx->detect_slot_states[i] = DETECT_SLOT_FREE;
        ctx->detect_slots[i].frame_rgb565 = heap_caps_malloc(ctx->camera_buffer_size,
                                                             MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
        if (!ctx->detect_slots[i].frame_rgb565) {
            ESP_LOGE(TAG, "Failed to allocate frame snapshot buffer for slot %d", i);
            return ESP_ERR_NO_MEM;
        }
    }

    ctx->latest_ready_slot = -1;
    return ESP_OK;
}

esp_err_t app_ai_pipeline_init(app_system_context_t *ctx)
{
    if (!ctx) {
        return ESP_ERR_INVALID_ARG;
    }

    if (init_detect_slots(ctx) != ESP_OK) {
        return ESP_FAIL;
    }

    ctx->detect_slot_queue = xQueueCreate(1, sizeof(uint8_t));
    ctx->detect_slot_mutex = xSemaphoreCreateMutex();
    ctx->overlay_mutex = xSemaphoreCreateMutex();
    if (!ctx->detect_slot_queue || !ctx->detect_slot_mutex || !ctx->overlay_mutex) {
        ESP_LOGE(TAG, "Failed to create AI pipeline sync primitives");
        return ESP_FAIL;
    }

    memset(&ctx->overlay_state, 0, sizeof(ctx->overlay_state));
    app_output_reset();

    if (xTaskCreatePinnedToCore(ai_detect_task, "ai_detect",
                                AI_DETECT_TASK_STACK, ctx,
                                AI_DETECT_TASK_PRIORITY, NULL, 0) != pdPASS) {
        ESP_LOGE(TAG, "Failed to create detect task");
        return ESP_FAIL;
    }

    if (xTaskCreatePinnedToCore(ai_post_task, "ai_post",
                                AI_POST_TASK_STACK, ctx,
                                AI_POST_TASK_PRIORITY, NULL, 1) != pdPASS) {
        ESP_LOGE(TAG, "Failed to create post task");
        return ESP_FAIL;
    }

    if (xTaskCreatePinnedToCore(display_compose_task, "display_compose",
                                AI_DISPLAY_TASK_STACK, ctx,
                                AI_DISPLAY_TASK_PRIORITY, NULL, 1) != pdPASS) {
        ESP_LOGE(TAG, "Failed to create display compose task");
        return ESP_FAIL;
    }

    ESP_LOGI(TAG, "AI pipeline initialized with detect/post/display split");
    return ESP_OK;
}

