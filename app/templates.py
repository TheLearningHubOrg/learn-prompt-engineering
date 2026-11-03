"""Stage 2: strict prompt templates, XML-delimited few-shot prompts and example selection."""

from __future__ import annotations

import math
import re
import string
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

_FORMATTER = string.Formatter()
_WORD = re.compile(r"[a-z0-9]+")


class TemplateError(ValueError):
    """Raised for malformed templates and for missing or unexpected values."""


def xml_escape(value: str) -> str:
    """Escape the three characters that let data close or open a tag."""
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def wrap(tag: str, value: str) -> str:
    """Put ``value`` inside ``<tag>...</tag>`` after escaping it."""
    return f"<{tag}>\n{xml_escape(value)}\n</{tag}>"


class PromptTemplate:
    """A ``str.format`` template that refuses to render with missing or extra values.

    Literal braces (for example a JSON example inside the prompt) must be doubled:
    ``{{"severity": "SEV-1"}}`` renders as ``{"severity": "SEV-1"}``.
    """

    def __init__(self, text: str):
        self.text = text
        self.fields = self._parse(text)

    @staticmethod
    def _parse(text: str) -> tuple[str, ...]:
        names: list[str] = []
        try:
            parsed = list(_FORMATTER.parse(text))
        except ValueError as err:
            raise TemplateError(f"{err}; double literal braces as {{{{ and }}}}") from None
        for _literal, name, spec, conversion in parsed:
            if name is None:
                continue
            if name == "" or name.isdigit():
                raise TemplateError("positional placeholders like {} or {0} are not allowed; name them")
            if not name.isidentifier():
                raise TemplateError(f"placeholder {{{name}}} must be a plain name, not an expression")
            if spec or conversion:
                raise TemplateError(f"placeholder {{{name}}} must not use a format spec or conversion")
            if name not in names:
                names.append(name)
        return tuple(names)

    def render(self, *, escape: bool = True, **values: object) -> str:
        missing = [f for f in self.fields if f not in values]
        extra = sorted(set(values) - set(self.fields))
        if missing:
            raise TemplateError(f"missing values for: {', '.join(missing)}")
        if extra:
            raise TemplateError(f"unexpected values: {', '.join(extra)}")
        text_values = {k: xml_escape(str(v)) if escape else str(v) for k, v in values.items()}
        return self.text.format(**text_values)


@dataclass(frozen=True)
class Example:
    input: str
    output: str
    reasoning: str | None = None


class FewShotPrompt:
    """Instruction, delimited examples, then the live input, all escaped."""

    def __init__(self, instruction: str, examples: Sequence[Example]):
        if not instruction.strip():
            raise TemplateError("instruction must not be empty")
        self.instruction = instruction.strip()
        self.examples = list(examples)

    def render(self, query: str) -> str:
        parts = [wrap("instructions", self.instruction), "", "<examples>"]
        for ex in self.examples:
            parts.append("<example>")
            parts.append(f"<input>{xml_escape(ex.input)}</input>")
            if ex.reasoning:
                parts.append(f"<reasoning>{xml_escape(ex.reasoning)}</reasoning>")
            parts.append(f"<output>{xml_escape(ex.output)}</output>")
            parts.append("</example>")
        parts += ["</examples>", "", wrap("input", query)]
        return "\n".join(parts)


def _bag(text: str) -> Counter[str]:
    return Counter(_WORD.findall(text.lower()))


def cosine(a: str, b: str) -> float:
    """Bag-of-words cosine similarity. Swap in embeddings for production retrieval."""
    va, vb = _bag(a), _bag(b)
    dot = sum(va[w] * vb[w] for w in va.keys() & vb.keys())
    norm = math.sqrt(sum(v * v for v in va.values())) * math.sqrt(sum(v * v for v in vb.values()))
    return dot / norm if norm else 0.0


def select_examples(
    pool: Sequence[Example],
    query: str,
    k: int,
    *,
    balance_labels: bool = False,
) -> list[Example]:
    """Pick ``k`` examples for ``query`` and order them least-similar first.

    The most similar example ends up last, closest to the live input. With
    ``balance_labels`` the picks rotate across output labels so one class cannot
    dominate the prompt.
    """
    if k < 1:
        raise ValueError("k must be >= 1")
    scored = sorted(
        ((cosine(ex.input, query), idx, ex) for idx, ex in enumerate(pool)),
        key=lambda t: (-t[0], t[1]),
    )
    if not balance_labels:
        chosen = scored[:k]
    else:
        by_label: dict[str, list[tuple[float, int, Example]]] = {}
        for item in scored:
            by_label.setdefault(item[2].output, []).append(item)
        queues = sorted(by_label.values(), key=lambda q: (-q[0][0], q[0][1]))
        chosen = []
        while len(chosen) < k and any(queues):
            for queue in queues:
                if queue and len(chosen) < k:
                    chosen.append(queue.pop(0))
    chosen.sort(key=lambda t: (t[0], -t[1]))
    return [ex for _, _, ex in chosen]
