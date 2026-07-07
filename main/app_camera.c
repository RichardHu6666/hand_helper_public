#include "app_camera.h"
#include "app_common.h"
#include <string.h>
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_cam_ctlr_csi.h"
#include "esp_cam_ctlr.h"
#include "example_sensor_init.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

static const char *TAG = "app_camera";
static int s_auto_log_counter = 0;
static const char *s_last_auto_action = NULL;

#define CAMERA_INIT_RETRY_COUNT      3
#define CAMERA_INIT_RETRY_DELAY_MS  120

#define AUTO_TUNE_INTERVAL_FRAMES  1
#define AUTO_SAMPLE_STEP_X         16
#define AUTO_SAMPLE_STEP_Y         16
#define AUTO_SAMPLE_MARGIN_X_PCT   18
#define AUTO_SAMPLE_MARGIN_Y_PCT   16
#define AUTO_TARGET_LUMA_NORMAL    148
#define AUTO_TARGET_LUMA_BRIGHT    148
#define AUTO_DEADBAND_NORMAL       8
#define AUTO_DEADBAND_BRIGHT       10
#define AUTO_BRIGHT_LUMA_THRESH    210
#define AUTO_BRIGHT_RATIO_THRESH   45
#define AUTO_BRIGHT_HOLD_MIN       146
#define AUTO_BRIGHT_HOLD_MAX       170
#define AUTO_INTEGRAL_THRESHOLD    10
#define AUTO_FAST_TRACK_TUNES      8
#define AUTO_FAST_TRACK_ERROR      28
#define AUTO_EXPOSURE_STEP_SMALL   8
#define AUTO_EXPOSURE_STEP_MEDIUM  12
#define AUTO_EXPOSURE_STEP_LARGE   18
#define AUTO_EXPOSURE_STEP_XL      24
#define AUTO_EXPOSURE_HEADROOM     6
#define AUTO_LOG_INTERVAL_TUNES    4

#define AUTO_ACCUM_MIN             (-48)
#define AUTO_ACCUM_MAX             48

typedef struct {
    uint32_t sample_count;
    uint32_t avg_luma;
    uint32_t bright_ratio_pct;
} frame_stats_t;

static int clamp_i32(int value, int min_value, int max_value)
{
    if (value < min_value) {
        return min_value;
    }
    if (value > max_value) {
        return max_value;
    }
    return value;
}

static uint32_t clamp_u32(uint32_t value, uint32_t min_value, uint32_t max_value)
{
    if (value < min_value) {
        return min_value;
    }
    if (value > max_value) {
        return max_value;
    }
    return value;
}

static uint8_t rgb565_r8(uint16_t pixel)
{
    return (uint8_t)((((pixel >> 11) & 0x1F) * 255) / 31);
}

static uint8_t rgb565_g8(uint16_t pixel)
{
    return (uint8_t)((((pixel >> 5) & 0x3F) * 255) / 63);
}

static uint8_t rgb565_b8(uint16_t pixel)
{
    return (uint8_t)(((pixel & 0x1F) * 255) / 31);
}

static void collect_frame_stats(const uint16_t *frame, int width, int height, frame_stats_t *stats)
{
    uint64_t sum_luma = 0;
    uint32_t sample_count = 0;
    uint32_t bright_count = 0;
    int x_margin = 0;
    int y_margin = 0;
    int x_start = 0;
    int x_end = 0;
    int y_start = 0;
    int y_end = 0;

    memset(stats, 0, sizeof(*stats));
    if (!frame || width <= 0 || height <= 0) {
        return;
    }

    x_margin = (width * AUTO_SAMPLE_MARGIN_X_PCT) / 100;
    y_margin = (height * AUTO_SAMPLE_MARGIN_Y_PCT) / 100;
    x_start = clamp_i32(x_margin, 0, width - 1);
    x_end = clamp_i32(width - x_margin, x_start + 1, width);
    y_start = clamp_i32(y_margin, 0, height - 1);
    y_end = clamp_i32(height - y_margin, y_start + 1, height);

    for (int y = y_start; y < y_end; y += AUTO_SAMPLE_STEP_Y) {
        const uint16_t *row = frame + (y * width);
        for (int x = x_start; x < x_end; x += AUTO_SAMPLE_STEP_X) {
            uint16_t pixel = row[x];
            uint32_t r = rgb565_r8(pixel);
            uint32_t g = rgb565_g8(pixel);
            uint32_t b = rgb565_b8(pixel);
            uint32_t luma = (77U * r + 150U * g + 29U * b) >> 8;

            sum_luma += luma;
            if (luma >= AUTO_BRIGHT_LUMA_THRESH) {
                bright_count++;
            }
            sample_count++;
        }
    }

    if (sample_count == 0) {
        return;
    }

    stats->sample_count = sample_count;
    stats->avg_luma = (uint32_t)(sum_luma / sample_count);
    stats->bright_ratio_pct = (bright_count * 100U) / sample_count;
}

static int abs_i32(int value)
{
    return value < 0 ? -value : value;
}

static void init_auto_state(app_system_context_t *ctx)
{
    esp_cam_sensor_param_desc_t exp_desc = {
        .id = ESP_CAM_SENSOR_EXPOSURE_VAL,
    };
    esp_cam_sensor_param_desc_t gain_desc = {
        .id = ESP_CAM_SENSOR_GAIN,
    };
    uint32_t exposure_val = 0;
    uint32_t gain_index = 0;

    if (!ctx || !ctx->cam_sensor || ctx->camera_auto.initialized) {
        return;
    }

    ctx->camera_auto.exposure_val = 0;
    ctx->camera_auto.exposure_min_val = 8;
    ctx->camera_auto.exposure_max_val = 512;
    ctx->camera_auto.gain_index = 0;
    ctx->camera_auto.gain_max_index = 0;
    ctx->camera_auto.tune_counter = 0;
    ctx->camera_auto.luma_error_accum = 0;
    ctx->camera_auto.last_error_sign = 0;

    if (esp_cam_sensor_query_para_desc(ctx->cam_sensor, &exp_desc) == ESP_OK) {
        ctx->camera_auto.exposure_min_val = (uint32_t)exp_desc.number.minimum;
        ctx->camera_auto.exposure_max_val = (uint32_t)exp_desc.number.maximum;
        ctx->camera_auto.exposure_val = (uint32_t)exp_desc.default_value;
    }

    if (esp_cam_sensor_query_para_desc(ctx->cam_sensor, &gain_desc) == ESP_OK) {
        ctx->camera_auto.gain_index = (uint32_t)gain_desc.default_value;
        if (gain_desc.enumeration.count > 0) {
            ctx->camera_auto.gain_max_index = gain_desc.enumeration.count - 1;
        }
    }

    if (esp_cam_sensor_get_para_value(ctx->cam_sensor,
                                      ESP_CAM_SENSOR_EXPOSURE_VAL,
                                      &exposure_val,
                                      sizeof(exposure_val)) == ESP_OK) {
        ctx->camera_auto.exposure_val = exposure_val;
    }

    if (esp_cam_sensor_get_para_value(ctx->cam_sensor,
                                      ESP_CAM_SENSOR_GAIN,
                                      &gain_index,
                                      sizeof(gain_index)) == ESP_OK) {
        ctx->camera_auto.gain_index = gain_index;
    }

    ctx->camera_auto.exposure_val = clamp_u32(ctx->camera_auto.exposure_val,
                                              ctx->camera_auto.exposure_min_val,
                                              ctx->camera_auto.exposure_max_val);
    ctx->camera_auto.gain_index = clamp_u32(ctx->camera_auto.gain_index,
                                            0,
                                            ctx->camera_auto.gain_max_index);
    ctx->camera_auto.initialized = true;

    ESP_LOGI(TAG,
             "Auto tune initialized: exp=%u (%u..%u) gain=%u/%u",
             (unsigned)ctx->camera_auto.exposure_val,
             (unsigned)ctx->camera_auto.exposure_min_val,
             (unsigned)ctx->camera_auto.exposure_max_val,
             (unsigned)ctx->camera_auto.gain_index,
             (unsigned)ctx->camera_auto.gain_max_index);
}

static void apply_sensor_exp_gain(app_system_context_t *ctx)
{
    esp_cam_sensor_gh_exp_gain_t exp_gain = {
        .exposure_us = 0,
        .exposure_val = ctx->camera_auto.exposure_val,
        .gain_index = ctx->camera_auto.gain_index,
    };

    if (!ctx || !ctx->cam_sensor) {
        return;
    }

    if (esp_cam_sensor_set_para_value(ctx->cam_sensor,
                                      ESP_CAM_SENSOR_GROUP_EXP_GAIN,
                                      &exp_gain,
                                      sizeof(exp_gain)) != ESP_OK) {
        ESP_LOGW(TAG, "Failed to apply sensor auto tune");
    }
}

static int exposure_step_for_error(int error, bool fast_track)
{
    int abs_error = abs_i32(error);

    if (abs_error >= 56) {
        return AUTO_EXPOSURE_STEP_XL;
    }
    if (abs_error >= 40) {
        return AUTO_EXPOSURE_STEP_LARGE;
    }
    if (abs_error >= 24) {
        return AUTO_EXPOSURE_STEP_MEDIUM;
    }
    if (fast_track) {
        return AUTO_EXPOSURE_STEP_MEDIUM;
    }
    return AUTO_EXPOSURE_STEP_SMALL;
}

static const char *tune_exposure_gain(app_system_context_t *ctx, const frame_stats_t *stats)
{
    bool bright_bg = stats->bright_ratio_pct >= AUTO_BRIGHT_RATIO_THRESH;
    bool fast_track = false;
    int target_luma = bright_bg ? AUTO_TARGET_LUMA_BRIGHT : AUTO_TARGET_LUMA_NORMAL;
    int deadband = bright_bg ? AUTO_DEADBAND_BRIGHT : AUTO_DEADBAND_NORMAL;
    int error = target_luma - (int)stats->avg_luma;
    int error_sign = 0;
    int accum_delta = 0;
    int step = 0;

    if (bright_bg &&
        stats->avg_luma >= AUTO_BRIGHT_HOLD_MIN &&
        stats->avg_luma <= AUTO_BRIGHT_HOLD_MAX) {
        ctx->camera_auto.luma_error_accum /= 2;
        ctx->camera_auto.last_error_sign = 0;
        return "hold_bright_bg";
    }

    if (error > deadband) {
        error_sign = 1;
    } else if (error < -deadband) {
        error_sign = -1;
    } else {
        ctx->camera_auto.luma_error_accum /= 2;
        ctx->camera_auto.last_error_sign = 0;
        return "hold_deadband";
    }

    fast_track = (ctx->camera_auto.tune_counter <= AUTO_FAST_TRACK_TUNES) ||
                 (abs_i32(error) >= AUTO_FAST_TRACK_ERROR);
    accum_delta = abs_i32(error);
    if (accum_delta > 16) {
        accum_delta = 16;
    }

    if (fast_track) {
        ctx->camera_auto.luma_error_accum = error_sign * AUTO_INTEGRAL_THRESHOLD;
    } else if (ctx->camera_auto.last_error_sign != error_sign) {
        ctx->camera_auto.luma_error_accum = error_sign * accum_delta;
    } else {
        ctx->camera_auto.luma_error_accum = clamp_i32(ctx->camera_auto.luma_error_accum + (error_sign * accum_delta),
                                                      AUTO_ACCUM_MIN,
                                                      AUTO_ACCUM_MAX);
    }
    ctx->camera_auto.last_error_sign = (int8_t)error_sign;

    if (!fast_track && abs_i32(ctx->camera_auto.luma_error_accum) < AUTO_INTEGRAL_THRESHOLD) {
        return "hold_wait";
    }

    step = exposure_step_for_error(error, fast_track);
    if (bright_bg && error_sign < 0 && step > AUTO_EXPOSURE_STEP_MEDIUM) {
        step = AUTO_EXPOSURE_STEP_MEDIUM;
    }

    if (error_sign > 0) {
        if (ctx->camera_auto.exposure_val + AUTO_EXPOSURE_HEADROOM < ctx->camera_auto.exposure_max_val) {
            ctx->camera_auto.exposure_val = clamp_u32(ctx->camera_auto.exposure_val + (uint32_t)step,
                                                      ctx->camera_auto.exposure_min_val,
                                                      ctx->camera_auto.exposure_max_val);
            ctx->camera_auto.luma_error_accum = 0;
            return "exp_up";
        }
        if (ctx->camera_auto.gain_index < ctx->camera_auto.gain_max_index) {
            ctx->camera_auto.gain_index++;
            ctx->camera_auto.luma_error_accum = 0;
            return "gain_up";
        }
        return "hold_limit";
    }

    if (ctx->camera_auto.gain_index > 0) {
        ctx->camera_auto.gain_index--;
        ctx->camera_auto.luma_error_accum = 0;
        return "gain_down";
    }
    if (ctx->camera_auto.exposure_val > ctx->camera_auto.exposure_min_val) {
        uint32_t next_exp = ctx->camera_auto.exposure_val > (uint32_t)step
                            ? (ctx->camera_auto.exposure_val - (uint32_t)step)
                            : ctx->camera_auto.exposure_min_val;
        ctx->camera_auto.exposure_val = clamp_u32(next_exp,
                                                  ctx->camera_auto.exposure_min_val,
                                                  ctx->camera_auto.exposure_max_val);
        ctx->camera_auto.luma_error_accum = 0;
        return "exp_down";
    }

    return "hold_limit";
}

static bool s_camera_get_new_vb(esp_cam_ctlr_handle_t handle, esp_cam_ctlr_trans_t *trans, void *user_data)
{
    app_system_context_t *ctx = (app_system_context_t *)user_data;
    (void)handle;

    if (!ctx || !ctx->camera_buffer) {
        return false;
    }

    trans->buffer = ctx->camera_buffer;
    trans->buflen = ctx->camera_buffer_size;
    return true;
}

static bool s_camera_get_finished_trans(esp_cam_ctlr_handle_t handle, esp_cam_ctlr_trans_t *trans, void *user_data)
{
    app_system_context_t *ctx = (app_system_context_t *)user_data;
    BaseType_t high_task_wakeup = pdFALSE;
    (void)handle;
    (void)trans;

    if (ctx && ctx->frame_ready_sem) {
        xSemaphoreGiveFromISR(ctx->frame_ready_sem, &high_task_wakeup);
    }
    if (high_task_wakeup == pdTRUE) {
        portYIELD_FROM_ISR();
    }

    return true;
}

esp_err_t app_camera_init(app_system_context_t *ctx)
{
    // Sensor init (creates I2C bus + SCCB + detects SC2336)
    example_sensor_handle_t sensor_handle = {0};
    example_sensor_config_t cam_sensor_config = {
        .i2c_port_num = I2C_NUM_0,
        .i2c_sda_io_num = APP_CAM_I2C_SDA,
        .i2c_scl_io_num = APP_CAM_I2C_SCL,
        .port = ESP_CAM_SENSOR_MIPI_CSI,
        .format_name = APP_CAM_FORMAT,
    };
    bool sensor_ready = false;

    for (int attempt = 1; attempt <= CAMERA_INIT_RETRY_COUNT; attempt++) {
        memset(&sensor_handle, 0, sizeof(sensor_handle));
        ESP_LOGI(TAG, "Camera sensor init attempt %d/%d", attempt, CAMERA_INIT_RETRY_COUNT);
        example_sensor_init(&cam_sensor_config, &sensor_handle);
        if (sensor_handle.i2c_bus_handle && sensor_handle.sensor_dev) {
            sensor_ready = true;
            break;
        }
        if (attempt < CAMERA_INIT_RETRY_COUNT) {
            ESP_LOGW(TAG, "Camera sensor detect failed on attempt %d, retrying...", attempt);
            vTaskDelay(pdMS_TO_TICKS(CAMERA_INIT_RETRY_DELAY_MS));
        }
    }

    // Check if sensor was detected (sensor_init is void, may early-return on failure)
    if (!sensor_ready || sensor_handle.i2c_bus_handle == NULL || sensor_handle.sensor_dev == NULL) {
        ESP_LOGE(TAG, "Camera sensor detection failed after %d attempts", CAMERA_INIT_RETRY_COUNT);
        return ESP_FAIL;
    }

    // Save I2C bus handle (for ES8311 reuse)
    ctx->i2c_bus = sensor_handle.i2c_bus_handle;
    ctx->cam_sensor = sensor_handle.sensor_dev;
    init_auto_state(ctx);

    ctx->camera_buffer_size = ctx->frame_buffer_size;
    ctx->camera_buffer = heap_caps_malloc(ctx->camera_buffer_size, MALLOC_CAP_SPIRAM | MALLOC_CAP_DMA);
    if (!ctx->camera_buffer) {
        ESP_LOGE(TAG, "Failed to allocate camera buffer (%u bytes)",
                 (unsigned)ctx->camera_buffer_size);
        return ESP_ERR_NO_MEM;
    }
    memset(ctx->camera_buffer, 0, ctx->camera_buffer_size);

    if (!ctx->frame_ready_sem) {
        ctx->frame_ready_sem = xSemaphoreCreateBinary();
    }
    if (!ctx->frame_ready_sem) {
        ESP_LOGE(TAG, "Failed to create frame ready semaphore");
        return ESP_FAIL;
    }

    // CSI controller (RAW8 passthrough)
    esp_cam_ctlr_csi_config_t csi_config = {
        .ctlr_id = 0,
        .h_res = APP_LCD_H_RES,
        .v_res = APP_LCD_V_RES,
        .lane_bit_rate_mbps = APP_CAM_LANE_BITRATE,
        .input_data_color_type = CAM_CTLR_COLOR_RAW8,
        .output_data_color_type = CAM_CTLR_COLOR_RAW8,  // Must passthrough!
        .data_lane_num = 2,
        .byte_swap_en = false,
        .queue_items = 1,
    };
    ESP_ERROR_CHECK(esp_cam_new_csi_ctlr(&csi_config, &ctx->cam_ctlr));

    esp_cam_ctlr_evt_cbs_t cbs = {
        .on_get_new_trans = s_camera_get_new_vb,
        .on_trans_finished = s_camera_get_finished_trans,
    };
    ESP_ERROR_CHECK(esp_cam_ctlr_register_event_callbacks(ctx->cam_ctlr, &cbs, ctx));
    ESP_ERROR_CHECK(esp_cam_ctlr_enable(ctx->cam_ctlr));

    ESP_LOGI(TAG, "Camera initialized: SC2336 RAW8 %dx%d", APP_LCD_H_RES, APP_LCD_V_RES);
    return ESP_OK;
}

void app_camera_auto_adjust(app_system_context_t *ctx, const uint16_t *frame, int width, int height)
{
    frame_stats_t stats = {0};
    const char *action = "hold";

    if (!ctx || !frame || !ctx->cam_sensor) {
        return;
    }

    if (!ctx->camera_auto.initialized) {
        init_auto_state(ctx);
    }

    ctx->camera_auto.tune_counter++;
    if ((ctx->camera_auto.tune_counter % AUTO_TUNE_INTERVAL_FRAMES) != 0) {
        return;
    }

    collect_frame_stats(frame, width, height, &stats);
    if (stats.sample_count == 0) {
        return;
    }

    action = tune_exposure_gain(ctx, &stats);
    apply_sensor_exp_gain(ctx);
    s_auto_log_counter++;
    if (action != s_last_auto_action ||
        (s_auto_log_counter % AUTO_LOG_INTERVAL_TUNES) == 0) {
        ESP_LOGI(TAG,
                 "auto: luma=%u bright=%u%% exp=%u gain=%u accum=%d action=%s",
                 (unsigned)stats.avg_luma,
                 (unsigned)stats.bright_ratio_pct,
                 (unsigned)ctx->camera_auto.exposure_val,
                 (unsigned)ctx->camera_auto.gain_index,
                 (int)ctx->camera_auto.luma_error_accum,
                 action);
        s_last_auto_action = action;
    }
}

