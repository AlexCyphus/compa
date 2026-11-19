"""Saves words the learner asks to keep as cloze sentences in their Clozemaster collection.

Uses the Clozemaster connector of the learner's claude.ai account, so this one Claude run loads claude.ai connectors
(a few seconds) and may only call the Clozemaster tools.
"""
import asyncio
import json
import time
from dataclasses import dataclass

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

from compa.brain import _final_text, _parse_json
from compa.settings import Profile

CLOZEMASTER_TOOLS = [f"mcp__claude_ai_Clozemaster__{name}"
                     for name in ("list_language_pairings", "list_collections", "add_sentences")]
CONNECT_TIMEOUT_SECONDS = 20


@dataclass(frozen=True)
class SaveResult:
    collection: str
    saved: list[str]
    failed: list[str]


class Clozemaster:
    def __init__(self, profile: Profile):
        self.profile = profile

    async def save(self, words: list[str], partner_line: str, learner_line: str) -> SaveResult:
        options = ClaudeAgentOptions(
            model=self.profile.corrector_model, system_prompt=self._instructions(),
            tools=CLOZEMASTER_TOOLS, allowed_tools=CLOZEMASTER_TOOLS, setting_sources=[], skills=[], plugins=[],
            thinking={"type": "disabled"}, env={"ENABLE_CLAUDEAI_MCP_SERVERS": "true"})
        async with ClaudeSDKClient(options) as client:
            await _until_clozemaster_connected(client)
            await client.query(f"""Words to save: {json.dumps(words, ensure_ascii=False)}
Conversation they came up in:
Partner: {partner_line}
Learner: {learner_line}""")
            answer = _parse_json(await _final_text(client), "{") or {}
        return SaveResult(self.profile.clozemaster_collection, answer.get("saved", []), answer.get("failed", words))

    def _instructions(self) -> str:
        profile = self.profile
        return f"""You save words a {profile.level}-level learner of {profile.language_name} ({profile.variety}) \
wants to learn into their Clozemaster collection "{profile.clozemaster_collection}".

1. list_language_pairings: take the pairing whose targetLanguage is {profile.language_name} and whose baseLanguage \
is {profile.native_language}.
2. list_collections: take the collection named "{profile.clozemaster_collection}".
3. add_sentences: one sentence per word. Write a natural, everyday sentence in {profile.variety} that uses the word \
the way it came up in the conversation, with exactly that word wrapped in {{{{double curly braces}}}} (for a phrase, \
wrap its key word); "translation" is the whole sentence in {profile.native_language}.

Your only tools are the Clozemaster ones: never try to read files or look for other instructions, everything you \
need is here. When done, answer with JSON only: {{"saved": ["<sentence text as saved>", ...], "failed": ["<word>: <why>", ...]}}"""


async def _until_clozemaster_connected(client: ClaudeSDKClient) -> None:
    """claude.ai connectors connect a moment after the CLI starts; asking before that finds no Clozemaster tools."""
    deadline = time.monotonic() + CONNECT_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        servers = (await client.get_mcp_status())["mcpServers"]
        if any("Clozemaster" in server["name"] and server["status"] != "pending" for server in servers):
            return
        await asyncio.sleep(0.2)
