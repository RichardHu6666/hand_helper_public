#include <assert.h>

#include "app_display.h"

#include "app_common.h"
#include "esp_heap_caps.h"
#include "esp_lcd_mipi_dsi.h"
#include "esp_lcd_panel_ops.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "example_dsi_init.h"
#include "example_dsi_init_config.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "lvgl.h"
#include "lvgl_demo_ui.h"
#include "sys/lock.h"
#include "sys/param.h"
#include "unistd.h"

static const char *TAG = "app_display";

#define APP_LVGL_DRAW_BUF_LINES    20
#define APP_LVGL_TICK_PERIOD_MS    2
#define APP_LVGL_TASK_STACK_SIZE   (8 * 1024)
#define APP_LVGL_TASK_PRIORITY     2
#define APP_LVGL_TASK_MAX_DELAY_MS 500
#define APP_LVGL_TASK_MIN_DELAY_MS (1000 / CONFIG_FREERTOS_HZ)

static _lock_t lvgl_api_lock;

esp_err_t app_display_init(app_system_context_t *ctx)
{
    example_dsi_resource_alloc(NULL, &ctx->dsi_bus, &ctx->dbi_io, &ctx->dpi_panel,
                               &ctx->frame_buffer, NULL);

    ctx->frame_buffer_size = APP_LCD_H_RES * APP_LCD_V_RES * APP_BYTES_PER_PIXEL;

    ESP_LOGI(TAG, "Display initialized: %dx%d RGB565", APP_LCD_H_RES, APP_LCD_V_RES);
    return ESP_OK;
}

static bool app_lvgl_flush_ready_cb(esp_lcd_panel_handle_t panel,
                                    esp_lcd_dpi_panel_event_data_t *edata,
                                    void *user_ctx)
{
    lv_display_t *disp = (lv_display_t *)user_ctx;
    lv_display_flush_ready(disp);
    return false;
}

static void app_lvgl_flush_cb(lv_display_t *disp, const lv_area_t *area, uint8_t *px_map)
{
    esp_lcd_panel_handle_t panel_handle = lv_display_get_user_data(disp);
    esp_lcd_panel_draw_bitmap(panel_handle, area->x1, area->y1,
                              area->x2 + 1, area->y2 + 1, px_map);
}

static void app_lvgl_tick_cb(void *arg)
{
    lv_tick_inc(APP_LVGL_TICK_PERIOD_MS);
}

static void app_lvgl_task(void *arg)
{
    uint32_t time_till_next_ms = 0;

    ESP_LOGI(TAG, "LVGL task started on core %d", xPortGetCoreID());
    while (1) {
        _lock_acquire(&lvgl_api_lock);
        time_till_next_ms = lv_timer_handler();
        _lock_release(&lvgl_api_lock);

        time_till_next_ms = MAX(time_till_next_ms, APP_LVGL_TASK_MIN_DELAY_MS);
        time_till_next_ms = MIN(time_till_next_ms, APP_LVGL_TASK_MAX_DELAY_MS);
        usleep(1000 * time_till_next_ms);
    }
}

esp_err_t app_display_lvgl_init(app_system_context_t *ctx)
{
    ESP_LOGI(TAG, "Initializing LVGL library");

    lv_init();

    lv_display_t *display = lv_display_create(APP_LCD_H_RES, APP_LCD_V_RES);
    assert(display);
    lv_display_set_user_data(display, ctx->dpi_panel);
    lv_display_set_color_format(display, LV_COLOR_FORMAT_RGB565);

    size_t draw_buffer_sz = APP_LCD_H_RES * APP_LVGL_DRAW_BUF_LINES * sizeof(lv_color_t);
    ESP_LOGI(TAG, "Allocating LVGL draw buffers: %d bytes each", draw_buffer_sz);

    void *buf1 = heap_caps_malloc(draw_buffer_sz, MALLOC_CAP_SPIRAM);
    void *buf2 = heap_caps_malloc(draw_buffer_sz, MALLOC_CAP_SPIRAM);
    assert(buf1 && buf2);
    lv_display_set_buffers(display, buf1, buf2, draw_buffer_sz, LV_DISPLAY_RENDER_MODE_PARTIAL);
    lv_display_set_flush_cb(display, app_lvgl_flush_cb);

    esp_lcd_dpi_panel_event_callbacks_t cbs = {
        .on_color_trans_done = app_lvgl_flush_ready_cb,
    };
    ESP_ERROR_CHECK(esp_lcd_dpi_panel_register_event_callbacks(ctx->dpi_panel, &cbs, display));

    const esp_timer_create_args_t lvgl_tick_timer_args = {
        .callback = &app_lvgl_tick_cb,
        .name = "lvgl_tick",
    };
    esp_timer_handle_t lvgl_tick_timer = NULL;
    ESP_ERROR_CHECK(esp_timer_create(&lvgl_tick_timer_args, &lvgl_tick_timer));
    ESP_ERROR_CHECK(esp_timer_start_periodic(lvgl_tick_timer, APP_LVGL_TICK_PERIOD_MS * 1000));

    example_lvgl_demo_ui(display);

    ESP_LOGI(TAG, "Creating LVGL task on Core 1");
    xTaskCreatePinnedToCore(app_lvgl_task, "lvgl_task", APP_LVGL_TASK_STACK_SIZE,
                            ctx, APP_LVGL_TASK_PRIORITY, NULL, 1);

    ESP_LOGI(TAG, "LVGL initialization complete (gesture panel active)");
    return ESP_OK;
}

