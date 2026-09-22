from __future__ import annotations

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import UnitOfTemperature

from .const import SPECIAL
from .entity_base import HaierAtwEntity


_MODE_TO_HVAC: dict[int, HVACMode] = {
    0: HVACMode.AUTO,
    1: HVACMode.COOL,
    2: HVACMode.HEAT,
    5: HVACMode.HEAT,
    6: HVACMode.AUTO,
    7: HVACMode.COOL,
    8: HVACMode.HEAT,
}

_HVAC_TO_MODE: dict[HVACMode, int] = {
    HVACMode.AUTO: 0,
    HVACMode.COOL: 1,
    HVACMode.HEAT: 2,
}


class HaierAtwClimate(HaierAtwEntity, ClimateEntity):
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.AUTO, HVACMode.HEAT, HVACMode.COOL]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_OFF
        | ClimateEntityFeature.TURN_ON
    )
    _attr_temperature_unit = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "climate_zone1")
        self._attr_unique_id = f"{coordinator.entry.entry_id}_climate_zone1"
        self._attr_name = "ZONE1 Climate"

        special_map = getattr(coordinator, "special", SPECIAL)
        power_spec = special_map["power"]
        mode_spec = special_map["mode"]
        setpoint_spec = special_map["zone1_sp"]

        self._power_reg = power_spec["register"]
        self._power_verify = power_spec["verify_register"]
        self._power_on_value = int(power_spec.get("on_value", 1))
        self._power_off_value = int(power_spec.get("off_value", 0))
        self._mode_reg = mode_spec["register"]
        self._mode_verify = mode_spec["verify_register"]
        self._setpoint_reg = setpoint_spec["register"]
        self._setpoint_verify = setpoint_spec["verify_register"]
        self._scale_write = float(setpoint_spec.get("scale_write", 1.0))
        self._scale_read = float(setpoint_spec.get("scale_read", 1.0))
        self._attr_target_temperature_step = float(setpoint_spec.get("step", 1.0))
        self._attr_min_temp = float(setpoint_spec.get("min", 0))
        self._attr_max_temp = float(setpoint_spec.get("max", 80))
        
        # Получаем регистр текущей температуры строго из профиля текущего устройства
        self._current_temperature_register = int(getattr(coordinator, "current_temperature_register", 40142))

        profile_mode_to_hvac = dict(getattr(coordinator, "mode_to_hvac", {}))
        profile_hvac_to_mode = dict(getattr(coordinator, "hvac_to_mode", {}))

        lookup_hvac = {
            "off": HVACMode.OFF,
            "auto": HVACMode.AUTO,
            "cool": HVACMode.COOL,
            "heat": HVACMode.HEAT,
        }
        self._mode_to_hvac = _MODE_TO_HVAC
        if profile_mode_to_hvac:
            parsed: dict[int, HVACMode] = {}
            for mode_raw, hvac_name in profile_mode_to_hvac.items():
                hvac = lookup_hvac.get(str(hvac_name).lower())
                if hvac is not None:
                    parsed[int(mode_raw)] = hvac
            if parsed:
                self._mode_to_hvac = parsed

        self._hvac_to_mode = _HVAC_TO_MODE
        if profile_hvac_to_mode:
            parsed_hvac_to_mode: dict[HVACMode, int] = {}
            for hvac_name, mode_raw in profile_hvac_to_mode.items():
                hvac = lookup_hvac.get(str(hvac_name).lower())
                if hvac is not None and hvac != HVACMode.OFF:
                    parsed_hvac_to_mode[hvac] = int(mode_raw)
            if parsed_hvac_to_mode:
                self._hvac_to_mode = parsed_hvac_to_mode
                supported = [HVACMode.OFF] + [m for m in (HVACMode.AUTO, HVACMode.HEAT, HVACMode.COOL) if m in parsed_hvac_to_mode]
                self._attr_hvac_modes = supported

    @property
    def hvac_mode(self) -> HVACMode | None:
        power = self.coordinator.get_raw_by_register(self._power_verify)
        if power is None:
            return None
        if int(power) == self._power_off_value:
            return HVACMode.OFF

        mode_raw = self.coordinator.get_raw_by_register(self._mode_verify)
        if mode_raw is None:
            return HVACMode.HEAT
        return self._mode_to_hvac.get(int(mode_raw), HVACMode.HEAT)

    @property
    def target_temperature(self) -> float | None:
        raw = self.coordinator.get_raw_by_register(self._setpoint_verify)
        if raw is None:
            return None
        return round(float(raw) * self._scale_read, 1)

    @property
    def current_temperature(self) -> float | None:
        raw = self.coordinator.get_raw_by_register(self._current_temperature_register)
        if raw is None:
            return None
        scale, dtype = self.coordinator.infer_meta(self._current_temperature_register)
        value = int(raw)
        if dtype == "int16" and value >= 0x8000:
            value -= 0x10000
        return round(float(value) * float(scale), 1)

    async def async_set_temperature(self, **kwargs) -> None:
        if (temperature := kwargs.get("temperature")) is None:
            return
        raw = int(round(float(temperature) * self._scale_write))
        await self.coordinator.client.write_register(
            self.coordinator.register_to_address(self._setpoint_reg),
            raw,
        )
        await self.coordinator.async_request_refresh()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self.async_turn_off()
            return
        if hvac_mode not in self._hvac_to_mode:
            raise ValueError(f"Unsupported HVAC mode: {hvac_mode}")

        await self.coordinator.client.write_register(
            self.coordinator.register_to_address(self._power_reg),
            self._power_on_value,
        )
        await self.coordinator.client.write_register(
            self.coordinator.register_to_address(self._mode_reg),
            self._hvac_to_mode[hvac_mode],
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self) -> None:
        await self.coordinator.client.write_register(
            self.coordinator.register_to_address(self._power_reg),
            self._power_on_value,
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self) -> None:
        await self.coordinator.client.write_register(
            self.coordinator.register_to_address(self._power_reg),
            self._power_off_value,
        )
        await self.coordinator.async_request_refresh()


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data["haier_atw_ew11"][entry.entry_id]
    special_map = getattr(coordinator, "special", SPECIAL)
    if all(key in special_map for key in ("power", "mode", "zone1_sp")):
        async_add_entities([HaierAtwClimate(coordinator)])
    else:
        async_add_entities([])
