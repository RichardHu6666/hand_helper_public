#pragma once

#include "esp_err.h"

#include "app_common.h"

#ifdef __cplusplus
extern "C" {
#endif

esp_err_t app_cloud_start(void);
void app_cloud_submit_frame(const app_cloud_frame_t *frame);

#ifdef __cplusplus
}
#endif

