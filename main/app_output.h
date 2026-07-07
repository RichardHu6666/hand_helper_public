#pragma once

#include <stdbool.h>

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    char state[16];
    int hand_count;
    char raw_gesture[24];
    float primary_score;
    char stable_gesture[24];
    char debug_profile[24];
    int stable_count;
    char classify_reason[24];
    int raw_hand_count;
    int classify_count;
    bool primitive_held;
    int rejected_edge;
    int rejected_small;
    int rejected_weak;
    char dominant_side[24];
    char location[32];
    char movement[24];
    char bimanual_relation[32];
    char dominant_shape[24];
    char nondominant_shape[24];
    char cloud_status[24];
    char cloud_word[32];
    char cloud_sentence[96];
    int cloud_http_code;
    bool cloud_stale;
    int cloud_fail_count;
} app_output_state_t;

esp_err_t app_output_init(void);
void app_output_snapshot(app_output_state_t *out_state);
void app_output_set_gesture_state(const char *state,
                                  int hand_count,
                                  const char *raw_gesture,
                                  float primary_score,
                                  const char *stable_gesture,
                                  const char *debug_profile,
                                  int stable_count,
                                  const char *classify_reason);
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
                                    const char *nondominant_shape);
void app_output_set_cloud_state(const char *cloud_status,
                                const char *cloud_word,
                                const char *cloud_sentence,
                                int cloud_http_code,
                                bool cloud_stale,
                                int cloud_fail_count);
void app_output_reset(void);

#ifdef __cplusplus
}
#endif

