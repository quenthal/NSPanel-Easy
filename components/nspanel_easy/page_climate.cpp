// page_climate.cpp

#ifdef NSPANEL_EASY_PAGE_CLIMATE

#include "page_climate.h"

#include <algorithm>
#include <cinttypes>
#include <cmath>
#include <cstring>

#include "base.h"
#include "esphome/components/nextion/nextion.h"
#include "esphome/core/helpers.h"  // For parse_number
#include "esphome/core/log.h"
#include "pages.h"  // For get_page_id and current_page_id

#ifdef NSPANEL_EASY_HW_DISPLAY
#include "hw_display.h"  // For current_theme
#endif                   // NSPANEL_EASY_HW_DISPLAY

#ifdef NSPANEL_EASY_PAGE_BUTTONS
#include "page_buttons.h"  // For button_draw
#endif                     // NSPANEL_EASY_PAGE_BUTTONS

#ifdef NSPANEL_EASY_PAGE_POPUP_SELECT
#include "page_popup_select.h"
#endif  // NSPANEL_EASY_PAGE_POPUP_SELECT

namespace esphome::nspanel_easy {

static const char *const TAG = "nspanel.page.climate";

bool climate_embedded_visible = false;

/// @brief Presets of the Home Assistant climate shown on the page, for the picker.
static std::vector<std::string> climate_preset_modes;
/// @brief Its active preset; empty when none.
static std::string climate_preset_mode;

/**
 * @brief Numeric attribute.
 *
 * @param entity The climate, from the snapshot.
 * @param key Attribute name.
 * @return The attribute; empty when it was not sent or is not a finite number.
 */
static optional<float> climate_number(const SnapshotEntity &entity, const char *key) {
  const optional<float> value = parse_number<float>(entity.attribute(key));
  if (value.has_value() && std::isfinite(*value)) {
    return value;
  }  // if (finite number)
  return {};
}

/**
 * @brief Temperature attribute rounded to one decimal, as shown.
 *
 * @param entity The climate, from the snapshot.
 * @param key Attribute name.
 * @return The temperature; -999 when it was not sent or is not a number.
 */
static float climate_temperature(const SnapshotEntity &entity, const char *key) {
  const optional<float> value = climate_number(entity, key);
  return value.has_value() ? std::round(*value * 10.0f) / 10.0f : -999.0f;
}

/**
 * @brief Whether a state or attribute carries no usable value.
 *
 * @param text The state or attribute.
 * @return true for empty, unknown, unavailable or none.
 */
static bool climate_unusable(const std::string &text) {
  return text.empty() || text == "unknown" || text == "unavailable" || text == "None" || text == "none";
}

ClimateView climate_view(const SnapshotEntity &entity) {
  ClimateView view;
  const optional<uint32_t> features = parse_number<uint32_t>(entity.attribute("supported_features"));
  view.supported_features = features.value_or(0);

  // Slider step, in tenths: target_temp_step, else target_temperature_step, else 0.5
  optional<float> step = climate_number(entity, "target_temp_step");
  if (!step.has_value()) {
    step = climate_number(entity, "target_temperature_step");
  }  // if (no target_temp_step)
  const int32_t step_tenths = static_cast<int32_t>(std::lround(std::fabs(step.value_or(0.5f)) * 10.0f));
  view.temp_step = (step_tenths > 0) ? step_tenths : 10;  // A step that rounds to zero would break the slider

  // Slider range, in tenths; the minimum is rounded up to a multiple of the step
  const int32_t min_tenths =
      static_cast<int32_t>(std::lround(climate_number(entity, "min_temp").value_or(7.0f) * 10.0f));
  const int32_t max_tenths =
      static_cast<int32_t>(std::lround(climate_number(entity, "max_temp").value_or(35.0f) * 10.0f));
  const int32_t remainder = ((min_tenths % view.temp_step) + view.temp_step) % view.temp_step;
  view.temp_offset = (remainder == 0) ? min_tenths : min_tenths + view.temp_step - remainder;
  view.total_steps = (max_tenths >= view.temp_offset) ? (max_tenths - view.temp_offset) / view.temp_step : 0;

  view.current_temp = climate_temperature(entity, "current_temperature");
  if ((view.supported_features & 1) != 0) {  // TARGET_TEMPERATURE
    view.target_temp = climate_temperature(entity, "temperature");
  }  // if (target temperature)
  if ((view.supported_features & 2) != 0) {  // TARGET_TEMPERATURE_RANGE
    view.target_temp_high = climate_temperature(entity, "target_temp_high");
    view.target_temp_low = climate_temperature(entity, "target_temp_low");
  }  // if (target temperature range)

  // Icon of what the climate is doing, else of its mode; checked in this order, as "heat_cool" contains "heat"
  const std::string &hvac_action = entity.attribute("hvac_action");
  const std::string &action = climate_unusable(hvac_action) ? entity.state : hvac_action;
  struct ActionIcon {
    const char *text;
    const char *icon;
  };
  static constexpr ActionIcon ACTION_ICONS[] = {
      {"off", Icons::MDI_NONE},
      {"heat_cool", Icons::MDI_AUTORENEW},
      {"heat", Icons::MDI_THERMOMETER_LINES},  // Also "heating"
      {"cool", Icons::MDI_SNOWFLAKE},          // Also "cooling"
      {"dry", Icons::MDI_WATER_PERCENT},       // Also "drying"
      {"fan", Icons::MDI_FAN},                 // Also "fan_only"
      {"auto", Icons::MDI_REFRESH_AUTO},
      {"idle", Icons::MDI_THERMOMETER},
  };
  for (const ActionIcon &entry : ACTION_ICONS) {
    if (action.find(entry.text) != std::string::npos) {
      view.icon = entry.icon;
      break;
    }  // if (action matches)
  }  // for each action icon
  return view;
}

/**
 * @brief Label shown beside a tile button of the climate page.
 *
 * @param name Button component name.
 * @return The label component name, or nullptr when the button has none.
 */
static const char *climate_tile_label(const char *name) {
  if (strcmp(name, "button03") == 0) {
    return "lbl_heat";
  } else if (strcmp(name, "button08") == 0) {
    return "button08_lbl";
  } else if (strcmp(name, "button09") == 0) {
    return "button09_lbl";
  }  // if (name)
  return nullptr;
}

void climate_tile_draw(const char *name, bool shown, bool on, bool working, uint16_t color) {
  if (nextion_display == nullptr) {
    return;
  }  // if (no display)
  const bool heating_tile = strcmp(name, "button03") == 0;
  if (heating_tile) {
    nextion_display->send_command_printf("climate.heat_on.val=%d", on ? 1 : 0);  // for its toggle
  }  // if (heating_tile)
  const char *label = climate_tile_label(name);
  if (!shown || label == nullptr) {  // only heating and the custom buttons are tiles
    nextion_display->hide_component(name);
    if (label != nullptr) {
      nextion_display->hide_component(label);
    }  // if (label)
    return;
  }  // if (!shown || label == nullptr)
#ifdef NSPANEL_EASY_HW_DISPLAY
  const bool light_theme = (current_theme == ThemeMode::LIGHT);
#else   // NSPANEL_EASY_HW_DISPLAY
  const bool light_theme = false;
#endif  // NSPANEL_EASY_HW_DISPLAY
  // Amber means "working": heating right now, or the device on
  const bool amber = on && working;
  const uint8_t tiles = light_theme ? (amber ? CLIMATE_TILES_ON_PIC_LIGHT : CLIMATE_TILES_PIC_LIGHT)
                                    : (amber ? CLIMATE_TILES_ON_PIC_DARK : CLIMATE_TILES_PIC_DARK);
  if (light_theme) {
    color = on ? Colors::RGB565_MIDNIGHT_TEXT : Colors::RGB565_MIDNIGHT_TEXT_SECONDARY;
  }  // if (light_theme)
  nextion_display->send_command_printf("climate.%s.picc=%" PRIu8, name, tiles);
  nextion_display->send_command_printf("climate.%s.pco=%" PRIu16, name, color);
  nextion_display->show_component(name);
  nextion_display->send_command_printf("climate.%s.picc=%" PRIu8, label, tiles);
  nextion_display->send_command_printf("climate.%s.pco=%s", label, on ? "color_pco_main" : "color_pco_secondary");
  nextion_display->show_component(label);
}

void climate_mode_buttons_render(const SnapshotEntity &entity) {
  if (nextion_display == nullptr) {
    return;
  }  // if (no display)
  const std::vector<std::string> *modes = entity.list("hvac_modes");
  // Heating right now: from hvac_action when the climate reports it, else whenever it is in heat mode
  const std::string &hvac_action = entity.attribute("hvac_action");
  const bool heating = climate_unusable(hvac_action) || hvac_action == "heating" || hvac_action == "preheating";
  for (const ClimateModeButton &button : CLIMATE_MODE_BUTTONS) {
    const bool supported =
        modes != nullptr && std::find(modes->begin(), modes->end(), button.hvac_mode) != modes->end();
    const bool active = entity.state == button.hvac_mode;
    climate_tile_draw(button.name, supported, active, heating, active ? button.color_active : button.color_inactive);
  }  // for (button : CLIMATE_MODE_BUTTONS)
}

#ifdef NSPANEL_EASY_SUBSCRIBE
void climate_sub_render(const SubBinding &binding, const SubRuntime &rt, const char *state, bool /*visible*/) {
  if (strcmp(binding.component, "button08") != 0 && strcmp(binding.component, "button09") != 0) {
    ESP_LOGW(TAG, "'%s' is not a climate custom button", binding.component);
    return;
  }  // if (not a custom button)
  if (!rt.has_appearance) {
    return;  // Nothing to draw until the Blueprint has pushed the appearance in this session
  }  // if (no appearance)

  // The Blueprint's icon (override, or the entity's own icon) wins; otherwise resolved from the
  // domain, device class and state
  const bool active = (rt.last_state == SUB_STATE_ON);
  const char *icon = active ? rt.icon_on : rt.icon_off;
  uint16_t color = active ? rt.color_on : rt.color_off;
  if (icon[0] == '\0') {
    const SubAppearance look = resolve_binding_appearance(binding, state, rt.color_on, rt.color_off);
    if (look.icon != nullptr) {
      icon = look.icon;
      color = look.color;
    }  // if (resolved)
  }  // if (no icon from the Blueprint)
  if (icon[0] == '\0') {
    icon = Icons::MDI_ALERT_CIRCLE;
  }  // if (still no icon)
  const bool available = !api_stale && rt.last_state != SUB_STATE_UNAVAILABLE;
  ESP_LOGV(TAG, "%s: icon_color=%" PRIu16 " available=%s", binding.component, color, YESNO(available));
#ifdef NSPANEL_EASY_PAGE_BUTTONS
  // Drawn as the other buttons, so every button surface follows the same rules; only while the page is shown
  button_draw(get_page_id("climate"), binding.component, false, icon, color, 0, "", "", false, true, available, 1);
#endif  // NSPANEL_EASY_PAGE_BUTTONS
  // An "on" device is an active (amber) tile
  if (current_page_id == get_page_id("climate")) {
    climate_tile_draw(binding.component, true, active && available, true, color);
  }  // if (climate page shown)
}
#endif  // NSPANEL_EASY_SUBSCRIBE

}  // namespace esphome::nspanel_easy

#endif  // NSPANEL_EASY_PAGE_CLIMATE
