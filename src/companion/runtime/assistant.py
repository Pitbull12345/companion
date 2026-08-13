from dataclasses import dataclass

from companion.agent.context import ContextBuilder
from companion.agent.conversation import ConversationManager
from companion.audio.interfaces import AudioSource, STTProvider, VADProvider
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
        conversation: ConversationManager,
        turn_controller: TurnController,
    ) -> None:
        self._audio_source = audio_source
        self._vad = vad
        self._stt = stt
        self._context_builder = context_builder
        self._llm = llm
        self._tts = tts
        self._conversation = conversation
        self._turn_controller = turn_controller

    async def run_turn(self) -> TurnResult:
        utterance = await self._vad.capture_utterance(self._audio_source)
        self._turn_controller.transition_to(TurnState.TRANSCRIBING)
        transcript = await self._stt.transcribe(utterance)
        self._turn_controller.transition_to(TurnState.THINKING)
        context = await self._context_builder.build(transcript)
        response = await self._llm.generate(context)
        self._turn_controller.transition_to(TurnState.SPEAKING)
        await self._tts.speak(response)
        self._conversation.add_turn(transcript, response)
        self._turn_controller.transition_to(TurnState.LISTENING)
        return TurnResult(transcript=transcript, response=response)
