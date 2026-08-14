"""Optional manual local Piper-to-speaker diagnostic."""

import argparse
import asyncio
import sys

from companion.audio.pipewire_output import PipeWireAudioOutput
from companion.audio.sounddevice_output import SoundDeviceAudioOutput
from companion.tts.piper import PiperTTSProvider


async def _run(model_path: str, config_path: str | None, text: str) -> None:
    tts = PiperTTSProvider(model_path, config_path=config_path)
    output = (
        PipeWireAudioOutput()
        if sys.platform.startswith("linux")
        else SoundDeviceAudioOutput()
    )
    await output.play(await tts.synthesize(text))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Synthesize with an installed local Piper voice and play it."
    )
    parser.add_argument("model_path")
    parser.add_argument("text")
    parser.add_argument("--config-path")
    arguments = parser.parse_args()
    asyncio.run(_run(arguments.model_path, arguments.config_path, arguments.text))


if __name__ == "__main__":
    main()
