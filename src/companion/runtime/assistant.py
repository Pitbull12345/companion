from dataclasses import dataclass

from companion.agent.context import ContextBuilder
from companion.agent.conversation import ConversationManager
from companion.events import (
    ApplicationError,
    ApplicationEvent,
    ApplicationEventObserver,
    ResponseReady,
    SpeechFinished,
    SpeechStarted,
    TranscriptReady,
)
from companion.audio.interfaces import AudioOutput, AudioSource, STTProvider, VADProvider
from companion.llm.router import LLMRouter
from companion.runtime.turn import TurnController, TurnState
from companion.tts.interfaces import TTSProvider


@dataclass(frozen=True, slots=True)
class TurnResult:
    transcript: str
    response: str


class AssistantRuntime:
    def __init__(
        self,
        audio_source: AudioSource,
        vad: VADProvider,
        stt: STTProvider,
        context_builder: ContextBuilder,
        llm: LLMRouter,
        tts: TTSProvider,
        audio_output: AudioOutput,
        conversation: ConversationManager,
        turn_controller: TurnController,
        event_observer: ApplicationEventObserver | None = None,
    ) -> None:
        self._audio_source = audio_source
        self._vad = vad
        self._stt = stt
        self._context_builder = context_builder
        self._llm = llm
        self._tts = tts
        self._audio_output = audio_output
        self._conversation = conversation
        self._turn_controller = turn_controller
        self._event_observer = event_observer

    def _publish(self, event: ApplicationEvent) -> None:
        if self._event_observer is not None:
            self._event_observer.publish(event)

    def _report_error(self, phase: str) -> None:
        self._publish(ApplicationError(phase, f"{phase} failed"))

    async def run_turn(self) -> TurnResult:
        try:
            utterance = await self._vad.capture_utterance(self._audio_source)
        except Exception:
            self._report_error("listening")
            raise
        self._turn_controller.transition_to(TurnState.TRANSCRIBING)
        try:
            transcript = await self._stt.transcribe(utterance)
        except Exception:
            self._report_error("transcription")
            raise
        self._publish(TranscriptReady(transcript))
        self._turn_controller.transition_to(TurnState.THINKING)
        try:
            context = await self._context_builder.build(transcript)
            response = await self._llm.generate(context)
        except Exception:
            self._report_error("response generation")
            raise
        self._publish(ResponseReady(response))
        self._turn_controller.transition_to(TurnState.SPEAKING)
        try:
            speech = await self._tts.synthesize(response)
        except Exception:
            self._report_error("speech synthesis")
            raise
        self._publish(SpeechStarted())
        try:
            await self._audio_output.play(speech)
        except Exception:
            self._report_error("speech playback")
            raise
        self._publish(SpeechFinished())
        self._conversation.add_turn(transcript, response)
        self._turn_controller.transition_to(TurnState.LISTENING)
        return TurnResult(transcript=transcript, response=response)
