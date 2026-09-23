"""Platform for number integration."""
from __future__ import annotations

import logging
from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Haier ATW number entities based on config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    entities = []
    for point in coordinator.profile.get("points", []):
        # Создаем ползунок только для параметров записи (rw == "W")
        if point.get("rw") == "W" and "scale_write" in point:
            entities.append(HaierNumberEntity(coordinator, entry, point))

    async_add_entities(entities)


class HaierNumberEntity(CoordinatorEntity, NumberEntity):
    """Representation of a Haier ATW Number entity."""

    def __init__(self, coordinator, entry, point: dict) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator)
        self._point = point
        self._entry = entry

        self._register = point["register"]
        self._ha_address = point.get("ha_address", self._register - 40001)
        self._scale_read = float(point.get("scale_read", 1.0))
        self._scale_write = float(point.get("scale_write", 1.0))

        # Уникальный ID на основе регистра
        self._attr_unique_id = f"{entry.entry_id}_number_{self._register}"
        self._attr_name = point.get("function", f"Register {self._register}")

        # Настройка параметров ползунка
        self._attr_native_min_value = float(point.get("min", 0))
        self._attr_native_max_value = float(point.get("max", 100))
        self._attr_native_step = float(point.get("step", 0.5))
        self._attr_native_unit_of_measurement = point.get("unit")
        self._attr_mode = NumberMode.BOX

    @property
    def native_value(self) -> float | None:
        """Return current value."""
        # Проверяем оба варианта ключей в coordinator.data (по register и по ha_address)
        raw_val = self.coordinator.data.get(self._register)
        if raw_val is None:
            raw_val = self.coordinator.data.get(self._ha_address)

        if raw_val is None:
            return None

        return round(float(raw_val) * self._scale_read, 2)

    async def async_set_native_value(self, value: float) -> None:
        """Set new value to Modbus register."""
        raw_value = int(round(value * self._scale_write))

        _LOGGER.debug(
            "Setting %s (register %s, ha_address %s) to raw value %s",
            self.entity_id,
            self._register,
            self._ha_address,
            raw_value,
        )

        # Вызов метода записи в координаторе с фоллбэком на разное наименование методов
        if hasattr(self.coordinator, "async_write_register"):
            try:
                await self.coordinator.async_write_register(self._register, raw_value)
            except TypeError:
                await self.coordinator.async_write_register(
                    address=self._ha_address, value=raw_value
                )
        elif hasattr(self.coordinator, "async_write"):
            await self.coordinator.async_write(self._register, raw_value)
        elif hasattr(self.coordinator, "client") and hasattr(
            self.coordinator.client, "write_register"
        ):
            await self.coordinator.client.write_register(
                self._ha_address, raw_value
            )

        await self.coordinator.async_request_refresh()
