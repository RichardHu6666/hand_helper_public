#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "driver/i2c_master.h"
#include "driver/isp.h"
#include "esp_cam_ctlr.h"
#include "esp_cam_sensor.h"
#include "esp_err.h"
#include "esp_lcd_mipi_dsi.h"
#include "esp_lcd_panel_ops.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"

#define APP_LCD_H_RES          1024
#define APP_LCD_V_RES          600
#define APP_LCD_RST_GPIO       27
#define APP_LCD_BK_GPIO        26

#define APP_CAM_I2C_SDA        7
#define APP_CAM_I2C_SCL        8
#define APP_CAM_LANE_BITRATE   200
#define APP_CAM_FORMAT         "MIPI_2lane_24Minput_RAW8_1024x600_30fps"

#define APP_RGB565_BPP         16
#define APP_BYTES_PER_PIXEL    2

#define AI_RESULT_MAX_BOXES    5
#define AI_PIPELINE_SLOT_COUNT 2

typedef struct {
    int count;
    struct {
        int x;
        int y;
        int w;
        int h;
        float score;
    } boxes[AI_RESULT_MAX_BOXES];
} ai_result_t;

typedef enum {
    DETECT_SLOT_FREE = 0,
    DETECT_SLOT_FILLING,
    DETECT_SLOT_READY,
    DETECT_SLOT_BUSY,
} detect_slot_state_t;

typedef enum {
    GESTURE_ID_NO_GESTURE = 0,
    GESTURE_ID_ONE,
    GESTURE_ID_TWO,
    GESTURE_ID_THREE,
    GESTURE_ID_FOUR,
    GESTURE_ID_FIVE,
    GESTURE_ID_LIKE,
    GESTURE_ID_OK,
    GESTURE_ID_CALL,
    GESTURE_ID_DISLIKE,
    GESTURE_ID_NO_HAND,
} gesture_id_t;

typedef struct {
    gesture_id_t gesture_id;
    float score;
    bool stable;
    int stable_count;
} gesture_result_t;

typedef enum {
    APP_SIGNER_SIDE_NONE = 0,
    APP_SIGNER_SIDE_LEFT,
    APP_SIGNER_SIDE_RIGHT,
} app_signer_side_t;

typedef enum {
    APP_BIMANUAL_RELATION_SINGLE_HAND = 0,
    APP_BIMANUAL_RELATION_DUAL_HAND,
    APP_BIMANUAL_RELATION_SAME_SHAPE,
    APP_BIMANUAL_RELATION_DIFFERENT_SHAPE,
} app_bimanual_relation_t;

typedef enum {
    APP_MOVEMENT_HOLD = 0,
    APP_MOVEMENT_LEFT_RIGHT,
    APP_MOVEMENT_UP_DOWN,
    APP_MOVEMENT_TOWARD_AWAY,
    APP_MOVEMENT_OPEN_CLOSE,
    APP_MOVEMENT_REPEAT,
} app_movement_t;

typedef enum {
    APP_RELATIVE_MOTION_UNKNOWN = 0,
    APP_RELATIVE_MOTION_HOLD,
    APP_RELATIVE_MOTION_LEFT_RIGHT,
    APP_RELATIVE_MOTION_LEFT_TO_RIGHT,
    APP_RELATIVE_MOTION_RIGHT_TO_LEFT,
    APP_RELATIVE_MOTION_UP_DOWN,
    APP_RELATIVE_MOTION_UP_TO_DOWN,
    APP_RELATIVE_MOTION_DOWN_TO_UP,
    APP_RELATIVE_MOTION_TOWARD_AWAY,
    APP_RELATIVE_MOTION_TOWARD,
    APP_RELATIVE_MOTION_AWAY,
    APP_RELATIVE_MOTION_OPEN_CLOSE,
    APP_RELATIVE_MOTION_REPEAT,
} app_relative_motion_t;

typedef enum {
    APP_LOCATION_UNKNOWN = 0,
    APP_LOCATION_SIGNER_LEFT_UPPER,
    APP_LOCATION_SIGNER_LEFT_MIDDLE,
    APP_LOCATION_SIGNER_LEFT_LOWER,
    APP_LOCATION_SIGNER_CENTER_UPPER,
    APP_LOCATION_SIGNER_CENTER_MIDDLE,
    APP_LOCATION_SIGNER_CENTER_LOWER,
    APP_LOCATION_SIGNER_RIGHT_UPPER,
    APP_LOCATION_SIGNER_RIGHT_MIDDLE,
    APP_LOCATION_SIGNER_RIGHT_LOWER,
} app_location_t;

typedef struct {
    int raw_hand_count;
    int hand_count;
    gesture_id_t dominant_shape;
    gesture_id_t nondominant_shape;
    app_bimanual_relation_t bimanual_relation;
    app_movement_t movement;
    app_relative_motion_t relative_motion;
    app_location_t location;
    app_signer_side_t dominant_side;
} app_primitive_state_t;

typedef struct {
    uint32_t frame_seq;
    int raw_hand_count;
    int hand_count;
    app_signer_side_t dominant_side;
    app_location_t location;
    app_movement_t movement;
    app_relative_motion_t relative_motion;
    app_bimanual_relation_t bimanual_relation;
    gesture_id_t dominant_shape;
    gesture_id_t nondominant_shape;
} app_cloud_frame_t;

typedef struct {
    uint32_t frame_seq;
    ai_result_t detect_result;
    int hand_count;
    uint16_t *frame_rgb565;
} detect_packet_t;

typedef struct {
    uint32_t frame_seq;
    ai_result_t detect_result;
    int hand_count;
    ai_result_t classify_result;
    int classify_hand_count;
    gesture_result_t gestures[AI_RESULT_MAX_BOXES];
    int primary_index;
    int stable_primary_index;
} overlay_state_t;

typedef struct {
    uint32_t exposure_val;
    uint32_t exposure_min_val;
    uint32_t exposure_max_val;
    uint32_t gain_index;
    uint32_t gain_max_index;
    uint32_t tune_counter;
    int32_t luma_error_accum;
    int8_t last_error_sign;
    bool initialized;
} camera_auto_state_t;

typedef struct {
    esp_lcd_dsi_bus_handle_t dsi_bus;
    esp_lcd_panel_io_handle_t dbi_io;
    esp_lcd_panel_handle_t dpi_panel;
    void *frame_buffer;
    size_t frame_buffer_size;
    void *camera_buffer;
    size_t camera_buffer_size;
    i2c_master_bus_handle_t i2c_bus;
    esp_cam_sensor_device_t *cam_sensor;
    esp_cam_ctlr_handle_t cam_ctlr;
    isp_proc_handle_t isp_proc;
    QueueHandle_t detect_slot_queue;
    SemaphoreHandle_t frame_ready_sem;
    SemaphoreHandle_t detect_slot_mutex;
    SemaphoreHandle_t overlay_mutex;
    detect_packet_t *detect_slots;
    overlay_state_t overlay_state;
    detect_slot_state_t detect_slot_states[AI_PIPELINE_SLOT_COUNT];
    int latest_ready_slot;
    camera_auto_state_t camera_auto;
} app_system_context_t;

#define APP_AUDIO_I2S_MCLK     13
#define APP_AUDIO_I2S_BCLK     12
#define APP_AUDIO_I2S_WS       10
#define APP_AUDIO_I2S_DOUT     9
#define APP_AUDIO_I2S_DIN      11
#define APP_AUDIO_PA_GPIO      53
#define APP_AUDIO_SAMPLE_RATE  16000

