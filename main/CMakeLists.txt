idf_component_register(SRCS "app_output.c"
                            "fonts/lv_font_sign_ui_14.c"
                            "app_wifi.c"
                            "app_cloud.c"
                            "lvgl_demo_ui.c"
                            "main.c"
                            "app_display.c"
                            "app_camera.c"
                            "app_isp.c"
                            "app_hand_detect.cpp"
                            "app_hand_gesture.cpp"
                            "app_ai_pipeline.c"
                       PRIV_REQUIRES esp_mm esp_driver_isp esp_driver_cam esp_driver_i2c esp_lcd spi_flash lvgl
                                     esp_event esp_netif nvs_flash esp_http_client esp-tls esp_wifi esp_wifi_remote
                       INCLUDE_DIRS "."
                       REQUIRES dsi_init sensor_init)

