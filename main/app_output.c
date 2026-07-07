#include "app_output.h"

#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

static app_output_state_t s_state;
static SemaphoreHandle_t s_state_mutex;

static void copy_text(char *dst, size_t dst_size, const char *src)
{
    if (!dst || dst_size == 0) {
        return;
    }

    if (!src) {
        dst[0] = '\0';
        return;
    }

    strncpy(dst, src, dst_size - 1);
    dst[dst_size - 1] = '\0';
}

static void ensure_state(void)
{
    if (!s_state_mutex) {
        s_state_mutex = xSemaphoreCreateMutex();
        copy_text(s_state.state, sizeof(s_state.state), "detecting");
        s_state.hand_count = 0;
        copy_text(s_state.raw_gesture, sizeof(s_state.raw_gesture), "-");
        s_state.primary_score = 0.0f;
        copy_text(s_state.stable_gesture, sizeof(s_state.stable_gesture), "-");
        copy_text(s_state.debug_profile, sizeof(s_state.debug_profile), "-");
        s_state.stable_count = 0;
        copy_text(s_state.classify_reason, sizeof(s_state.classify_reason), "-");
        s_state.raw_hand_count = 0;
        s_state.classify_count = 0;
        s_state.primitive_held = false;
        s_state.rejected_edge = 0;
        s_state.rejected_small = 0;
        s_state.rejected_weak = 0;
        copy_text(s_state.dominant_side, sizeof(s_state.dominant_side), "none");
        copy_text(s_state.location, sizeof(s_state.location), "unknown");
        copy_text(s_state.movement, sizeof(s_state.movement), "hold");
        copy_text(s_state.bimanual_relation, sizeof(s_state.bimanual_relation), "none");
        copy_text(s_state.dominant_shape, sizeof(s_state.dominant_shape), "no_hand");
        copy_text(s_state.nondominant_shape, sizeof(s_state.nondominant_shape), "no_hand");
        copy_text(s_state.cloud_status, sizeof(s_state.cloud_status), "off");
        copy_text(s_state.cloud_word, sizeof(s_state.cloud_word), "-");
        copy_text(s_state.cloud_sentence, sizeof(s_state.cloud_sentence), "-");
        s_state.cloud_http_code = 0;
        s_state.cloud_stale = false;
        s_state.cloud_fail_count = 0;
    }
}

esp_err_t app_output_init(void)
{
    ensure_state();
    return s_state_mutex ? ESP_OK : ESP_FAIL;
}

void app_output_snapshot(app_output_state_t *out_state)
{
    ensure_state();
    if (!out_state) {
        return;
    }
    if (xSemaphoreTake(s_state_mutex, pdMS_TO_TICKS(20)) == pdTRUE) {
        *out_state = s_state;
        xSemaphoreGive(s_state_mutex);
    }
}

void app_output_set_gesture_state(const char *state,
                                  int hand_count,
                                  const char *raw_gesture,
                                  float primary_score,
                                  const char *stable_gesture,
                                  const char *debug_profile,
                                  int stable_count,
                                  const char *classify_reason)
{
    ensure_state();
    if (xSemaphoreTake(s_state_mutex, pdMS_TO_TICKS(20)) != pdTRUE) {
        return;
    }

    copy_text(s_state.state, sizeof(s_state.state), state ? state : "detecting");
    s_state.hand_count = hand_count;
    copy_text(s_state.raw_gesture, sizeof(s_state.raw_gesture), raw_gesture ? raw_gesture : "-");
    s_state.primary_score = primary_score;
    copy_text(s_state.stable_gesture, sizeof(s_state.stable_gesture), stable_gesture ? stable_gesture : "-");
    copy_text(s_state.debug_profile, sizeof(s_state.debug_profile), debug_profile ? debug_profile : "-");
    s_state.stable_count = stable_count;
    copy_text(s_state.classify_reason, sizeof(s_state.classify_reason), classify_reason ? classify_reason : "-");
    xSemaphoreGive(s_state_mutex);
}

void app_output_set_primitive_state(int raw_hand_count,
                                    int hand_count,
                                    int classify_count,
                                    bool primitive_held,
                                    int rejected_edge,
                                    int rejected_small,
                                    int rejected_weak,
                                    const char *dominant_side,
                                    const char *location,
                                    const char *movement,
                                    const char *bimanual_relation,
                                    const char *dominant_shape,
                                    const char *nondominant_shape)
{
    ensure_state();
    if (xSemaphoreTake(s_state_mutex, pdMS_TO_TICKS(20)) != pdTRUE) {
        return;
    }

    copy_text(s_state.state, sizeof(s_state.state), "primitive");
    s_state.raw_hand_count = raw_hand_count;
    s_state.hand_count = hand_count;
    s_state.classify_count = classify_count;
    s_state.primitive_held = primitive_held;
    s_state.rejected_edge = rejected_edge;
    s_state.rejected_small = rejected_small;
    s_state.rejected_weak = rejected_weak;
    copy_text(s_state.dominant_side, sizeof(s_state.dominant_side),
              dominant_side ? dominant_side : "none");
    copy_text(s_state.location, sizeof(s_state.location),
              location ? location : "unknown");
    copy_text(s_state.movement, sizeof(s_state.movement),
              movement ? movement : "hold");
    copy_text(s_state.bimanual_relation, sizeof(s_state.bimanual_relation),
              bimanual_relation ? bimanual_relation : "none");
    copy_text(s_state.dominant_shape, sizeof(s_state.dominant_shape),
              dominant_shape ? dominant_shape : "no_hand");
    copy_text(s_state.nondominant_shape, sizeof(s_state.nondominant_shape),
              nondominant_shape ? nondominant_shape : "no_hand");
    xSemaphoreGive(s_state_mutex);
}

void app_output_set_cloud_state(const char *cloud_status,
                                const char *cloud_word,
                                const char *cloud_sentence,
                                int cloud_http_code,
                                bool cloud_stale,
                                int cloud_fail_count)
{
    ensure_state();
    if (xSemaphoreTake(s_state_mutex, pdMS_TO_TICKS(20)) != pdTRUE) {
        return;
    }

    copy_text(s_state.cloud_status, sizeof(s_state.cloud_status),
              cloud_status ? cloud_status : "off");
    copy_text(s_state.cloud_word, sizeof(s_state.cloud_word),
              cloud_word ? cloud_word : "-");
    copy_text(s_state.cloud_sentence, sizeof(s_state.cloud_sentence),
              cloud_sentence ? cloud_sentence : "-");
    s_state.cloud_http_code = cloud_http_code;
    s_state.cloud_stale = cloud_stale;
    s_state.cloud_fail_count = cloud_fail_count;
    xSemaphoreGive(s_state_mutex);
}

void app_output_reset(void)
{
    app_output_set_gesture_state("detecting", 0, "-", 0.0f, "-", "-", 0, "-");
    app_output_set_primitive_state(0, 0, 0, false, 0, 0, 0,
                                   "none", "unknown", "hold", "none",
                                   "no_hand", "no_hand");
}

