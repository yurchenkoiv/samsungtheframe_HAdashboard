"""Config flow for Samsung Frame Art integration."""
from __future__ import annotations

import os
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    DOMAIN,
    CONF_TV_IP,
    CONF_MEDIA_FOLDER,
    CONF_TOKEN_FILE,
    CONF_CALENDAR_ENTITY,
    CONF_LANGUAGE,
    CONF_UPCOMING_DAYS,
    CONF_MATTE_COLOR,
    CONF_OVERLAY_OPACITY,
    CONF_DEBUG_SAVE,
    CONF_FONT_SIZE,
    DEFAULT_MEDIA_FOLDER,
    DEFAULT_TOKEN_FILE,
    DEFAULT_UPCOMING_DAYS,
    DEFAULT_MATTE_COLOR,
    DEFAULT_LANGUAGE,
    DEFAULT_OVERLAY_OPACITY,
    DEFAULT_DEBUG_SAVE,
    DEFAULT_FONT_SIZE,
    LANGUAGES,
    MATTE_OPTIONS,
)


def _setup_schema(defaults: dict) -> vol.Schema:
    return vol.Schema({
        vol.Required(CONF_TV_IP, default=defaults.get(CONF_TV_IP, "")): str,
        vol.Required(CONF_MEDIA_FOLDER, default=defaults.get(CONF_MEDIA_FOLDER, DEFAULT_MEDIA_FOLDER)): str,
        vol.Required(CONF_TOKEN_FILE, default=defaults.get(CONF_TOKEN_FILE, DEFAULT_TOKEN_FILE)): str,
        vol.Optional(CONF_CALENDAR_ENTITY, default=defaults.get(CONF_CALENDAR_ENTITY, "")): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="calendar")
        ),
        vol.Required(CONF_LANGUAGE, default=defaults.get(CONF_LANGUAGE, DEFAULT_LANGUAGE)): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[{"value": k, "label": v} for k, v in LANGUAGES.items()],
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        ),
        vol.Required(CONF_UPCOMING_DAYS, default=defaults.get(CONF_UPCOMING_DAYS, DEFAULT_UPCOMING_DAYS)): selector.NumberSelector(
            selector.NumberSelectorConfig(min=1, max=14, mode=selector.NumberSelectorMode.BOX)
        ),
        vol.Required(CONF_MATTE_COLOR, default=defaults.get(CONF_MATTE_COLOR, DEFAULT_MATTE_COLOR)): selector.SelectSelector(
            selector.SelectSelectorConfig(options=MATTE_OPTIONS, mode=selector.SelectSelectorMode.DROPDOWN)
        ),
        vol.Required(CONF_OVERLAY_OPACITY, default=defaults.get(CONF_OVERLAY_OPACITY, DEFAULT_OVERLAY_OPACITY)): selector.NumberSelector(
            selector.NumberSelectorConfig(min=10, max=90, step=5, mode=selector.NumberSelectorMode.SLIDER)
        ),
        vol.Required(CONF_FONT_SIZE, default=defaults.get(CONF_FONT_SIZE, DEFAULT_FONT_SIZE)): selector.NumberSelector(
            selector.NumberSelectorConfig(min=50, max=200, step=10, mode=selector.NumberSelectorMode.SLIDER)
        ),
    })


def _options_schema(defaults: dict) -> vol.Schema:
    return vol.Schema({
        vol.Required(CONF_OVERLAY_OPACITY, default=defaults.get(CONF_OVERLAY_OPACITY, DEFAULT_OVERLAY_OPACITY)): selector.NumberSelector(
            selector.NumberSelectorConfig(min=10, max=90, step=5, mode=selector.NumberSelectorMode.SLIDER)
        ),
        vol.Required(CONF_FONT_SIZE, default=defaults.get(CONF_FONT_SIZE, DEFAULT_FONT_SIZE)): selector.NumberSelector(
            selector.NumberSelectorConfig(min=50, max=200, step=10, mode=selector.NumberSelectorMode.SLIDER)
        ),
        vol.Required(CONF_UPCOMING_DAYS, default=defaults.get(CONF_UPCOMING_DAYS, DEFAULT_UPCOMING_DAYS)): selector.NumberSelector(
            selector.NumberSelectorConfig(min=1, max=14, mode=selector.NumberSelectorMode.BOX)
        ),
        vol.Required(CONF_MATTE_COLOR, default=defaults.get(CONF_MATTE_COLOR, DEFAULT_MATTE_COLOR)): selector.SelectSelector(
            selector.SelectSelectorConfig(options=MATTE_OPTIONS, mode=selector.SelectSelectorMode.DROPDOWN)
        ),
        vol.Required(CONF_LANGUAGE, default=defaults.get(CONF_LANGUAGE, DEFAULT_LANGUAGE)): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[{"value": k, "label": v} for k, v in LANGUAGES.items()],
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        ),
        vol.Optional(CONF_CALENDAR_ENTITY, default=defaults.get(CONF_CALENDAR_ENTITY, "")): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="calendar")
        ),
        vol.Optional(CONF_DEBUG_SAVE, default=defaults.get(CONF_DEBUG_SAVE, DEFAULT_DEBUG_SAVE)): selector.BooleanSelector(),
    })


class SamsungFrameConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}

        if user_input is not None:
            media_folder = user_input[CONF_MEDIA_FOLDER]

            import asyncio

            def _check():
                if not os.path.isdir(media_folder):
                    return "invalid_path"
                images = [f for f in os.listdir(media_folder)
                          if f.lower().endswith((".jpg", ".jpeg", ".png"))]
                return "no_images" if not images else None

            err = await asyncio.get_event_loop().run_in_executor(None, _check)
            if err:
                errors[CONF_MEDIA_FOLDER] = err
            else:
                await self.async_set_unique_id(user_input[CONF_TV_IP])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Samsung Frame ({user_input[CONF_TV_IP]})",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_setup_schema({}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return SamsungFrameOptionsFlow()


class SamsungFrameOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(current),
        )
