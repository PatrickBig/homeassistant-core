"""Support for Wyoming wake-word-detection services."""
import asyncio
from collections.abc import AsyncIterable
import logging

from wyoming.audio import AudioChunk, AudioStart
from wyoming.client import AsyncTcpClient
from wyoming.wake import Detection

from homeassistant.components import wake
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .data import WyomingService
from .error import WyomingError

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Wyoming wake-word-detection."""
    service: WyomingService = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities(
        [
            WyomingWakeProvider(config_entry, service),
        ]
    )


class WyomingWakeProvider(wake.WakeWordDetectionEntity):
    """Wyoming wake-word-detection provider."""

    def __init__(
        self,
        config_entry: ConfigEntry,
        service: WyomingService,
    ) -> None:
        """Set up provider."""
        self.service = service
        wake_service = service.info.wake[0]

        self._supported_wake_words = [
            wake.WakeWord(ww_id=ww.name, name=ww.name) for ww in wake_service.models
        ]
        self._attr_name = wake_service.name
        self._attr_unique_id = f"{config_entry.entry_id}-stt"

    @property
    def supported_wake_words(self) -> list[wake.WakeWord]:
        """Return a list of supported wake words."""
        return self._supported_wake_words

    async def async_process_audio_stream(
        self, stream: AsyncIterable[tuple[bytes, int]]
    ) -> wake.DetectionResult | None:
        """Try to detect one or more wake words in an audio stream.

        Audio must be 16Khz sample rate with 16-bit mono PCM samples.
        """

        async def next_chunk():
            """Get the next chunk from audio stream."""
            async for chunk_bytes in stream:
                return chunk_bytes

        try:
            async with AsyncTcpClient(self.service.host, self.service.port) as client:
                await client.write_event(
                    AudioStart(
                        rate=16000,
                        width=2,
                        channels=1,
                    ).event(),
                )

                # Read audio and wake events in "parallel"
                audio_task = asyncio.create_task(next_chunk())
                wake_task = asyncio.create_task(client.read_event())
                pending = {audio_task, wake_task}

                try:
                    while True:
                        done, pending = await asyncio.wait(
                            pending, return_when=asyncio.FIRST_COMPLETED
                        )

                        if audio_task in done:
                            # Forward audio to wake service
                            chunk_bytes, chunk_timestamp = audio_task.result()
                            chunk = AudioChunk(
                                rate=16000,
                                width=2,
                                channels=1,
                                audio=chunk_bytes,
                                timestamp=chunk_timestamp,
                            )
                            await client.write_event(chunk.event())

                            # Next chunk
                            audio_task = asyncio.create_task(next_chunk())
                            pending.add(audio_task)

                        if wake_task in done:
                            event = wake_task.result()
                            if event is None:
                                _LOGGER.debug("Connection lost")
                                break

                            if Detection.is_type(event.type):
                                # Successful detection
                                detection = Detection.from_event(event)
                                _LOGGER.info(detection)
                                return wake.DetectionResult(
                                    ww_id=detection.name, timestamp=detection.timestamp
                                )

                            # Next event
                            wake_task = asyncio.create_task(client.read_event())
                            pending.add(wake_task)
                finally:
                    # Clean up
                    for task in pending:
                        task.cancel()

        except (OSError, WyomingError) as err:
            _LOGGER.exception("Error processing audio stream: %s", err)

        return None
