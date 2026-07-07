#pragma once

#include <stdbool.h>

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

esp_err_t app_wifi_init(void);
bool app_wifi_is_connected(void);

#ifdef __cplusplus
}
#endif

