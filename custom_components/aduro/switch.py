class AduroAutoResumeAfterWoodSwitch(AduroSwitchBase):
    """Switch to enable/disable automatic resume after wood mode."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, entry, "auto_resume_after_wood_mode", "auto_resume_after_wood_mode")
        self._attr_icon = "mdi:restart"

    @property
    def is_on(self) -> bool:
        """Return true if auto-resume is enabled."""
        # Access internal coordinator state
        return self.coordinator._auto_resume_after_wood

    @property
    def icon(self) -> str:
        """Return icon based on state."""
        if self.is_on:
            return "mdi:replay"
        return "mdi:pause"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        attrs = {
            "in_wood_mode": self.coordinator._was_in_wood_mode,
        }
        
        # Add saved settings if available
        if self.coordinator._pre_wood_mode_operation_mode is not None:
            mode_names = {0: "Heat Level", 1: "Temperature", 2: "Wood"}
            attrs["saved_mode"] = mode_names.get(
                self.coordinator._pre_wood_mode_operation_mode, 
                "Unknown"
            )
            
        if self.coordinator._pre_wood_mode_heatlevel is not None:
            attrs["saved_heatlevel"] = self.coordinator._pre_wood_mode_heatlevel
            
        if self.coordinator._pre_wood_mode_temperature is not None:
            attrs["saved_temperature"] = self.coordinator._pre_wood_mode_temperature
        
        return attrs

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable auto-resume after wood mode."""
        _LOGGER.info("Switch: Enabling auto-resume after wood mode")
        self.coordinator.set_auto_resume_after_wood(True)
        await self.coordinator.async_save_pellet_data()
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable auto-resume after wood mode."""
        _LOGGER.info("Switch: Disabling auto-resume after wood mode")
        self.coordinator.set_auto_resume_after_wood(False)
        await self.coordinator.async_save_pellet_data()
        await self.coordinator.async_request_refresh()
