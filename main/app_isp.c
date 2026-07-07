#include "app_isp.h"
#include "app_common.h"

#include <math.h>

#include "driver/isp.h"
#include "driver/isp_ccm.h"
#include "driver/isp_demosaic.h"
#include "driver/isp_gamma.h"
#include "driver/isp_wbg.h"
#include "esp_log.h"

static const char *TAG = "app_isp";

static uint32_t s_gamma_correction_curve(uint32_t x)
{
    return pow((double)x / 256, 0.7) * 256;
}

esp_err_t app_isp_init(app_system_context_t *ctx)
{
    esp_isp_processor_cfg_t isp_config = {
        .clk_hz = 80 * 1000 * 1000,
        .input_data_source = ISP_INPUT_DATA_SOURCE_CSI,
        .input_data_color_type = ISP_COLOR_RAW8,
        .output_data_color_type = ISP_COLOR_RGB565,
        .has_line_start_packet = false,
        .has_line_end_packet = false,
        .h_res = APP_LCD_H_RES,
        .v_res = APP_LCD_V_RES,
    };
    esp_isp_demosaic_config_t demosaic_config = {
        .grad_ratio = { .integer = 2, .decimal = 5 },
    };
    esp_isp_ccm_config_t ccm_config = {
        .matrix = {
            { 1.0, 0.0, 0.0 },
            { 0.0, 1.0, 0.0 },
            { 0.0, 0.0, 1.0 },
        },
        .saturation = false,
    };
    esp_isp_wbg_config_t wbg_config = {
        .flags.update_once_configured = 1,
    };
    isp_wbg_gain_t wbg_gain = {
        .gain_r = 256,
        .gain_g = 200,
        .gain_b = 280,
    };
    isp_gamma_curve_points_t pts = {0};

    ESP_ERROR_CHECK(esp_isp_new_processor(&isp_config, &ctx->isp_proc));

    ESP_ERROR_CHECK(esp_isp_demosaic_configure(ctx->isp_proc, &demosaic_config));
    ESP_ERROR_CHECK(esp_isp_demosaic_enable(ctx->isp_proc));

    ESP_ERROR_CHECK(esp_isp_ccm_configure(ctx->isp_proc, &ccm_config));
    ESP_ERROR_CHECK(esp_isp_ccm_enable(ctx->isp_proc));

    ESP_ERROR_CHECK(esp_isp_wbg_configure(ctx->isp_proc, &wbg_config));
    ESP_ERROR_CHECK(esp_isp_wbg_enable(ctx->isp_proc));
    ESP_ERROR_CHECK(esp_isp_wbg_set_wb_gain(ctx->isp_proc, wbg_gain));

    ESP_ERROR_CHECK(esp_isp_gamma_fill_curve_points(s_gamma_correction_curve, &pts));
    ESP_ERROR_CHECK(esp_isp_gamma_configure(ctx->isp_proc, COLOR_COMPONENT_R, &pts));
    ESP_ERROR_CHECK(esp_isp_gamma_configure(ctx->isp_proc, COLOR_COMPONENT_G, &pts));
    ESP_ERROR_CHECK(esp_isp_gamma_configure(ctx->isp_proc, COLOR_COMPONENT_B, &pts));
    ESP_ERROR_CHECK(esp_isp_gamma_enable(ctx->isp_proc));

    ESP_ERROR_CHECK(esp_isp_enable(ctx->isp_proc));

    ESP_LOGI(TAG, "ISP initialized: RAW8->RGB565, 80MHz, CCM corrected");
    return ESP_OK;
}

