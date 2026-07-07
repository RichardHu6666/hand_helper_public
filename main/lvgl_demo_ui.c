#include "lvgl_demo_ui.h"

#include <stdio.h>
#include <string.h>

#include "app_output.h"
#include "app_ui_layout.h"
#include "sdkconfig.h"

#ifndef CONFIG_UI_SHOW_REJECT_LINE
#define CONFIG_UI_SHOW_REJECT_LINE 0
#endif

LV_FONT_DECLARE(lv_font_sign_ui_14);

static lv_obj_t *s_state_label;
static lv_obj_t *s_hands_label;
static lv_obj_t *s_side_loc_label;
static lv_obj_t *s_move_rel_label;
static lv_obj_t *s_shape_label;
static lv_obj_t *s_filter_label;
static lv_obj_t *s_cloud_label;
static lv_obj_t *s_word_label;
static lv_obj_t *s_sentence_label;
static app_output_state_t s_last_state;
static bool s_has_last_state;

static void apply_label_font(lv_obj_t *obj)
{
    lv_obj_set_style_text_color(obj, lv_color_hex(0xF8FAFC), 0);
    lv_obj_set_style_text_opa(obj, LV_OPA_COVER, 0);
    lv_obj_set_style_text_font(obj, &lv_font_sign_ui_14, 0);
}

static void update_label_if_changed(lv_obj_t *label,
                                    const char *prefix,
                                    const char *new_value,
                                    char *cached_value,
                                    size_t cached_size)
{
    if (!label || !prefix || !new_value || !cached_value || cached_size == 0) {
        return;
    }

    if (strncmp(cached_value, new_value, cached_size) == 0) {
        return;
    }

    lv_label_set_text_fmt(label, "%s%s", prefix, new_value);
    strncpy(cached_value, new_value, cached_size - 1);
    cached_value[cached_size - 1] = '\0';
}

static void update_cloud_if_changed(const app_output_state_t *state)
{
    char cloud_buf[48];
    char word_buf[48];
    char sentence_buf[120];
    bool stale_changed;

    if (!state) {
        return;
    }

    stale_changed = s_last_state.cloud_stale != state->cloud_stale;

    if (s_cloud_label &&
        (strncmp(s_last_state.cloud_status, state->cloud_status,
                 sizeof(s_last_state.cloud_status)) != 0 ||
         stale_changed ||
         s_last_state.cloud_fail_count != state->cloud_fail_count)) {
        snprintf(cloud_buf,
                 sizeof(cloud_buf),
                 "Cloud: %s%s",
                 state->cloud_status,
                 state->cloud_stale ? " stale" : "");
        lv_label_set_text(s_cloud_label, cloud_buf);
        strncpy(s_last_state.cloud_status, state->cloud_status,
                sizeof(s_last_state.cloud_status) - 1);
        s_last_state.cloud_status[sizeof(s_last_state.cloud_status) - 1] = '\0';
        s_last_state.cloud_stale = state->cloud_stale;
        s_last_state.cloud_fail_count = state->cloud_fail_count;
    }

    if (s_word_label &&
        (strncmp(s_last_state.cloud_word, state->cloud_word,
                 sizeof(s_last_state.cloud_word)) != 0 ||
         stale_changed)) {
        snprintf(word_buf,
                 sizeof(word_buf),
                 "%s%s",
                 state->cloud_stale ? "Word(old): " : "Word: ",
                 state->cloud_word);
        lv_label_set_text(s_word_label, word_buf);
        strncpy(s_last_state.cloud_word, state->cloud_word,
                sizeof(s_last_state.cloud_word) - 1);
        s_last_state.cloud_word[sizeof(s_last_state.cloud_word) - 1] = '\0';
    }

    if (s_sentence_label &&
        (strncmp(s_last_state.cloud_sentence, state->cloud_sentence,
                 sizeof(s_last_state.cloud_sentence)) != 0 ||
         stale_changed)) {
        snprintf(sentence_buf,
                 sizeof(sentence_buf),
                 "%s%s",
                 state->cloud_stale ? "Sentence(old): " : "Sentence: ",
                 state->cloud_sentence);
        lv_label_set_text(s_sentence_label, sentence_buf);
        strncpy(s_last_state.cloud_sentence, state->cloud_sentence,
                sizeof(s_last_state.cloud_sentence) - 1);
        s_last_state.cloud_sentence[sizeof(s_last_state.cloud_sentence) - 1] = '\0';
    }
}

static void update_counts_if_changed(const app_output_state_t *state)
{
    char buf[64];

    if (!s_hands_label) {
        return;
    }
    if (s_has_last_state &&
        s_last_state.raw_hand_count == state->raw_hand_count &&
        s_last_state.hand_count == state->hand_count &&
        s_last_state.classify_count == state->classify_count &&
        s_last_state.primitive_held == state->primitive_held) {
        return;
    }

    snprintf(buf, sizeof(buf), "Hands: raw=%d use=%d cls=%d hold=%d",
             state->raw_hand_count,
             state->hand_count,
             state->classify_count,
             state->primitive_held ? 1 : 0);
    lv_label_set_text(s_hands_label, buf);
    s_last_state.raw_hand_count = state->raw_hand_count;
    s_last_state.hand_count = state->hand_count;
    s_last_state.classify_count = state->classify_count;
    s_last_state.primitive_held = state->primitive_held;
}

static void update_filter_if_changed(const app_output_state_t *state)
{
    char buf[64];

    if (!CONFIG_UI_SHOW_REJECT_LINE || !s_filter_label) {
        return;
    }
    if (s_has_last_state &&
        s_last_state.rejected_edge == state->rejected_edge &&
        s_last_state.rejected_small == state->rejected_small &&
        s_last_state.rejected_weak == state->rejected_weak) {
        return;
    }

    snprintf(buf, sizeof(buf), "Reject: edge=%d small=%d weak=%d",
             state->rejected_edge,
             state->rejected_small,
             state->rejected_weak);
    lv_label_set_text(s_filter_label, buf);
    s_last_state.rejected_edge = state->rejected_edge;
    s_last_state.rejected_small = state->rejected_small;
    s_last_state.rejected_weak = state->rejected_weak;
}

static void update_side_loc_if_changed(const app_output_state_t *state)
{
    char buf[96];

    if (!s_side_loc_label) {
        return;
    }
    if (s_has_last_state &&
        strncmp(s_last_state.dominant_side, state->dominant_side,
                sizeof(s_last_state.dominant_side)) == 0 &&
        strncmp(s_last_state.location, state->location,
                sizeof(s_last_state.location)) == 0) {
        return;
    }

    snprintf(buf, sizeof(buf), "Side/Loc: %s / %s",
             state->dominant_side,
             state->location);
    lv_label_set_text(s_side_loc_label, buf);
    strncpy(s_last_state.dominant_side, state->dominant_side,
            sizeof(s_last_state.dominant_side) - 1);
    s_last_state.dominant_side[sizeof(s_last_state.dominant_side) - 1] = '\0';
    strncpy(s_last_state.location, state->location,
            sizeof(s_last_state.location) - 1);
    s_last_state.location[sizeof(s_last_state.location) - 1] = '\0';
}

static void update_move_rel_if_changed(const app_output_state_t *state)
{
    char buf[96];

    if (!s_move_rel_label) {
        return;
    }
    if (s_has_last_state &&
        strncmp(s_last_state.movement, state->movement,
                sizeof(s_last_state.movement)) == 0 &&
        strncmp(s_last_state.bimanual_relation, state->bimanual_relation,
                sizeof(s_last_state.bimanual_relation)) == 0) {
        return;
    }

    snprintf(buf, sizeof(buf), "Move/Rel: %s / %s",
             state->movement,
             state->bimanual_relation);
    lv_label_set_text(s_move_rel_label, buf);
    strncpy(s_last_state.movement, state->movement,
            sizeof(s_last_state.movement) - 1);
    s_last_state.movement[sizeof(s_last_state.movement) - 1] = '\0';
    strncpy(s_last_state.bimanual_relation, state->bimanual_relation,
            sizeof(s_last_state.bimanual_relation) - 1);
    s_last_state.bimanual_relation[sizeof(s_last_state.bimanual_relation) - 1] = '\0';
}

static void update_shape_if_changed(const app_output_state_t *state)
{
    char buf[72];

    if (!s_shape_label) {
        return;
    }
    if (s_has_last_state &&
        strncmp(s_last_state.dominant_shape, state->dominant_shape,
                sizeof(s_last_state.dominant_shape)) == 0 &&
        strncmp(s_last_state.nondominant_shape, state->nondominant_shape,
                sizeof(s_last_state.nondominant_shape)) == 0) {
        return;
    }

    snprintf(buf, sizeof(buf), "Shape: D=%s N=%s",
             state->dominant_shape,
             state->nondominant_shape);
    lv_label_set_text(s_shape_label, buf);
    strncpy(s_last_state.dominant_shape, state->dominant_shape,
            sizeof(s_last_state.dominant_shape) - 1);
    s_last_state.dominant_shape[sizeof(s_last_state.dominant_shape) - 1] = '\0';
    strncpy(s_last_state.nondominant_shape, state->nondominant_shape,
            sizeof(s_last_state.nondominant_shape) - 1);
    s_last_state.nondominant_shape[sizeof(s_last_state.nondominant_shape) - 1] = '\0';
}

static void apply_output_state(const app_output_state_t *state)
{
    if (!state) {
        return;
    }

    if (!s_has_last_state) {
        memset(&s_last_state, 0, sizeof(s_last_state));
        s_last_state.hand_count = -1;
        s_has_last_state = true;
    }

    update_label_if_changed(s_state_label,
                            "Primitive: ",
                            state->state,
                            s_last_state.state,
                            sizeof(s_last_state.state));
    update_counts_if_changed(state);
    update_side_loc_if_changed(state);
    update_move_rel_if_changed(state);
    update_shape_if_changed(state);
    update_filter_if_changed(state);
    update_cloud_if_changed(state);
}

static void sign_ui_timer_cb(lv_timer_t *timer)
{
    app_output_state_t state = {0};

    LV_UNUSED(timer);
    app_output_snapshot(&state);
    apply_output_state(&state);
}

void example_lvgl_demo_ui(lv_display_t *disp)
{
    lv_obj_t *screen = lv_display_get_screen_active(disp);
    lv_obj_t *panel = lv_obj_create(screen);

    lv_obj_set_style_text_font(screen, &lv_font_sign_ui_14, 0);
    lv_obj_set_style_text_font(panel, &lv_font_sign_ui_14, 0);

    lv_obj_set_size(panel, APP_UI_PANEL_W, APP_UI_PANEL_H);
    lv_obj_align(panel, LV_ALIGN_TOP_LEFT, APP_UI_PANEL_X, APP_UI_PANEL_Y);
    lv_obj_set_style_bg_opa(panel, LV_OPA_COVER, 0);
    lv_obj_set_style_bg_color(panel, lv_color_hex(0x0F172A), 0);
    lv_obj_set_style_border_width(panel, 1, 0);
    lv_obj_set_style_border_color(panel, lv_color_hex(0x334155), 0);
    lv_obj_set_style_radius(panel, 8, 0);
    lv_obj_set_style_pad_all(panel, 10, 0);
    lv_obj_set_layout(panel, LV_LAYOUT_FLEX);
    lv_obj_set_flex_flow(panel, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_style_pad_row(panel, 4, 0);

    s_state_label = lv_label_create(panel);
    s_hands_label = lv_label_create(panel);
    s_side_loc_label = lv_label_create(panel);
    s_move_rel_label = lv_label_create(panel);
    s_shape_label = lv_label_create(panel);
    if (CONFIG_UI_SHOW_REJECT_LINE) {
        s_filter_label = lv_label_create(panel);
    }
    s_cloud_label = lv_label_create(panel);
    s_word_label = lv_label_create(panel);
    s_sentence_label = lv_label_create(panel);
    apply_label_font(s_state_label);
    apply_label_font(s_hands_label);
    apply_label_font(s_side_loc_label);
    apply_label_font(s_move_rel_label);
    apply_label_font(s_shape_label);
    if (s_filter_label) {
        apply_label_font(s_filter_label);
    }
    apply_label_font(s_cloud_label);
    apply_label_font(s_word_label);
    apply_label_font(s_sentence_label);

    lv_obj_set_width(s_hands_label, lv_pct(100));
    lv_obj_set_width(s_side_loc_label, lv_pct(100));
    lv_obj_set_width(s_move_rel_label, lv_pct(100));
    lv_obj_set_width(s_shape_label, lv_pct(100));
    if (s_filter_label) {
        lv_obj_set_width(s_filter_label, lv_pct(100));
    }
    lv_obj_set_width(s_cloud_label, lv_pct(100));
    lv_obj_set_width(s_word_label, lv_pct(100));
    lv_obj_set_width(s_sentence_label, lv_pct(100));
    lv_label_set_long_mode(s_sentence_label, LV_LABEL_LONG_WRAP);

    lv_timer_create(sign_ui_timer_cb, 33, NULL);
    sign_ui_timer_cb(NULL);
}

