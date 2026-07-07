#include "app_hand_detect.h"
#include "esp_log.h"
#include "hand_detect.hpp"
#include "dl_image_define.hpp"

static const char *TAG = "hand_detect";
static HandDetect *s_detect = nullptr;
static constexpr float HAND_DETECT_SCORE_THR = 0.30f;
static constexpr float HAND_DETECT_NMS_THR = 0.40f;
static constexpr int HAND_DETECT_MIN_SIDE_PX = 96;

esp_err_t app_hand_detect_init(void)
{
    ESP_LOGI(TAG, "Initializing hand detection model...");
    s_detect = new HandDetect(HandDetect::ESPDET_PICO_224_224_HAND, false);
    if (!s_detect) {
        ESP_LOGE(TAG, "Failed to create HandDetect");
        return ESP_FAIL;
    }
    s_detect->set_score_thr(HAND_DETECT_SCORE_THR, 0);
    s_detect->set_nms_thr(HAND_DETECT_NMS_THR, 0);
    ESP_LOGI(TAG, "Hand detect thresholds: score=%.2f nms=%.2f",
             HAND_DETECT_SCORE_THR, HAND_DETECT_NMS_THR);
    ESP_LOGI(TAG, "Hand detection model loaded");
    return ESP_OK;
}

int app_hand_detect_run(uint16_t *frame, int w, int h,
                        ai_result_t *result)
{
    if (!s_detect || !frame || !result) {
        return 0;
    }

    dl::image::img_t img = {
        .data = frame,
        .width = (uint16_t)w,
        .height = (uint16_t)h,
        .pix_type = dl::image::DL_IMAGE_PIX_TYPE_RGB565LE,
    };

    std::list<dl::detect::result_t> &res = s_detect->run(img);

    int count = 0;
    for (auto it = res.begin(); it != res.end() && count < AI_RESULT_MAX_BOXES; ++it) {
        int bw = it->box[2] - it->box[0];
        int bh = it->box[3] - it->box[1];
        int short_side = bw < bh ? bw : bh;

        // The model still occasionally returns low-score or wrist-sized boxes;
        // filter them again here before they reach tracking/classification.
        if (it->score < HAND_DETECT_SCORE_THR || short_side < HAND_DETECT_MIN_SIDE_PX) {
            continue;
        }

        result->boxes[count].x = it->box[0];
        result->boxes[count].y = it->box[1];
        result->boxes[count].w = bw;
        result->boxes[count].h = bh;
        result->boxes[count].score = it->score;
        count++;
    }
    result->count = count;
    return count;
}

void draw_bbox_rgb565(uint16_t *fb, int fb_w, int fb_h,
                                 int x, int y, int bw, int bh, uint16_t color)
{
    // Clamp to frame bounds
    int x0 = (x < 0) ? 0 : x;
    int y0 = (y < 0) ? 0 : y;
    int x1 = (x + bw > fb_w) ? fb_w : x + bw;
    int y1 = (y + bh > fb_h) ? fb_h : y + bh;
    int thickness = 2;

    // Top edge
    for (int i = x0; i < x1; i++) {
        for (int t = 0; t < thickness && y0 + t < fb_h; t++) {
            fb[(y0 + t) * fb_w + i] = color;
        }
    }
    // Bottom edge
    for (int i = x0; i < x1; i++) {
        for (int t = 0; t < thickness && y1 - 1 - t >= 0; t++) {
            fb[(y1 - 1 - t) * fb_w + i] = color;
        }
    }
    // Left edge
    for (int j = y0; j < y1; j++) {
        for (int t = 0; t < thickness && x0 + t < fb_w; t++) {
            fb[j * fb_w + (x0 + t)] = color;
        }
    }
    // Right edge
    for (int j = y0; j < y1; j++) {
        for (int t = 0; t < thickness && x1 - 1 - t >= 0; t++) {
            fb[j * fb_w + (x1 - 1 - t)] = color;
        }
    }
}

