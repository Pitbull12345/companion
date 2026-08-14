class AudioError(RuntimeError):
    """An audio provider could not complete an operation."""


class VADError(AudioError):
    """Voice activity detection could not complete an operation."""


class STTError(AudioError):
    """Speech transcription could not complete an operation."""
