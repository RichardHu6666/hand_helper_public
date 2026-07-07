#include "app_wifi.h"

#include <string.h>

#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "nvs_flash.h"
#include "sdkconfig.h"

#include "app_output.h"

static const char *TAG = "app_wifi";

static EventGroupHandle_t s_wifi_event_group;
static bool s_wifi_connected;
static bool s_wifi_initialized;

#define WIFI_CONNECTED_BIT BIT0
#define WIFI_FAIL_BIT      BIT1

static void set_cloud_status_only(const char *status, int http_code, bool stale)
{
    app_output_state_t state = {0};

    app_output_snapshot(&state);
    app_output_set_cloud_state(status,
                               state.cloud_word,
                               state.cloud_sentence,
                               http_code,
                               stale,
                               state.cloud_fail_count);
}

static void app_wifi_event_handler(void *arg,
                                   esp_event_base_t event_base,
                                   int32_t event_id,
                                   void *event_data)
{
    (void)arg;
    (void)event_data;

    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        ESP_LOGI(TAG, "wifi sta start");
        esp_wifi_connect();
        set_cloud_status_only("wifi", 0, false);
    } else if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        s_wifi_connected = false;
        if (s_wifi_event_group) {
            xEventGroupSetBits(s_wifi_event_group, WIFI_FAIL_BIT);
        }
        ESP_LOGW(TAG, "wifi disconnected");
        set_cloud_status_only("wifi", 0, true);
        esp_wifi_connect();
    } else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        s_wifi_connected = true;
        if (s_wifi_event_group) {
            xEventGroupSetBits(s_wifi_event_group, WIFI_CONNECTED_BIT);
        }
        ESP_LOGI(TAG, "wifi connected");
        set_cloud_status_only("wifi", 200, false);
    }
}

esp_err_t app_wifi_init(void)
{
    esp_err_t err;
    wifi_config_t wifi_config = {0};
    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();

    if (!CONFIG_CLOUD_ENABLE) {
        ESP_LOGI(TAG, "cloud disabled, skip wifi init");
        app_output_set_cloud_state("off", "-", "-", 0, false, 0);
        return ESP_OK;
    }

    if (s_wifi_initialized) {
        return ESP_OK;
    }

    err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        err = nvs_flash_erase();
        if (err != ESP_OK) {
            ESP_LOGW(TAG, "nvs erase failed: %s", esp_err_to_name(err));
            set_cloud_status_only("wifi", 0, true);
            return err;
        }
        err = nvs_flash_init();
    }
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "nvs init failed: %s", esp_err_to_name(err));
        set_cloud_status_only("wifi", 0, true);
        return err;
    }

    err = esp_netif_init();
    if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) {
        ESP_LOGW(TAG, "esp_netif_init failed: %s", esp_err_to_name(err));
        set_cloud_status_only("wifi", 0, true);
        return err;
    }

    err = esp_event_loop_create_default();
    if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) {
        ESP_LOGW(TAG, "event loop create failed: %s", esp_err_to_name(err));
        set_cloud_status_only("wifi", 0, true);
        return err;
    }

    if (!esp_netif_create_default_wifi_sta()) {
        ESP_LOGW(TAG, "failed to create default wifi sta");
        set_cloud_status_only("wifi", 0, true);
        return ESP_FAIL;
    }

    if (!s_wifi_event_group) {
        s_wifi_event_group = xEventGroupCreate();
    }

    err = esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, &app_wifi_event_handler, NULL);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "register wifi handler failed: %s", esp_err_to_name(err));
        set_cloud_status_only("wifi", 0, true);
        return err;
    }
    err = esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, &app_wifi_event_handler, NULL);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "register ip handler failed: %s", esp_err_to_name(err));
        set_cloud_status_only("wifi", 0, true);
        return err;
    }

    err = esp_wifi_init(&cfg);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "esp_wifi_init failed: %s", esp_err_to_name(err));
        set_cloud_status_only("wifi", 0, true);
        return err;
    }

    memset(&wifi_config, 0, sizeof(wifi_config));
    strncpy((char *)wifi_config.sta.ssid, CONFIG_WIFI_SSID, sizeof(wifi_config.sta.ssid) - 1);
    strncpy((char *)wifi_config.sta.password, CONFIG_WIFI_PASSWORD, sizeof(wifi_config.sta.password) - 1);
    wifi_config.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;
    wifi_config.sta.pmf_cfg.capable = true;
    wifi_config.sta.pmf_cfg.required = false;

    err = esp_wifi_set_mode(WIFI_MODE_STA);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "esp_wifi_set_mode failed: %s", esp_err_to_name(err));
        set_cloud_status_only("wifi", 0, true);
        return err;
    }

    err = esp_wifi_set_config(WIFI_IF_STA, &wifi_config);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "esp_wifi_set_config failed: %s", esp_err_to_name(err));
        set_cloud_status_only("wifi", 0, true);
        return err;
    }

    err = esp_wifi_start();
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "esp_wifi_start failed: %s", esp_err_to_name(err));
        set_cloud_status_only("wifi", 0, true);
        return err;
    }

    s_wifi_initialized = true;
    set_cloud_status_only("wifi", 0, false);
    return ESP_OK;
}

bool app_wifi_is_connected(void)
{
    return s_wifi_connected;
}

