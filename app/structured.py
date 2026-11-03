"""Stage 4: system prompt blueprint, tagged output, JSON recovery and validate-and-repair."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from app.llm import ChatModel
from app.templates import xml_escape

_FENCE = re.compile(r"```(?:json|JSON)?\s*\n(.*?)\n?```", re.S)


@dataclass
class SystemPrompt:
    """The five blueprint sections, always rendered in the same order.

    Rendering is deterministic: the same inputs give byte-identical output, which is
    what prefix caching and prompt versioning both depend on.
    """

    role: str
    constraints: Sequence[str] = ()
    knowledge: Mapping[str, str] = field(default_factory=dict)
    tools: Mapping[str, str] = field(default_factory=dict)
    output: str = ""

    def render(self) -> str:
        if not self.role.strip():
            raise ValueError("role must not be empty")
        parts = [f"<role>\n{self.role.strip()}\n</role>"]
        if self.constraints:
            rules = "\n".join(f"- {rule.strip()}" for rule in self.constraints)
            parts.append(f"<hard_constraints>\n{rules}\n</hard_constraints>")
        if self.knowledge:
            docs = "\n".join(
                f'<document name="{xml_escape(name)}">\n{xml_escape(text.strip())}\n</document>'
                for name, text in self.knowledge.items()
            )
            parts.append(f"<knowledge>\n{docs}\n</knowledge>")
        if self.tools:
            lines = "\n".join(f"- {name}: {desc.strip()}" for name, desc in self.tools.items())
            parts.append(f"<tools>\n{lines}\n</tools>")
        if self.output.strip():
            parts.append(f"<output_format>\n{self.output.strip()}\n</output_format>")
        return "\n\n".join(parts)

    def fingerprint(self) -> str:
        """Short content hash to log with every request, so outputs trace back to a prompt."""
        return hashlib.sha256(self.render().encode()).hexdigest()[:12]


def extract_tag(text: str, tag: str) -> str | None:
    """Content of the last ``<tag>...</tag>`` block, stripped, or ``None``."""
    found = re.findall(rf"<{re.escape(tag)}>\s*(.*?)\s*</{re.escape(tag)}>", text, re.S)
    return found[-1] if found else None


def extract_json(text: str) -> Any:
    """Recover the first JSON value from model text.

    Handles a bare JSON reply, a fenced code block, and JSON surrounded by prose.
    Raises ``ValueError`` when nothing parses. Use this only for providers or models
    without schema-constrained decoding.
    """
    candidates = [text.strip()]
    candidates += [m.strip() for m in _FENCE.findall(text)]
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    decoder = json.JSONDecoder()
    for match in re.finditer(r"[{\[]", text):
        try:
            value, _end = decoder.raw_decode(text, match.start())
            return value
        except json.JSONDecodeError:
            continue
    raise ValueError("no JSON value found in model output")


def strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """JSON Schema for ``model`` in the strict subset that schema-enforcing APIs accept.

    Every object gets ``additionalProperties: false`` and lists all its properties
    as required. Optional fields stay nullable (``anyOf`` with ``null``), so "absent"
    is expressed as ``null`` rather than a missing key.
    """
    schema = copy.deepcopy(model.model_json_schema())

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"])
                for prop in node["properties"].values():
                    prop.pop("default", None)
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(schema)
    return schema


def validation_summary(err: ValidationError) -> list[str]:
    """One ``path: message`` line per error, short enough to send back to the model."""
    return [f"{'.'.join(str(p) for p in e['loc']) or '<root>'}: {e['msg']}" for e in err.errors()]


@dataclass
class ParseResult[T: BaseModel]:
    value: T | None
    attempts: int
    errors: list[list[str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.value is not None


REPAIR_SUFFIX = """

<previous_output>
{output}
</previous_output>
<validation_errors>
{errors}
</validation_errors>
Your previous output did not match the schema. Return only the corrected JSON object."""


def parse_with_repair[T: BaseModel](
    model: ChatModel, prompt: str, schema: type[T], max_attempts: int = 2
) -> ParseResult[T]:
    """Call the model, validate against ``schema`` and retry with the errors attached.

    The retry sends the original prompt plus the bad output and the validation errors,
    which fixes most formatting slips in one extra call. ``max_attempts`` bounds cost.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    result: ParseResult[T] = ParseResult(None, 0)
    current = prompt
    for _ in range(max_attempts):
        result.attempts += 1
        output = model.complete(current)
        try:
            result.value = schema.model_validate(extract_json(output))
            return result
        except ValueError as err:  # ValidationError subclasses ValueError
            errors = validation_summary(err) if isinstance(err, ValidationError) else [str(err)]
            result.errors.append(errors)
            current = prompt + REPAIR_SUFFIX.format(output=xml_escape(output), errors="\n".join(errors))
    return result
