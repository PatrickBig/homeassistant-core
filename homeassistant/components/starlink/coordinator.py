"""Contains the shared Coordinator for Starlink systems."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging

from starlink_grpc import (
    AlertDict,
    ChannelContext,
    GrpcError,
    ObstructionDict,
    StatusDict,
    reboot,
    set_stow_state,
    status_data,
)

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util.timeout import asyncio_timeout

_LOGGER = logging.getLogger(__name__)


@dataclass
class StarlinkData:
    """Contains data pulled from the Starlink system."""

    status: StatusDict
    obstruction: ObstructionDict
    alert: AlertDict


class StarlinkUpdateCoordinator(DataUpdateCoordinator[StarlinkData]):
    """Coordinates updates between all Starlink sensors defined in this file."""

    def __init__(self, hass: HomeAssistant, name: str, url: str) -> None:
        """Initialize an UpdateCoordinator for a group of sensors."""
        self.channel_context = ChannelContext(target=url)

        super().__init__(
            hass,
            _LOGGER,
            name=name,
            update_interval=timedelta(seconds=5),
        )

    async def _async_update_data(self) -> StarlinkData:
        async with asyncio_timeout(4):
            try:
                status = await self.hass.async_add_executor_job(
                    status_data, self.channel_context
                )
                return StarlinkData(*status)
            except GrpcError as exc:
                raise UpdateFailed from exc

    async def async_stow_starlink(self, stow: bool):
        """Set whether Starlink system tied to this coordinator should be stowed."""
        async with asyncio_timeout(4):
            try:
                await self.hass.async_add_executor_job(
                    set_stow_state, not stow, self.channel_context
                )
            except GrpcError as exc:
                raise HomeAssistantError from exc

    async def async_reboot_starlink(self):
        """Reboot the Starlink system tied to this coordinator."""
        async with asyncio_timeout(4):
            try:
                await self.hass.async_add_executor_job(reboot, self.channel_context)
            except GrpcError as exc:
                raise HomeAssistantError from exc
