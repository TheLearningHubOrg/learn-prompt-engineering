"""Masterclasses M3-M5: citation checks, cache-prefix analysis and context compaction."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from app.llm import ChatModel
from app.messages import Message
from app.templates import xml_escape

_CITATION = re.compile(r'<citation\s+doc_id="([^"]+)"\s*>(.*?)</citation>', re.S)


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


@dataclass(frozen=True)
class CitationCheck:
    doc_id: str
    quote: str
    found: bool


def verify_citations(answer: str, documents: Mapping[str, str]) -> list[CitationCheck]:
    """Check every ``<citation doc_id="...">quote</citation>`` against its source.

    Whitespace and case are normalised; everything else must match exactly. A quote
    that is not in the cited document is a fabrication, whatever the analysis says.
    """
    checks = []
    for doc_id, quote in _CITATION.findall(answer):
        source = documents.get(doc_id)
        found = source is not None and bool(quote.strip()) and _squash(quote) in _squash(source)
        checks.append(CitationCheck(doc_id, quote.strip(), found))
    return checks


def documents_block(documents: Mapping[str, str]) -> str:
    """One tagged, escaped block per document, with an index first so the model can navigate."""
    index = "\n".join(f"- {doc_id} ({len(text.split())} words)" for doc_id, text in documents.items())
    docs = "\n".join(
        f'<document id="{doc_id}">\n{xml_escape(text.strip())}\n</document>' for doc_id, text in documents.items()
    )
    return f"<index>\n{index}\n</index>\n<documents>\n{docs}\n</documents>"


def shared_prefix(a: Sequence[str], b: Sequence[str]) -> int:
    """Number of leading tokens two prompts share: the most a prefix cache can reuse."""
    n = 0
    for x, y in zip(a, b, strict=False):
        if x != y:
            break
        n += 1
    return n


def first_divergence(a: str, b: str, context: int = 20) -> str | None:
    """Text around the first character where two prompts differ, or ``None`` if equal."""
    n = shared_prefix(a, b)
    if n == len(a) == len(b):
        return None
    return f"...{a[max(0, n - context): n]}[{a[n: n + context]!r} vs {b[n: n + context]!r}]"


SUMMARY_PROMPT = """Summarise the conversation below for a future turn of the same task.
Keep: decisions made, open questions, file names, identifiers and numbers, user preferences.
Drop: greetings, repeated explanations, tool output that was already acted on.

<conversation>
{transcript}
</conversation>"""


def compact(
    turns: Sequence[Message],
    model: ChatModel,
    *,
    keep_last: int = 4,
    budget: int,
    count: Callable[[str], int],
) -> list[Message]:
    """Replace old turns with a model-written summary once the history exceeds ``budget``.

    The most recent ``keep_last`` turns stay verbatim because the next reply depends
    on them most. The summary is a user turn, so alternation stays valid when the
    kept tail starts with an assistant turn.
    """
    if sum(count(t.content) for t in turns) <= budget or len(turns) <= keep_last:
        return list(turns)
    split = len(turns) - keep_last
    if turns[split].role == "user":
        split -= 1  # keep the tail starting on an assistant turn so the summary can precede it
    old, tail = turns[:split], turns[split:]
    if not old:
        return list(turns)
    transcript = "\n".join(f"{t.role}: {xml_escape(t.content)}" for t in old)
    summary = model.complete(SUMMARY_PROMPT.format(transcript=transcript)).strip()
    return [Message("user", f"<summary_of_earlier_turns>\n{summary}\n</summary_of_earlier_turns>"), *tail]
