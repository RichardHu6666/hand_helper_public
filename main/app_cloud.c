#include "app_cloud.h"

#include <ctype.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "esp_err.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "sdkconfig.h"
#if CONFIG_MBEDTLS_CERTIFICATE_BUNDLE
#include "esp_crt_bundle.h"
#endif
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"

#include "app_output.h"
#include "app_wifi.h"

#ifndef CONFIG_CLOUD_DEBUG_LOG
#define CONFIG_CLOUD_DEBUG_LOG 0
#endif
#ifndef CONFIG_CLOUD_UPLOAD_SAMPLE_MS
#define CONFIG_CLOUD_UPLOAD_SAMPLE_MS 250
#endif
#ifndef CONFIG_CLOUD_UPLOAD_IDLE_HEARTBEAT_MS
#define CONFIG_CLOUD_UPLOAD_IDLE_HEARTBEAT_MS 1000
#endif
#ifndef CONFIG_CLOUD_NORMALIZE_GRACE_MS
#define CONFIG_CLOUD_NORMALIZE_GRACE_MS 1500
#endif
#ifndef CONFIG_CLOUD_ACTIVE_MOVEMENT_GRACE_MS
#define CONFIG_CLOUD_ACTIVE_MOVEMENT_GRACE_MS 800
#endif
#ifndef CONFIG_CLOUD_FRAME_QUEUE_LEN
#define CONFIG_CLOUD_FRAME_QUEUE_LEN 24
#endif
#ifndef CONFIG_CLOUD_BATCH_ENABLE
#define CONFIG_CLOUD_BATCH_ENABLE 1
#endif
#ifndef CONFIG_CLOUD_BATCH_MAX_FRAMES
#define CONFIG_CLOUD_BATCH_MAX_FRAMES 4
#endif
#ifndef CONFIG_CLOUD_BATCH_MAX_WAIT_MS
#define CONFIG_CLOUD_BATCH_MAX_WAIT_MS 900
#endif
#ifndef CONFIG_CLOUD_BATCH_IDLE_MAX_FRAMES
#define CONFIG_CLOUD_BATCH_IDLE_MAX_FRAMES 2
#endif
#ifndef CONFIG_CLOUD_SHAPE_ACTIVE_HOLD_MS
#define CONFIG_CLOUD_SHAPE_ACTIVE_HOLD_MS 6000
#endif
#ifndef CONFIG_CLOUD_SHAPE_UNKNOWN_ON_ACTIVE_WITHOUT_CACHE
#define CONFIG_CLOUD_SHAPE_UNKNOWN_ON_ACTIVE_WITHOUT_CACHE 0
#endif
#ifndef CONFIG_CLOUD_REQUIRE_SHAPE_CACHE_FOR_ACTIVE
#define CONFIG_CLOUD_REQUIRE_SHAPE_CACHE_FOR_ACTIVE 0
#endif

static const char *TAG = "app_cloud";

#define CLOUD_RESPONSE_BUF_LEN 1024
#define CLOUD_REQUEST_BUF_LEN 3072
#define CLOUD_TASK_PRIORITY 1
#define CLOUD_MAX_BACKLOG_FRAMES 6
#define CLOUD_HTTP_PACING_MAX_MS 1000
#define CLOUD_BATCH_MAX_FRAMES_LIMIT 6
#define CLOUD_SKIP_ACTIVE_NO_SHAPE_LOG_MS 1000

typedef struct {
    char status[24];
    char word[32];
    char sentence[96];
    int http_code;
    bool stale;
    int fail_count;
} cloud_display_state_t;

typedef struct {
    char *response_buf;
} cloud_http_event_ctx_t;

static QueueHandle_t s_cloud_queue;
static TaskHandle_t s_cloud_task;
static char s_cloud_frame_url[192];
static char s_cloud_frames_url[192];
static bool s_cloud_batch_supported = CONFIG_CLOUD_BATCH_ENABLE;
static char s_last_logged_status[24];
static cloud_display_state_t s_cloud_display = {
    .status = "off",
    .word = "-",
    .sentence = "-",
    .http_code = 0,
    .stale = false,
    .fail_count = 0,
};
static int64_t s_last_timestamp_second = -1;
static int s_timestamp_seq = 0;
static gesture_id_t s_cloud_last_dominant_shape = GESTURE_ID_NO_HAND;
static int64_t s_cloud_shape_valid_until_us = 0;
static gesture_id_t s_cloud_stable_motion_shape = GESTURE_ID_NO_HAND;
static int64_t s_cloud_stable_motion_shape_valid_until_us = 0;
static int64_t s_cloud_shape_cache_last_refresh_us = 0;
static app_movement_t s_cloud_last_active_movement = APP_MOVEMENT_HOLD;
static int64_t s_cloud_movement_valid_until_us = 0;
static app_relative_motion_t s_cloud_last_relative_motion = APP_RELATIVE_MOTION_UNKNOWN;
static app_movement_t s_cloud_last_relative_motion_movement = APP_MOVEMENT_HOLD;
static int64_t s_cloud_relative_motion_valid_until_us = 0;
static app_location_t s_cloud_last_vertical_location = APP_LOCATION_UNKNOWN;
static int64_t s_cloud_location_valid_until_us = 0;
static bool s_cloud_was_active_movement = false;
static bool s_cloud_last_enqueued_valid = false;
static app_cloud_frame_t s_cloud_last_enqueued_frame = {0};
static int64_t s_cloud_last_enqueue_us = 0;
static int64_t s_cloud_last_http_ms = CLOUD_HTTP_PACING_MAX_MS;
static int64_t s_cloud_last_skip_no_shape_log_us = 0;
static int s_cloud_drop_old_counter = 0;

static const char *gesture_name(gesture_id_t gesture)
{
    switch (gesture) {
    case GESTURE_ID_ONE:
        return "one";
    case GESTURE_ID_TWO:
        return "two";
    case GESTURE_ID_THREE:
        return "three";
    case GESTURE_ID_FOUR:
        return "four";
    case GESTURE_ID_FIVE:
        return "five";
    case GESTURE_ID_LIKE:
        return "like";
    case GESTURE_ID_OK:
        return "ok";
    case GESTURE_ID_CALL:
        return "call";
    case GESTURE_ID_DISLIKE:
        return "dislike";
    case GESTURE_ID_NO_GESTURE:
        return "no_gesture";
    case GESTURE_ID_NO_HAND:
    default:
        return "no_hand";
    }
}

static const char *cloud_dominant_shape_wire_name(const app_cloud_frame_t *frame)
{
    if (!frame) {
        return "no_hand";
    }

    if (CONFIG_CLOUD_SHAPE_UNKNOWN_ON_ACTIVE_WITHOUT_CACHE &&
        frame->movement != APP_MOVEMENT_HOLD &&
        frame->dominant_shape == GESTURE_ID_NO_GESTURE) {
        return "unknown";
    }

    return gesture_name(frame->dominant_shape);
}

static const char *signer_side_name(app_signer_side_t side)
{
    switch (side) {
    case APP_SIGNER_SIDE_LEFT:
        return "signer_left";
    case APP_SIGNER_SIDE_RIGHT:
        return "signer_right";
    case APP_SIGNER_SIDE_NONE:
    default:
        return "none";
    }
}

static const char *movement_name(app_movement_t movement)
{
    switch (movement) {
    case APP_MOVEMENT_LEFT_RIGHT:
        return "left_right";
    case APP_MOVEMENT_UP_DOWN:
        return "up_down";
    case APP_MOVEMENT_TOWARD_AWAY:
        return "toward_away";
    case APP_MOVEMENT_OPEN_CLOSE:
        return "open_close";
    case APP_MOVEMENT_REPEAT:
        return "repeat";
    case APP_MOVEMENT_HOLD:
    default:
        return "hold";
    }
}

static const char *relative_motion_name(app_relative_motion_t relative_motion)
{
    switch (relative_motion) {
    case APP_RELATIVE_MOTION_HOLD:
        return "hold";
    case APP_RELATIVE_MOTION_LEFT_RIGHT:
        return "left_right";
    case APP_RELATIVE_MOTION_LEFT_TO_RIGHT:
        return "left_to_right";
    case APP_RELATIVE_MOTION_RIGHT_TO_LEFT:
        return "right_to_left";
    case APP_RELATIVE_MOTION_UP_DOWN:
        return "up_down";
    case APP_RELATIVE_MOTION_UP_TO_DOWN:
        return "up_to_down";
    case APP_RELATIVE_MOTION_DOWN_TO_UP:
        return "down_to_up";
    case APP_RELATIVE_MOTION_TOWARD_AWAY:
        return "toward_away";
    case APP_RELATIVE_MOTION_TOWARD:
        return "toward";
    case APP_RELATIVE_MOTION_AWAY:
        return "away";
    case APP_RELATIVE_MOTION_OPEN_CLOSE:
        return "open_close";
    case APP_RELATIVE_MOTION_REPEAT:
        return "repeat";
    case APP_RELATIVE_MOTION_UNKNOWN:
    default:
        return "unknown";
    }
}

static const char *location_name(app_location_t location)
{
    switch (location) {
    case APP_LOCATION_SIGNER_LEFT_UPPER:
        return "signer_left_upper";
    case APP_LOCATION_SIGNER_LEFT_MIDDLE:
        return "signer_left_middle";
    case APP_LOCATION_SIGNER_LEFT_LOWER:
        return "signer_left_lower";
    case APP_LOCATION_SIGNER_CENTER_UPPER:
        return "signer_center_upper";
    case APP_LOCATION_SIGNER_CENTER_MIDDLE:
        return "signer_center_middle";
    case APP_LOCATION_SIGNER_CENTER_LOWER:
        return "signer_center_lower";
    case APP_LOCATION_SIGNER_RIGHT_UPPER:
        return "signer_right_upper";
    case APP_LOCATION_SIGNER_RIGHT_MIDDLE:
        return "signer_right_middle";
    case APP_LOCATION_SIGNER_RIGHT_LOWER:
        return "signer_right_lower";
    case APP_LOCATION_UNKNOWN:
    default:
        return "unknown";
    }
}

static const char *bimanual_relation_name(app_bimanual_relation_t relation)
{
    switch (relation) {
    case APP_BIMANUAL_RELATION_SINGLE_HAND:
        return "single_hand";
    case APP_BIMANUAL_RELATION_DUAL_HAND:
        return "dual_hand";
    case APP_BIMANUAL_RELATION_SAME_SHAPE:
        return "same_shape";
    case APP_BIMANUAL_RELATION_DIFFERENT_SHAPE:
        return "different_shape";
    default:
        return "none";
    }
}

static bool cloud_shape_is_concrete(gesture_id_t gesture)
{
    return gesture == GESTURE_ID_ONE ||
           gesture == GESTURE_ID_TWO ||
           gesture == GESTURE_ID_THREE ||
           gesture == GESTURE_ID_FOUR ||
           gesture == GESTURE_ID_FIVE ||
           gesture == GESTURE_ID_LIKE ||
           gesture == GESTURE_ID_OK ||
           gesture == GESTURE_ID_CALL ||
           gesture == GESTURE_ID_DISLIKE;
}

static int64_t cloud_ms_to_us(int ms)
{
    return (int64_t)ms * 1000LL;
}

static bool cloud_movement_is_active(app_movement_t movement)
{
    return movement != APP_MOVEMENT_HOLD;
}

static void refresh_cloud_shape_cache(gesture_id_t shape, int64_t now_us)
{
    if (!cloud_shape_is_concrete(shape)) {
        return;
    }

    s_cloud_stable_motion_shape = shape;
    s_cloud_stable_motion_shape_valid_until_us =
        now_us + cloud_ms_to_us(CONFIG_CLOUD_SHAPE_ACTIVE_HOLD_MS);
    s_cloud_last_dominant_shape = shape;
    s_cloud_shape_valid_until_us =
        now_us + cloud_ms_to_us(CONFIG_CLOUD_NORMALIZE_GRACE_MS);
    s_cloud_shape_cache_last_refresh_us = now_us;
}

static bool cloud_stable_shape_cache_is_valid(int64_t now_us)
{
    return cloud_shape_is_concrete(s_cloud_stable_motion_shape) &&
           now_us <= s_cloud_stable_motion_shape_valid_until_us;
}

static bool cloud_relative_motion_is_directional_for_movement(app_relative_motion_t relative_motion,
                                                              app_movement_t movement)
{
    switch (movement) {
    case APP_MOVEMENT_LEFT_RIGHT:
        return relative_motion == APP_RELATIVE_MOTION_LEFT_TO_RIGHT ||
               relative_motion == APP_RELATIVE_MOTION_RIGHT_TO_LEFT ||
               relative_motion == APP_RELATIVE_MOTION_LEFT_RIGHT;
    case APP_MOVEMENT_UP_DOWN:
        return relative_motion == APP_RELATIVE_MOTION_UP_TO_DOWN ||
               relative_motion == APP_RELATIVE_MOTION_DOWN_TO_UP ||
               relative_motion == APP_RELATIVE_MOTION_UP_DOWN;
    case APP_MOVEMENT_TOWARD_AWAY:
        return relative_motion == APP_RELATIVE_MOTION_TOWARD ||
               relative_motion == APP_RELATIVE_MOTION_AWAY ||
               relative_motion == APP_RELATIVE_MOTION_TOWARD_AWAY;
    case APP_MOVEMENT_OPEN_CLOSE:
        return relative_motion == APP_RELATIVE_MOTION_OPEN_CLOSE;
    case APP_MOVEMENT_REPEAT:
        return relative_motion == APP_RELATIVE_MOTION_REPEAT;
    case APP_MOVEMENT_HOLD:
    default:
        return relative_motion == APP_RELATIVE_MOTION_HOLD;
    }
}

static app_relative_motion_t cloud_relative_motion_for_movement(app_movement_t movement)
{
    switch (movement) {
    case APP_MOVEMENT_LEFT_RIGHT:
        return APP_RELATIVE_MOTION_LEFT_RIGHT;
    case APP_MOVEMENT_UP_DOWN:
        return APP_RELATIVE_MOTION_UP_DOWN;
    case APP_MOVEMENT_TOWARD_AWAY:
        return APP_RELATIVE_MOTION_TOWARD_AWAY;
    case APP_MOVEMENT_OPEN_CLOSE:
        return APP_RELATIVE_MOTION_OPEN_CLOSE;
    case APP_MOVEMENT_REPEAT:
        return APP_RELATIVE_MOTION_REPEAT;
    case APP_MOVEMENT_HOLD:
    default:
        return APP_RELATIVE_MOTION_HOLD;
    }
}

static int cloud_location_vertical_band(app_location_t location)
{
    switch (location) {
    case APP_LOCATION_SIGNER_LEFT_UPPER:
    case APP_LOCATION_SIGNER_CENTER_UPPER:
    case APP_LOCATION_SIGNER_RIGHT_UPPER:
        return 0;
    case APP_LOCATION_SIGNER_LEFT_MIDDLE:
    case APP_LOCATION_SIGNER_CENTER_MIDDLE:
    case APP_LOCATION_SIGNER_RIGHT_MIDDLE:
        return 1;
    case APP_LOCATION_SIGNER_LEFT_LOWER:
    case APP_LOCATION_SIGNER_CENTER_LOWER:
    case APP_LOCATION_SIGNER_RIGHT_LOWER:
        return 2;
    default:
        return -1;
    }
}

static app_location_t cloud_center_location_for_vertical_band(int vertical_band)
{
    switch (vertical_band) {
    case 0:
        return APP_LOCATION_SIGNER_CENTER_UPPER;
    case 1:
        return APP_LOCATION_SIGNER_CENTER_MIDDLE;
    case 2:
        return APP_LOCATION_SIGNER_CENTER_LOWER;
    default:
        return APP_LOCATION_UNKNOWN;
    }
}

static app_movement_t normalize_cloud_movement(app_movement_t movement, int64_t now_us)
{
    if (movement == APP_MOVEMENT_LEFT_RIGHT) {
        s_cloud_last_active_movement = APP_MOVEMENT_LEFT_RIGHT;
        s_cloud_movement_valid_until_us =
            now_us + cloud_ms_to_us(CONFIG_CLOUD_ACTIVE_MOVEMENT_GRACE_MS);
        return APP_MOVEMENT_LEFT_RIGHT;
    }

    if (movement != APP_MOVEMENT_HOLD) {
        s_cloud_last_active_movement = movement;
        s_cloud_movement_valid_until_us =
            now_us + cloud_ms_to_us(CONFIG_CLOUD_ACTIVE_MOVEMENT_GRACE_MS);
        return movement;
    }

    if (s_cloud_last_active_movement != APP_MOVEMENT_HOLD &&
        now_us <= s_cloud_movement_valid_until_us) {
        return s_cloud_last_active_movement;
    }

    s_cloud_last_active_movement = APP_MOVEMENT_HOLD;
    s_cloud_movement_valid_until_us = 0;
    return APP_MOVEMENT_HOLD;
}

static gesture_id_t normalize_cloud_shape(gesture_id_t shape,
                                          bool active,
                                          int64_t now_us)
{
    if (cloud_shape_is_concrete(shape)) {
        if (active && cloud_stable_shape_cache_is_valid(now_us) &&
            shape != s_cloud_stable_motion_shape) {
            refresh_cloud_shape_cache(s_cloud_stable_motion_shape, now_us);
            return s_cloud_stable_motion_shape;
        }

        refresh_cloud_shape_cache(shape, now_us);
        return shape;
    }

    if (!active) {
        if (cloud_stable_shape_cache_is_valid(now_us)) {
            return s_cloud_stable_motion_shape;
        }

        return shape;
    }

    if (cloud_stable_shape_cache_is_valid(now_us)) {
        refresh_cloud_shape_cache(s_cloud_stable_motion_shape, now_us);
        return s_cloud_stable_motion_shape;
    }

    if (cloud_shape_is_concrete(s_cloud_last_dominant_shape) &&
        now_us <= s_cloud_shape_valid_until_us) {
        refresh_cloud_shape_cache(s_cloud_last_dominant_shape, now_us);
        return s_cloud_last_dominant_shape;
    }

    return GESTURE_ID_NO_GESTURE;
}

static app_location_t normalize_cloud_location(app_location_t location,
                                               app_movement_t movement,
                                               int64_t now_us)
{
    int vertical_band = cloud_location_vertical_band(location);
    bool active = cloud_movement_is_active(movement);

    if (active) {
        s_cloud_was_active_movement = true;
        return APP_LOCATION_UNKNOWN;
    }

    if (vertical_band >= 0 &&
        (!s_cloud_was_active_movement ||
         s_cloud_last_vertical_location == APP_LOCATION_UNKNOWN ||
         now_us > s_cloud_location_valid_until_us ||
         cloud_location_vertical_band(s_cloud_last_vertical_location) == vertical_band)) {
        s_cloud_last_vertical_location = cloud_center_location_for_vertical_band(vertical_band);
        s_cloud_location_valid_until_us =
            now_us + cloud_ms_to_us(CONFIG_CLOUD_NORMALIZE_GRACE_MS);
    }

    s_cloud_was_active_movement = false;

    if (movement == APP_MOVEMENT_LEFT_RIGHT && vertical_band >= 0) {
        return cloud_center_location_for_vertical_band(vertical_band);
    }

    return location;
}

static app_relative_motion_t normalize_cloud_relative_motion(app_relative_motion_t relative_motion,
                                                             app_movement_t movement,
                                                             int64_t now_us)
{
    if (!cloud_movement_is_active(movement)) {
        s_cloud_last_relative_motion = APP_RELATIVE_MOTION_UNKNOWN;
        s_cloud_last_relative_motion_movement = APP_MOVEMENT_HOLD;
        s_cloud_relative_motion_valid_until_us = 0;
        return APP_RELATIVE_MOTION_HOLD;
    }

    if (cloud_relative_motion_is_directional_for_movement(relative_motion, movement)) {
        s_cloud_last_relative_motion = relative_motion;
        s_cloud_last_relative_motion_movement = movement;
        s_cloud_relative_motion_valid_until_us =
            now_us + cloud_ms_to_us(CONFIG_CLOUD_ACTIVE_MOVEMENT_GRACE_MS);
        return relative_motion;
    }

    if (s_cloud_last_relative_motion_movement == movement &&
        now_us <= s_cloud_relative_motion_valid_until_us &&
        cloud_relative_motion_is_directional_for_movement(s_cloud_last_relative_motion, movement)) {
        return s_cloud_last_relative_motion;
    }

    return cloud_relative_motion_for_movement(movement);
}

static app_cloud_frame_t normalize_cloud_frame_for_match(const app_cloud_frame_t *frame)
{
    app_cloud_frame_t normalized = *frame;
    int64_t now_us = esp_timer_get_time();
    bool active = false;

    normalized.movement = normalize_cloud_movement(normalized.movement, now_us);
    active = cloud_movement_is_active(normalized.movement);
    normalized.relative_motion = normalize_cloud_relative_motion(normalized.relative_motion,
                                                                 normalized.movement,
                                                                 now_us);
    normalized.dominant_shape = normalize_cloud_shape(normalized.dominant_shape,
                                                      active,
                                                      now_us);
    normalized.location = normalize_cloud_location(normalized.location,
                                                   normalized.movement,
                                                   now_us);

    return normalized;
}

static void set_cloud_display_state(const char *status,
                                    const char *word,
                                    const char *sentence,
                                    int http_code,
                                    bool stale,
                                    int fail_count)
{
    if (status) {
        strncpy(s_cloud_display.status, status, sizeof(s_cloud_display.status) - 1);
        s_cloud_display.status[sizeof(s_cloud_display.status) - 1] = '\0';
    }
    if (word) {
        strncpy(s_cloud_display.word, word, sizeof(s_cloud_display.word) - 1);
        s_cloud_display.word[sizeof(s_cloud_display.word) - 1] = '\0';
    }
    if (sentence) {
        strncpy(s_cloud_display.sentence, sentence, sizeof(s_cloud_display.sentence) - 1);
        s_cloud_display.sentence[sizeof(s_cloud_display.sentence) - 1] = '\0';
    }
    s_cloud_display.http_code = http_code;
    s_cloud_display.stale = stale;
    s_cloud_display.fail_count = fail_count;

    app_output_set_cloud_state(s_cloud_display.status,
                               s_cloud_display.word,
                               s_cloud_display.sentence,
                               s_cloud_display.http_code,
                               s_cloud_display.stale,
                               s_cloud_display.fail_count);
}

static bool has_cloud_text(const char *text)
{
    return text && text[0] != '\0' && strcmp(text, "-") != 0;
}

static void build_timestamp(char *out_buf, size_t out_buf_len)
{
    int64_t total_seconds = esp_timer_get_time() / 1000000LL;
    int64_t hhmmss_seconds = total_seconds % (24 * 60 * 60);
    int hour = (int)(hhmmss_seconds / 3600);
    int minute = (int)((hhmmss_seconds % 3600) / 60);
    int second = (int)(hhmmss_seconds % 60);

    if (!out_buf || out_buf_len == 0) {
        return;
    }

    if (s_last_timestamp_second != total_seconds) {
        s_last_timestamp_second = total_seconds;
        s_timestamp_seq = 1;
    } else {
        s_timestamp_seq++;
        if (s_timestamp_seq > 999) {
            s_timestamp_seq = 999;
        }
    }

    snprintf(out_buf,
             out_buf_len,
             "%s-%02d%02d%02d-%03d",
             CONFIG_CLOUD_TIMESTAMP_DATE_YYMMDD,
             hour,
             minute,
             second,
             s_timestamp_seq);
}

static int cloud_batch_limit(void)
{
    int limit = CONFIG_CLOUD_BATCH_MAX_FRAMES;

    if (limit < 1) {
        return 1;
    }
    if (limit > CLOUD_BATCH_MAX_FRAMES_LIMIT) {
        return CLOUD_BATCH_MAX_FRAMES_LIMIT;
    }
    return limit;
}

static int collect_cloud_batch(app_cloud_frame_t *batch,
                               int max_frames,
                               bool active_batch)
{
    TickType_t deadline_ticks =
        xTaskGetTickCount() + pdMS_TO_TICKS(CONFIG_CLOUD_BATCH_MAX_WAIT_MS);
    int count = 1;

    if (!batch || max_frames <= 1 || !s_cloud_queue) {
        return count;
    }

    if (!active_batch && CONFIG_CLOUD_BATCH_IDLE_MAX_FRAMES < max_frames) {
        max_frames = CONFIG_CLOUD_BATCH_IDLE_MAX_FRAMES;
        if (max_frames < 1) {
            max_frames = 1;
        }
    }

    while (count < max_frames) {
        TickType_t now = xTaskGetTickCount();
        TickType_t wait_ticks = 0;

        if (now >= deadline_ticks) {
            break;
        }
        wait_ticks = deadline_ticks - now;
        if (xQueueReceive(s_cloud_queue, &batch[count], wait_ticks) != pdTRUE) {
            break;
        }
        count++;
    }

    return count;
}

static int append_cloud_frame_json(char *buf,
                                   size_t buf_len,
                                   int offset,
                                   const app_cloud_frame_t *frame,
                                   bool include_relative_motion)
{
    char timestamp[32];
    int written = 0;

    if (!buf || !frame || offset < 0 || (size_t)offset >= buf_len) {
        return -1;
    }

    build_timestamp(timestamp, sizeof(timestamp));
    written = snprintf(buf + offset,
                       buf_len - (size_t)offset,
                       "{\"client_seq\":%" PRIu32 ","
                       "\"timestamp\":\"%s\","
                       "\"primitive\":{"
                       "\"hand_count\":%d,"
                       "\"dominant_side\":\"%s\","
                       "\"location\":\"%s\","
                       "\"movement\":\"%s\","
                       "%s%s%s"
                       "\"bimanual_relation\":\"%s\","
                       "\"dominant_shape\":\"%s\","
                       "\"nondominant_shape\":\"%s\"}}",
                       frame->frame_seq,
                       timestamp,
                       frame->hand_count,
                       signer_side_name(frame->dominant_side),
                       location_name(frame->location),
                       movement_name(frame->movement),
                       include_relative_motion ? "\"relative_motion\":\"" : "",
                       include_relative_motion ? relative_motion_name(frame->relative_motion) : "",
                       include_relative_motion ? "\"," : "",
                       bimanual_relation_name(frame->bimanual_relation),
                       cloud_dominant_shape_wire_name(frame),
                       gesture_name(frame->nondominant_shape));

    if (written < 0 || (size_t)written >= buf_len - (size_t)offset) {
        return -1;
    }
    return offset + written;
}

static bool build_single_request(char *buf,
                                 size_t buf_len,
                                 const app_cloud_frame_t *frame)
{
    int offset = 0;
    char timestamp[32];

    if (!buf || !frame || buf_len == 0) {
        return false;
    }

    build_timestamp(timestamp, sizeof(timestamp));
    offset = snprintf(buf,
                      buf_len,
                      "{\"session_id\":\"%s\",\"timestamp\":\"%s\",\"primitive\":{"
                      "\"hand_count\":%d,"
                      "\"dominant_side\":\"%s\","
                      "\"location\":\"%s\","
                      "\"movement\":\"%s\","
                      "\"relative_motion\":\"%s\","
                      "\"bimanual_relation\":\"%s\","
                      "\"dominant_shape\":\"%s\","
                      "\"nondominant_shape\":\"%s\"},"
                      "\"debug\":false}",
                      CONFIG_CLOUD_SESSION_ID,
                      timestamp,
                      frame->hand_count,
                      signer_side_name(frame->dominant_side),
                      location_name(frame->location),
                      movement_name(frame->movement),
                      relative_motion_name(frame->relative_motion),
                      bimanual_relation_name(frame->bimanual_relation),
                      cloud_dominant_shape_wire_name(frame),
                      gesture_name(frame->nondominant_shape));

    return offset > 0 && (size_t)offset < buf_len;
}

static bool build_batch_request(char *buf,
                                size_t buf_len,
                                const app_cloud_frame_t *batch,
                                int batch_count)
{
    int offset = 0;

    if (!buf || !batch || batch_count <= 0 || buf_len == 0) {
        return false;
    }

    offset = snprintf(buf,
                      buf_len,
                      "{\"session_id\":\"%s\",\"debug\":false,\"frames\":[",
                      CONFIG_CLOUD_SESSION_ID);
    if (offset <= 0 || (size_t)offset >= buf_len) {
        return false;
    }

    for (int i = 0; i < batch_count; i++) {
        if (i > 0) {
            if ((size_t)offset + 1 >= buf_len) {
                return false;
            }
            buf[offset++] = ',';
            buf[offset] = '\0';
        }
        offset = append_cloud_frame_json(buf, buf_len, offset, &batch[i], true);
        if (offset < 0) {
            return false;
        }
    }

    if ((size_t)offset + 3 >= buf_len) {
        return false;
    }
    snprintf(buf + offset, buf_len - (size_t)offset, "]}");
    return true;
}

static void log_cloud_frame_post(const app_cloud_frame_t *frame,
                                 UBaseType_t queue_depth,
                                 int64_t http_ms,
                                 esp_err_t err,
                                 int status_code)
{
    if (!frame) {
        return;
    }

    ESP_LOGI(TAG,
             "cloud frame: seq=%" PRIu32 " hand=%d move=%s rel=%s loc=%s shape=%s q=%u http_ms=%" PRId64 " err=%s http=%d",
             frame->frame_seq,
             frame->hand_count,
             movement_name(frame->movement),
             relative_motion_name(frame->relative_motion),
             location_name(frame->location),
             cloud_dominant_shape_wire_name(frame),
             (unsigned)queue_depth,
             http_ms,
             esp_err_to_name(err),
             status_code);

}

static void log_cloud_batch_post(const app_cloud_frame_t *batch,
                                 int batch_count,
                                 UBaseType_t queue_depth,
                                 int64_t http_ms,
                                 esp_err_t err,
                                 int status_code)
{
    if (!batch || batch_count <= 0) {
        return;
    }

    ESP_LOGI(TAG,
             "cloud batch: n=%d seq=%" PRIu32 "..%" PRIu32 " move=%s..%s rel=%s..%s loc=%s..%s shape=%s..%s q=%u http_ms=%" PRId64 " err=%s http=%d",
             batch_count,
             batch[0].frame_seq,
             batch[batch_count - 1].frame_seq,
             movement_name(batch[0].movement),
             movement_name(batch[batch_count - 1].movement),
             relative_motion_name(batch[0].relative_motion),
             relative_motion_name(batch[batch_count - 1].relative_motion),
             location_name(batch[0].location),
             location_name(batch[batch_count - 1].location),
             cloud_dominant_shape_wire_name(&batch[0]),
             cloud_dominant_shape_wire_name(&batch[batch_count - 1]),
             (unsigned)queue_depth,
             http_ms,
             esp_err_to_name(err),
             status_code);
}

static bool cloud_frame_key_equal(const app_cloud_frame_t *a,
                                  const app_cloud_frame_t *b)
{
    if (!a || !b) {
        return false;
    }

    return a->hand_count == b->hand_count &&
           a->movement == b->movement &&
           a->relative_motion == b->relative_motion &&
           a->location == b->location &&
           a->dominant_shape == b->dominant_shape &&
           a->bimanual_relation == b->bimanual_relation;
}

static bool should_enqueue_cloud_frame(const app_cloud_frame_t *frame, int64_t now_us)
{
    int interval_ms = 0;
    int64_t elapsed_us = 0;
    bool changed = false;
    bool active = false;
    bool active_start = false;

    if (!frame) {
        return false;
    }

    if (!s_cloud_last_enqueued_valid) {
        return true;
    }

    elapsed_us = now_us - s_cloud_last_enqueue_us;
    changed = !cloud_frame_key_equal(frame, &s_cloud_last_enqueued_frame);
    active = cloud_movement_is_active(frame->movement);
    active_start = active && !cloud_movement_is_active(s_cloud_last_enqueued_frame.movement);

    if (active_start) {
        return true;
    }

    interval_ms = active ? CONFIG_CLOUD_UPLOAD_SAMPLE_MS :
                  CONFIG_CLOUD_UPLOAD_IDLE_HEARTBEAT_MS;
    if (active && s_cloud_last_http_ms > interval_ms) {
        int64_t paced_ms = s_cloud_last_http_ms;
        if (paced_ms > CLOUD_HTTP_PACING_MAX_MS) {
            paced_ms = CLOUD_HTTP_PACING_MAX_MS;
        }
        interval_ms = (int)paced_ms;
    }

    if (changed && !active) {
        return elapsed_us >= cloud_ms_to_us(CONFIG_CLOUD_UPLOAD_SAMPLE_MS);
    }

    return elapsed_us >= cloud_ms_to_us(interval_ms);
}

static void remember_enqueued_cloud_frame(const app_cloud_frame_t *frame, int64_t now_us)
{
    if (!frame) {
        return;
    }

    s_cloud_last_enqueued_frame = *frame;
    s_cloud_last_enqueued_valid = true;
    s_cloud_last_enqueue_us = now_us;
}

static bool should_skip_active_without_shape_cache(const app_cloud_frame_t *frame, int64_t now_us)
{
    if (!CONFIG_CLOUD_REQUIRE_SHAPE_CACHE_FOR_ACTIVE ||
        !frame ||
        !cloud_movement_is_active(frame->movement) ||
        cloud_shape_is_concrete(frame->dominant_shape)) {
        return false;
    }

    if (now_us - s_cloud_last_skip_no_shape_log_us >=
        cloud_ms_to_us(CLOUD_SKIP_ACTIVE_NO_SHAPE_LOG_MS)) {
        bool cache_valid = cloud_stable_shape_cache_is_valid(now_us);
        int64_t cache_age_ms = s_cloud_shape_cache_last_refresh_us > 0 ?
            ((now_us - s_cloud_shape_cache_last_refresh_us) / 1000LL) : -1;

        ESP_LOGW(TAG,
                 "cloud skip active no_shape_cache seq=%" PRIu32 " move=%s rel=%s raw_shape=%s last_shape=%s cache_valid=%d cache_age_ms=%" PRId64,
                 frame->frame_seq,
                 movement_name(frame->movement),
                 relative_motion_name(frame->relative_motion),
                 gesture_name(frame->dominant_shape),
                 gesture_name(s_cloud_stable_motion_shape),
                 cache_valid ? 1 : 0,
                 cache_age_ms);
        s_cloud_last_skip_no_shape_log_us = now_us;
    }

    return true;
}

static bool enqueue_cloud_frame_fifo(const app_cloud_frame_t *frame)
{
    app_cloud_frame_t dropped = {0};
    UBaseType_t max_backlog = CLOUD_MAX_BACKLOG_FRAMES;

    if (!frame || !s_cloud_queue) {
        return false;
    }

    if (CONFIG_CLOUD_FRAME_QUEUE_LEN < CLOUD_MAX_BACKLOG_FRAMES) {
        max_backlog = CONFIG_CLOUD_FRAME_QUEUE_LEN;
    }

    while (uxQueueMessagesWaiting(s_cloud_queue) >= max_backlog) {
        if (xQueueReceive(s_cloud_queue, &dropped, 0) != pdTRUE) {
            break;
        }
        s_cloud_drop_old_counter++;
        ESP_LOGW(TAG,
                 "cloud queue drop_old=%d dropped_seq=%" PRIu32,
                 s_cloud_drop_old_counter,
                 dropped.frame_seq);
    }

    if (xQueueSendToBack(s_cloud_queue, frame, 0) == pdTRUE) {
        return true;
    }

    if (xQueueReceive(s_cloud_queue, &dropped, 0) == pdTRUE) {
        s_cloud_drop_old_counter++;
        ESP_LOGW(TAG,
                 "cloud queue drop_old=%d dropped_seq=%" PRIu32,
                 s_cloud_drop_old_counter,
                 dropped.frame_seq);
    }

    return xQueueSendToBack(s_cloud_queue, frame, 0) == pdTRUE;
}

static esp_err_t http_event_handler(esp_http_client_event_t *evt)
{
    cloud_http_event_ctx_t *event_ctx = (cloud_http_event_ctx_t *)evt->user_data;
    char *buf = event_ctx ? event_ctx->response_buf : NULL;

    if (!buf) {
        return ESP_OK;
    }

    if (evt->event_id == HTTP_EVENT_ON_DATA && evt->data && evt->data_len > 0) {
        size_t used = strlen(buf);
        size_t remain = CLOUD_RESPONSE_BUF_LEN - used - 1;
        size_t copy_len = evt->data_len < (int)remain ? (size_t)evt->data_len : remain;
        if (copy_len > 0) {
            memcpy(buf + used, evt->data, copy_len);
            buf[used + copy_len] = '\0';
        }
    }

    return ESP_OK;
}

static const char *skip_ws(const char *p)
{
    while (p && *p && isspace((unsigned char)*p)) {
        p++;
    }
    return p;
}

static bool extract_json_string(const char *json,
                                const char *key,
                                char *out,
                                size_t out_size)
{
    char pattern[64];
    const char *p = NULL;
    const char *value_start = NULL;
    const char *value_end = NULL;
    size_t len = 0;

    if (!json || !key || !out || out_size == 0) {
        return false;
    }

    snprintf(pattern, sizeof(pattern), "\"%s\"", key);
    p = strstr(json, pattern);
    if (!p) {
        return false;
    }

    p = strchr(p + strlen(pattern), ':');
    if (!p) {
        return false;
    }
    p = skip_ws(p + 1);
    if (!p || *p != '"') {
        return false;
    }

    value_start = p + 1;
    value_end = value_start;
    while (*value_end && *value_end != '"') {
        if (*value_end == '\\' && *(value_end + 1) != '\0') {
            value_end++;
        }
        value_end++;
    }
    if (*value_end != '"') {
        return false;
    }

    len = (size_t)(value_end - value_start);
    if (len >= out_size) {
        len = out_size - 1;
    }
    memcpy(out, value_start, len);
    out[len] = '\0';
    return true;
}

static bool extract_json_string_after_anchor(const char *json,
                                             const char *anchor_key,
                                             const char *key,
                                             char *out,
                                             size_t out_size)
{
    char anchor_pattern[64];
    const char *anchor = NULL;
    const char *p = NULL;
    const char *object_start = NULL;
    const char *object_end = NULL;
    bool in_string = false;
    bool escaped = false;
    int depth = 0;
    char object_buf[CLOUD_RESPONSE_BUF_LEN];
    size_t object_len = 0;

    if (!json || !anchor_key || !key || !out || out_size == 0) {
        return false;
    }

    snprintf(anchor_pattern, sizeof(anchor_pattern), "\"%s\"", anchor_key);
    anchor = strstr(json, anchor_pattern);
    if (!anchor) {
        return false;
    }

    p = strchr(anchor + strlen(anchor_pattern), ':');
    if (!p) {
        return false;
    }
    p = skip_ws(p + 1);
    if (!p || *p != '{') {
        return false;
    }

    object_start = p;
    for (; *p; p++) {
        if (escaped) {
            escaped = false;
            continue;
        }
        if (*p == '\\' && in_string) {
            escaped = true;
            continue;
        }
        if (*p == '"') {
            in_string = !in_string;
            continue;
        }
        if (in_string) {
            continue;
        }
        if (*p == '{') {
            depth++;
        } else if (*p == '}') {
            depth--;
            if (depth == 0) {
                object_end = p + 1;
                break;
            }
        }
    }

    if (!object_end || object_end <= object_start) {
        return false;
    }

    object_len = (size_t)(object_end - object_start);
    if (object_len >= sizeof(object_buf)) {
        object_len = sizeof(object_buf) - 1;
    }
    memcpy(object_buf, object_start, object_len);
    object_buf[object_len] = '\0';

    return extract_json_string(object_buf, key, out, out_size);
}

static bool extract_json_number(const char *json,
                                const char *key,
                                float *out_value)
{
    char pattern[64];
    const char *p = NULL;
    char *end_ptr = NULL;

    if (!json || !key || !out_value) {
        return false;
    }

    snprintf(pattern, sizeof(pattern), "\"%s\"", key);
    p = strstr(json, pattern);
    if (!p) {
        return false;
    }

    p = strchr(p + strlen(pattern), ':');
    if (!p) {
        return false;
    }
    p = skip_ws(p + 1);
    if (!p || (!isdigit((unsigned char)*p) && *p != '-' && *p != '+')) {
        return false;
    }

    *out_value = strtof(p, &end_ptr);
    return end_ptr != p;
}

static void parse_cloud_response(const char *response, int http_code)
{
    char status[24] = {0};
    char word[32] = {0};
    char sentence[96] = {0};
    bool have_status = false;
    bool have_word = false;
    bool have_sentence = false;
    bool stale = false;
    bool current_can_be_empty = false;
    float confidence = 0.0f;
    bool should_log = false;

    if (!response || response[0] == '\0') {
        ESP_LOGW(TAG, "cloud json_error: empty response http=%d", http_code);
        set_cloud_display_state("json_error",
                                s_cloud_display.word,
                                s_cloud_display.sentence,
                                http_code,
                                true,
                                s_cloud_display.fail_count + 1);
        return;
    }

    have_status = extract_json_string(response, "status", status, sizeof(status));
    have_word = extract_json_string_after_anchor(response, "result", "word_base", word, sizeof(word));
    have_sentence = extract_json_string_after_anchor(response, "sentence", "text", sentence, sizeof(sentence));
    (void)extract_json_number(response, "confidence", &confidence);

    if (!have_status) {
        ESP_LOGW(TAG, "cloud json_error: missing status http=%d body=%s", http_code, response);
        set_cloud_display_state("json_error",
                                s_cloud_display.word,
                                s_cloud_display.sentence,
                                http_code,
                                true,
                                s_cloud_display.fail_count + 1);
        return;
    }

    current_can_be_empty = strcmp(status, "collecting") == 0 ||
                           strcmp(status, "pending") == 0;

    if (!have_word) {
        if (current_can_be_empty) {
            strncpy(word, "-", sizeof(word) - 1);
            word[sizeof(word) - 1] = '\0';
        } else {
            strncpy(word, s_cloud_display.word, sizeof(word) - 1);
            word[sizeof(word) - 1] = '\0';
            stale = true;
        }
    }
    if (!have_sentence) {
        if (current_can_be_empty) {
            strncpy(sentence, "-", sizeof(sentence) - 1);
            sentence[sizeof(sentence) - 1] = '\0';
        } else {
            strncpy(sentence, s_cloud_display.sentence, sizeof(sentence) - 1);
            sentence[sizeof(sentence) - 1] = '\0';
            stale = true;
        }
    }

    set_cloud_display_state(status,
                            word,
                            sentence,
                            http_code,
                            stale,
                            0);

    should_log = CONFIG_CLOUD_DEBUG_LOG ||
                 strcmp(status, s_last_logged_status) != 0 ||
                 strcmp(status, "confirmed") == 0;
    if (should_log && stale) {
        ESP_LOGI(TAG,
                 "cloud status=%s last_word=%s last_sentence=%s confidence=%.2f stale=1",
                 status,
                 word,
                 sentence,
                 confidence);
        strncpy(s_last_logged_status, status, sizeof(s_last_logged_status) - 1);
        s_last_logged_status[sizeof(s_last_logged_status) - 1] = '\0';
    } else if (should_log) {
        ESP_LOGI(TAG,
                 "cloud status=%s word=%s sentence=%s confidence=%.2f stale=%d",
                 status,
                 word,
                 sentence,
                 confidence,
                 stale ? 1 : 0);
        strncpy(s_last_logged_status, status, sizeof(s_last_logged_status) - 1);
        s_last_logged_status[sizeof(s_last_logged_status) - 1] = '\0';
    }
}

static void cloud_task(void *arg)
{
    app_cloud_frame_t frame = {0};
    app_cloud_frame_t batch[CLOUD_BATCH_MAX_FRAMES_LIMIT] = {0};
    char request_body[CLOUD_REQUEST_BUF_LEN];
    char response_buf[CLOUD_RESPONSE_BUF_LEN];
    cloud_http_event_ctx_t http_event_ctx = {
        .response_buf = response_buf,
    };
    esp_http_client_handle_t client = NULL;
    bool client_is_batch = false;

    (void)arg;
    ESP_LOGI(TAG, "cloud task started");

    while (1) {
        UBaseType_t queue_depth = 0;
        esp_err_t err = ESP_OK;
        int status_code = 0;
        int64_t http_start_us = 0;
        int64_t http_ms = 0;
        int batch_count = 1;
        bool use_batch = false;
        const char *url = s_cloud_frame_url;

        if (!s_cloud_queue) {
            vTaskDelay(pdMS_TO_TICKS(200));
            continue;
        }

        if (xQueueReceive(s_cloud_queue, &frame, portMAX_DELAY) != pdTRUE) {
            continue;
        }

        batch[0] = frame;
        use_batch = s_cloud_batch_supported && CONFIG_CLOUD_BATCH_ENABLE;
        if (use_batch) {
            batch_count = collect_cloud_batch(batch,
                                              cloud_batch_limit(),
                                              cloud_movement_is_active(frame.movement));
            if (batch_count <= 1 && !cloud_movement_is_active(frame.movement)) {
                use_batch = false;
            }
        }

        queue_depth = uxQueueMessagesWaiting(s_cloud_queue);

        if (!app_wifi_is_connected()) {
            if (client) {
                esp_http_client_cleanup(client);
                client = NULL;
            }
            client_is_batch = false;
            set_cloud_display_state("wifi",
                                    s_cloud_display.word,
                                    s_cloud_display.sentence,
                                    0,
                                    true,
                                    s_cloud_display.fail_count);
            continue;
        }

        if (use_batch) {
            if (!build_batch_request(request_body, sizeof(request_body), batch, batch_count)) {
                ESP_LOGW(TAG, "cloud batch request too large, fallback to single frame");
                use_batch = false;
            }
        }
        if (!use_batch &&
            !build_single_request(request_body, sizeof(request_body), &frame)) {
            ESP_LOGW(TAG, "cloud request body build failed");
            set_cloud_display_state("json_error",
                                    s_cloud_display.word,
                                    s_cloud_display.sentence,
                                    0,
                                    true,
                                    s_cloud_display.fail_count + 1);
            continue;
        }

        url = use_batch ? s_cloud_frames_url : s_cloud_frame_url;

        memset(response_buf, 0, sizeof(response_buf));
        set_cloud_display_state("posting",
                                s_cloud_display.word,
                                s_cloud_display.sentence,
                                0,
                                has_cloud_text(s_cloud_display.word) ||
                                    has_cloud_text(s_cloud_display.sentence),
                                s_cloud_display.fail_count);

        http_event_ctx.response_buf = response_buf;
        if (client && client_is_batch != use_batch) {
            esp_http_client_cleanup(client);
            client = NULL;
        }
        if (!client) {
            esp_http_client_config_t config = {
                .url = url,
                .method = HTTP_METHOD_POST,
                .timeout_ms = CONFIG_CLOUD_HTTP_TIMEOUT_MS,
                .event_handler = http_event_handler,
                .user_data = &http_event_ctx,
#if CONFIG_MBEDTLS_CERTIFICATE_BUNDLE
                .crt_bundle_attach = esp_crt_bundle_attach,
#endif
            };

            client = esp_http_client_init(&config);
            if (!client) {
                ESP_LOGW(TAG, "failed to init http client");
                set_cloud_display_state("http_error",
                                        s_cloud_display.word,
                                        s_cloud_display.sentence,
                                        0,
                                        true,
                                        s_cloud_display.fail_count + 1);
                continue;
            }
            esp_http_client_set_header(client, "Content-Type", "application/json");
            client_is_batch = use_batch;
        }

        esp_http_client_set_post_field(client, request_body, (int)strlen(request_body));

        http_start_us = esp_timer_get_time();
        err = esp_http_client_perform(client);
        http_ms = (esp_timer_get_time() - http_start_us) / 1000LL;
        s_cloud_last_http_ms = http_ms;
        if (err != ESP_OK) {
            const char *err_name = esp_err_to_name(err);
            const char *status = (err == ESP_ERR_TIMEOUT ||
                                  strcmp(err_name, "ESP_ERR_HTTP_EAGAIN") == 0) ?
                                 "timeout" :
                                 "http_error";
            if (use_batch) {
                log_cloud_batch_post(batch, batch_count, queue_depth, http_ms, err, 0);
            } else {
                log_cloud_frame_post(&frame, queue_depth, http_ms, err, 0);
            }
            ESP_LOGW(TAG, "cloud post failed: %s", err_name);
            set_cloud_display_state(status,
                                    s_cloud_display.word,
                                    s_cloud_display.sentence,
                                    0,
                                    true,
                                    s_cloud_display.fail_count + 1);
            esp_http_client_cleanup(client);
            client = NULL;
            client_is_batch = false;
            continue;
        }

        status_code = esp_http_client_get_status_code(client);
        if (use_batch) {
            log_cloud_batch_post(batch, batch_count, queue_depth, http_ms, err, status_code);
        } else {
            log_cloud_frame_post(&frame, queue_depth, http_ms, err, status_code);
        }

        if (status_code < 200 || status_code >= 300) {
            ESP_LOGW(TAG, "cloud http status=%d body=%s", status_code, response_buf);
            if (use_batch && (status_code == 404 || status_code == 422)) {
                ESP_LOGW(TAG, "cloud batch unsupported, fallback to /stream/frame");
                s_cloud_batch_supported = false;
                esp_http_client_cleanup(client);
                client = NULL;
                client_is_batch = false;
            }
            set_cloud_display_state("http_error",
                                    s_cloud_display.word,
                                    s_cloud_display.sentence,
                                    status_code,
                                    true,
                                    s_cloud_display.fail_count + 1);
            continue;
        }

        parse_cloud_response(response_buf, status_code);
    }
}

esp_err_t app_cloud_start(void)
{
    if (!CONFIG_CLOUD_ENABLE) {
        set_cloud_display_state("off", "-", "-", 0, false, 0);
        return ESP_OK;
    }

    if (!s_cloud_queue) {
        s_cloud_queue = xQueueCreate(CONFIG_CLOUD_FRAME_QUEUE_LEN, sizeof(app_cloud_frame_t));
    }
    if (!s_cloud_queue) {
        set_cloud_display_state("task_fail", "-", "-", 0, true, 1);
        return ESP_FAIL;
    }

    if (s_cloud_frame_url[0] == '\0') {
        snprintf(s_cloud_frame_url,
                 sizeof(s_cloud_frame_url),
                 "%s/api/v1/stream/frame",
                 CONFIG_CLOUD_BASE_URL);
    }
    if (s_cloud_frames_url[0] == '\0') {
        snprintf(s_cloud_frames_url,
                 sizeof(s_cloud_frames_url),
                 "%s/api/v1/stream/frames",
                 CONFIG_CLOUD_BASE_URL);
    }

    if (!s_cloud_task) {
        if (xTaskCreate(cloud_task, "cloud_task", 12288, NULL, CLOUD_TASK_PRIORITY, &s_cloud_task) != pdPASS) {
            set_cloud_display_state("task_fail", "-", "-", 0, true, 1);
            return ESP_FAIL;
        }
    }

    set_cloud_display_state("wifi", "-", "-", 0, false, 0);
    return ESP_OK;
}

void app_cloud_submit_frame(const app_cloud_frame_t *frame)
{
    app_cloud_frame_t normalized = {0};
    int64_t now_us = esp_timer_get_time();

    if (!CONFIG_CLOUD_ENABLE || !frame || !s_cloud_queue) {
        return;
    }

    normalized = normalize_cloud_frame_for_match(frame);
    if (should_skip_active_without_shape_cache(&normalized, now_us)) {
        return;
    }
    if (!should_enqueue_cloud_frame(&normalized, now_us)) {
        return;
    }

    if (enqueue_cloud_frame_fifo(&normalized)) {
        remember_enqueued_cloud_frame(&normalized, now_us);
    }
}

