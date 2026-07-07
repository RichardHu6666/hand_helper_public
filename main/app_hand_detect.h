#pragma once

#include "app_common.h"

#ifdef __cplusplus
extern "C" {
#endif

esp_err_t app_hand_detect_init(void);
int app_hand_detect_run(uint16_t *frame, int w, int h,
                        ai_result_t *result);
void draw_bbox_rgb565(uint16_t *fb, int fb_w, int fb_h,
                      int x, int y, int bw, int bh, uint16_t color);

#ifdef __cplusplus
}
#endif

