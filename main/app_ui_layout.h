#pragma once

#include <stdbool.h>

#define APP_UI_PANEL_X 20
#define APP_UI_PANEL_Y 20
#define APP_UI_PANEL_W 430
#define APP_UI_PANEL_H 260

static inline bool app_ui_panel_contains(int x, int y)
{
    return x >= APP_UI_PANEL_X &&
           x < (APP_UI_PANEL_X + APP_UI_PANEL_W) &&
           y >= APP_UI_PANEL_Y &&
           y < (APP_UI_PANEL_Y + APP_UI_PANEL_H);
}

