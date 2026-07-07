#pragma once

#include "app_common.h"
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    bool valid;
    int detect_x;
    int detect_y;
    int detect_w;
    int detect_h;
    int crop_x;
    int crop_y;
    int crop_w;
    int crop_h;
    char profile_name[16];
    char side_source_name[24];
    char aspect_bucket[20];
    float aspect_ratio;
    float slender_blend;
    float crop_short_ratio;
    float crop_long_ratio;
    float crop_area_ratio;
    float center_y_bias;
    bool clamped;
} gesture_debug_info_t;

esp_err_t app_hand_gesture_init(void);
int app_hand_gesture_recognize(uint16_t *frame,
                               int w,
                               int h,
                               const ai_result_t *detect_result,
                               gesture_result_t *gestures,
                               int max_gestures,
                               gesture_debug_info_t *debug_infos,
                               int max_debug_infos);
const char *app_gesture_name(gesture_id_t gesture_id);

#ifdef __cplusplus
}
#endif

