import asyncio
from collections.abc import Sequence

import pytest

from companion.agent.context import ContextBuilder
from companion.agent.conversation import ConversationManager
from companion.agent.messages import Message
from companion.audio.interfaces import (
    AudioClip,
    AudioFrame,
    AudioSegment,
    AudioSource,
)
from companion.llm.router import LLMRouter
from companion.memory.manager import MemoryManager
from companion.runtime.assistant import AssistantRuntime, TurnResult
from companion.runtime.interactive import InteractiveTurnLoop, TurnRuntime
from companion.runtime.turn import TurnController, TurnState


class FakeRuntime:
    def __init__(self, results: Sequence[TurnResult | Exception]) -> None:
        self._results = iter(results)
        self.calls = 0
        self.task_ids: set[int] = set()

    async def run_turn(self) -> TurnResult:
        self.calls += 1
        task = asyncio.current_task()
        assert task is not None
        self.task_ids.add(id(task))
        result = next(self._results)
        if isinstance(result, Exception):
            raise result
        return result


class FakeResource:
    def __init__(self, failure: Exception | None = None) -> None:
        self.close_calls = 0
        self.failure = failure

    async def close(self) -> None:
        self.close_calls += 1
        if self.failure is not None:
            raise self.failure


def test_repeated_turns_reuse_runtime_stop_without_extra_turn_and_cleanup() -> None:
    async def exercise() -> None:
        results = [TurnResult("one", "first"), TurnResult("two", "second")]
        runtime = FakeRuntime(results)
        resource = FakeResource()
        completed: list[TurnResult] = []
        listening_calls = 0
        loop: InteractiveTurnLoop

        def listening() -> None:
            nonlocal listening_calls
            listening_calls += 1

        def completed_turn(result: TurnResult) -> None:
            completed.append(result)
            if len(completed) == 2:
                loop.request_stop()

        loop = InteractiveTurnLoop(
            runtime,
            resources=(resource,),
            on_listening=listening,
            on_turn_completed=completed_turn,
        )
        await loop.run()
        await loop.close()

        assert runtime.calls == 2
        assert listening_calls == 2
        assert completed == results
        assert resource.close_calls == 1

    asyncio.run(exercise())


def test_runtime_failure_is_fail_fast_and_cleanup_is_idempotent() -> None:
    async def exercise() -> None:
        failure = RuntimeError("turn failed")
        runtime = FakeRuntime([TurnResult("one", "first"), failure])
        resource = FakeResource()
        loop = InteractiveTurnLoop(runtime, resources=(resource,))

        with pytest.raises(RuntimeError, match="turn failed") as raised:
            await loop.run()
        assert raised.value is failure
        assert runtime.calls == 2
        assert resource.close_calls == 1

        await loop.close()
        assert resource.close_calls == 1

    asyncio.run(exercise())


def test_turn_failure_is_not_masked_by_cleanup_failure() -> None:
    async def exercise() -> None:
        turn_failure = RuntimeError("primary turn failure")
        loop = InteractiveTurnLoop(
            FakeRuntime([turn_failure]),
            resources=(FakeResource(RuntimeError("cleanup failure")),),
        )

        with pytest.raises(RuntimeError, match="primary turn failure") as raised:
            await loop.run()
        assert raised.value is turn_failure

    asyncio.run(exercise())


def test_cancellation_propagates_after_cleanup() -> None:
    class BlockingRuntime:
        def __init__(self) -> None:
            self.started = asyncio.Event()

        async def run_turn(self) -> TurnResult:
            self.started.set()
            await asyncio.Event().wait()

    async def exercise() -> None:
        runtime = BlockingRuntime()
        resource = FakeResource()
        loop = InteractiveTurnLoop(runtime, resources=(resource,))
        running = asyncio.create_task(loop.run())
        await runtime.started.wait()
        running.cancel()

        with pytest.raises(asyncio.CancelledError):
            await running
        assert resource.close_calls == 1

    asyncio.run(exercise())


def test_bounded_many_turn_simulation_accumulates_no_results_or_tasks() -> None:
    class ConversationRuntime:
        def __init__(self, conversation: ConversationManager) -> None:
            self.conversation = conversation
            self.calls = 0
            self.task_ids: set[int] = set()

        async def run_turn(self) -> TurnResult:
            task = asyncio.current_task()
            assert task is not None
            self.task_ids.add(id(task))
            self.calls += 1
            result = TurnResult(f"user {self.calls}", f"assistant {self.calls}")
            self.conversation.add_turn(result.transcript, result.response)
            return result

    async def exercise() -> None:
        conversation = ConversationManager(history_limit=3)
        runtime = ConversationRuntime(conversation)
        resource = FakeResource()
        loop: InteractiveTurnLoop

        def stop_at_limit(result: TurnResult) -> None:
            del result
            if runtime.calls == 100:
                loop.request_stop()

        loop = InteractiveTurnLoop(
            runtime,
            resources=(resource,),
            on_turn_completed=stop_at_limit,
        )
        await loop.run()

        assert runtime.calls == 100
        assert len(runtime.task_ids) == 1
        assert len(conversation.history) == 6
        assert not hasattr(loop, "results")
        assert resource.close_calls == 1

    asyncio.run(exercise())


def test_loop_accepts_runtime_protocol_without_concrete_runtime() -> None:
    async def consume(runtime: TurnRuntime) -> TurnResult:
        return await runtime.run_turn()

    async def exercise() -> None:
        result = TurnResult("contract", "works")
        assert await consume(FakeRuntime([result])) == result

    asyncio.run(exercise())


def test_multiple_real_runtime_turns_preserve_conversation_and_listening_state() -> None:
    class ClosingAudioSource:
        def __init__(self) -> None:
            self.frames = [AudioFrame(b"\x01\x00"), AudioFrame(b"\x02\x00")]
            self.close_calls = 0

        async def read_frame(self) -> AudioFrame:
            return self.frames.pop(0)

        async def close(self) -> None:
            self.close_calls += 1

    class FakeVAD:
        async def capture_utterance(self, source: AudioSource) -> AudioSegment:
            return AudioSegment((await source.read_frame(),))

    class FakeSTT:
        async def transcribe(self, audio: AudioSegment) -> str:
            return f"question {int.from_bytes(audio.frames[0].data, 'little')}"

    class HistoryAwareLLM:
        def __init__(self) -> None:
            self.contexts: list[tuple[Message, ...]] = []

        async def generate(self, messages: Sequence[Message]) -> str:
            self.contexts.append(tuple(messages))
            return f"answer {len(self.contexts)}"

    class FakeTTS:
        async def synthesize(self, text: str) -> AudioClip:
            del text
            return AudioClip(b"\x00\x00", 22_050, 1, 2)

    class FakeOutput:
        async def play(self, audio: AudioClip) -> None:
            del audio

    async def exercise() -> None:
        source = ClosingAudioSource()
        conversation = ConversationManager()
        llm = HistoryAwareLLM()
        turns = TurnController()
        runtime = AssistantRuntime(
            audio_source=source,
            vad=FakeVAD(),
            stt=FakeSTT(),
            context_builder=ContextBuilder("system", conversation, MemoryManager()),
            llm=LLMRouter(llm),
            tts=FakeTTS(),
            audio_output=FakeOutput(),
            conversation=conversation,
            turn_controller=turns,
        )
        completed = 0
        loop: InteractiveTurnLoop

        def stop_after_two(result: TurnResult) -> None:
            nonlocal completed
            del result
            completed += 1
            assert turns.state is TurnState.LISTENING
            if completed == 2:
                loop.request_stop()

        loop = InteractiveTurnLoop(
            runtime,
            resources=(source,),
            on_turn_completed=stop_after_two,
        )
        await loop.run()

        assert len(llm.contexts) == 2
        assert len(llm.contexts[1]) > len(llm.contexts[0])
        assert len(conversation.history) == 4
        assert turns.state is TurnState.LISTENING
        assert source.close_calls == 1

    asyncio.run(exercise())
