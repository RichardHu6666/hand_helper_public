#pragma once

#include "app_common.h"

esp_err_t app_camera_init(app_system_context_t *ctx);
void app_camera_auto_adjust(app_system_context_t *ctx, const uint16_t *frame, int width, int height);

