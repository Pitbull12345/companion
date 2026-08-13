class MemoryManager:
    """Boundary for selecting Companion-owned memories for a model context."""

    async def relevant_memories(self, query: str) -> tuple[str, ...]:
        return ()
