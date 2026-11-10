"""Customize here. Bind identity in a closure; never accept owner/user_id from the model."""

from langchain_core.tools import tool


def build_tools(storage, owner):
    @tool
    async def memory_remember(key: str, value: str) -> str:
        """Save or update a concise fact ONLY when the user asks you to remember it."""
        return storage.remember(owner, key, value)

    @tool
    async def memory_search(query: str = "", offset: int = 0) -> dict:
        """Search saved facts for this account, or page through them using next_offset."""
        return storage.memory_page(owner, query, offset)

    @tool
    async def memory_forget(key: str) -> str:
        """Forget one saved fact when the user asks. Conversation transcripts are separate."""
        return storage.forget(owner, key)

    return [memory_remember, memory_search, memory_forget]
