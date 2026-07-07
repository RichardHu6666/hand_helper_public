#include <stdio.h>
#include <string.h>

#include "esp_cache.h"
#include "esp_ldo_regulator.h"
#include "esp_log.h"
#include "sdkconfig.h"

#include "app_ai_pipeline.h"
#include "app_camera.h"
#include "app_common.h"
#include "app_cloud.h"
#include "app_display.h"
#include "app_isp.h"
#include "app_output.h"
#include "app_wifi.h"
#include "example_dsi_init.h"

#ifndef CONFIG_CLOUD_DEBUG_LOG
#define CONFIG_CLOUD_DEBUG_LOG 0
#endif

static const char *TAG = "main";

static void configure_log_profile(void)
{
#if !CONFIG_CLOUD_DEBUG_LOG
    esp_log_level_set("*", ESP_LOG_WARN);
    esp_log_level_set(TAG, ESP_LOG_INFO);
    esp_log_level_set("app_wifi", ESP_LOG_INFO);
    esp_log_level_set("app_cloud", ESP_LOG_INFO);
#endif
}

void app_main(void)
{
    configure_log_profile();
    ESP_LOGI(TAG, "Hand Gesture Demo Starting...");

    app_system_context_t ctx = {0};

    esp_ldo_channel_handle_t ldo_mipi_phy = NULL;
    esp_ldo_channel_config_t ldo_mipi_phy_config = {
        .chan_id = 3,
        .voltage_mv = 2500,
    };
    ESP_ERROR_CHECK(esp_ldo_acquire_channel(&ldo_mipi_phy_config, &ldo_mipi_phy));
    ESP_LOGI(TAG, "MIPI PHY LDO powered on");

    ESP_ERROR_CHECK(app_display_init(&ctx));
    ESP_ERROR_CHECK(app_camera_init(&ctx));
    ESP_ERROR_CHECK(app_isp_init(&ctx));

    example_dpi_panel_reset(ctx.dpi_panel);

    memset(ctx.frame_buffer, 0xFF, ctx.frame_buffer_size);
    esp_cache_msync((void *)ctx.frame_buffer, ctx.frame_buffer_size,
                    ESP_CACHE_MSYNC_FLAG_DIR_C2M);

    ESP_ERROR_CHECK(esp_cam_ctlr_start(ctx.cam_ctlr));
    example_dpi_panel_init(ctx.dpi_panel);

    ESP_ERROR_CHECK(app_display_lvgl_init(&ctx));
    ESP_ERROR_CHECK(app_output_init());
    if (app_wifi_init() != ESP_OK) {
        ESP_LOGW(TAG, "wifi init failed, local primitive pipeline continues");
    }
    if (app_cloud_start() != ESP_OK) {
        ESP_LOGW(TAG, "cloud task start failed");
    }
    ESP_ERROR_CHECK(app_ai_pipeline_init(&ctx));

    ESP_LOGI(TAG, "System ready - LVGL UI and AI pipeline running");
    while (1) {
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}

