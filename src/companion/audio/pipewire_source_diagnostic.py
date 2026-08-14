"""Optional manual diagnostic for the default PipeWire microphone."""

import argparse
import asyncio

from companion.audio.pipewire_source import PipeWireAudioSource


async def _capture(frame_count: int) -> None:
    source = PipeWireAudioSource()
    try:
        for index in range(frame_count):
            frame = await source.read_frame()
            print(
                f"frame {index + 1}: {len(frame.data)} bytes, "
                f"{frame.sample_rate} Hz, {frame.channels} channel, "
                f"{frame.sample_width}-byte samples"
            )
    finally:
        await source.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture frames from the system default PipeWire microphone."
    )
    parser.add_argument("--frames", type=int, default=10)
    arguments = parser.parse_args()
    if arguments.frames < 1:
        parser.error("--frames must be at least 1")
    asyncio.run(_capture(arguments.frames))


if __name__ == "__main__":
    main()
