"""Stage 3: answer extraction, self-consistency voting, ReAct loops and prompt chains."""

from __future__ import annotations

import ast
import operator
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from app.llm import ChatModel
from app.templates import PromptTemplate

_ANSWER_TAG = re.compile(r"<answer>\s*(.*?)\s*</answer>", re.S | re.I)
_ANSWER_LINE = re.compile(r"^\s*(?:final answer|answer)\s*[:=]\s*(.+?)\s*$", re.I | re.M)
_NUMBER = re.compile(r"-?[\d,]+(?:\.\d+)?")


def normalise_answer(raw: str) -> str:
    text = re.sub(r"\s+", " ", raw).strip().rstrip(".").strip()
    if _NUMBER.fullmatch(text):
        text = text.replace(",", "")
    return text


def extract_answer(completion: str) -> str | None:
    """Pull the final answer out of a reasoning trace.

    Prefers the last ``<answer>...</answer>`` block, then the last ``Answer:`` line.
    Returns ``None`` when the model never committed to an answer.
    """
    tags = _ANSWER_TAG.findall(completion)
    if tags:
        return normalise_answer(tags[-1])
    lines = _ANSWER_LINE.findall(completion)
    if lines:
        return normalise_answer(lines[-1])
    return None


@dataclass(frozen=True)
class Vote:
    answer: str | None
    votes: int
    total: int
    parsed: int

    @property
    def confidence(self) -> float:
        return self.votes / self.total if self.total else 0.0


def majority_vote(completions: Iterable[str]) -> Vote:
    """Self-consistency aggregation. Case-insensitive; ties go to the answer seen first."""
    counts: dict[str, int] = {}
    first_form: dict[str, str] = {}
    total = parsed = 0
    for completion in completions:
        total += 1
        answer = extract_answer(completion)
        if answer is None:
            continue
        parsed += 1
        key = answer.casefold()
        first_form.setdefault(key, answer)
        counts[key] = counts.get(key, 0) + 1
    if not counts:
        return Vote(None, 0, total, 0)
    best = max(counts, key=lambda key: counts[key])  # max() keeps the first of equal keys
    return Vote(first_form[best], counts[best], total, parsed)


def self_consistency(model: ChatModel, prompt: str, n: int = 5) -> Vote:
    """Sample ``n`` reasoning paths and keep the most common final answer.

    Only useful when the model samples with temperature > 0; at temperature 0 all
    paths are (nearly) identical and you pay ``n`` times for one answer.
    """
    if n < 1:
        raise ValueError("n must be >= 1")
    return majority_vote(model.complete(prompt) for _ in range(n))


# ---------------------------------------------------------------- ReAct

_ACTION = re.compile(r"^Action:\s*([A-Za-z_]\w*)\[(.*)\]\s*$", re.M)
_FINAL = re.compile(r"^Final Answer:\s*(.+?)\s*$", re.M)

REACT_HEADER = """Answer the question by alternating Thought, Action and Observation lines.
Call one tool per step, written exactly as: Action: tool_name[input]
When you know the answer, write: Final Answer: <answer>

Tools:
{tools}

Question: {question}
"""

Tool = Callable[[str], str]


@dataclass
class Step:
    text: str
    tool: str | None = None
    tool_input: str | None = None
    observation: str | None = None


@dataclass
class ReactResult:
    answer: str | None
    stop_reason: Literal["answer", "max_steps", "no_action"]
    steps: list[Step] = field(default_factory=list)


def react(
    model: ChatModel,
    question: str,
    tools: Mapping[str, Tool],
    descriptions: Mapping[str, str] | None = None,
    max_steps: int = 5,
) -> ReactResult:
    """Run a Thought/Action/Observation loop with a hard step limit."""
    descriptions = descriptions or {}
    tool_lines = "\n".join(f"- {name}: {descriptions.get(name, 'no description')}" for name in tools)
    transcript = REACT_HEADER.format(tools=tool_lines, question=question)
    steps: list[Step] = []
    for _ in range(max_steps):
        reply = model.complete(transcript + "Thought:")
        reply = reply.split("\nObservation:")[0]  # never trust an observation the model wrote itself
        final = _FINAL.search(reply)
        action = _ACTION.search(reply)
        if final and (action is None or final.start() < action.start()):
            steps.append(Step(reply))
            return ReactResult(normalise_answer(final.group(1)), "answer", steps)
        if action is None:
            steps.append(Step(reply))
            return ReactResult(None, "no_action", steps)
        name, arg = action.group(1), action.group(2).strip()
        tool = tools.get(name)
        if tool is None:
            observation = f"error: unknown tool '{name}'. Available: {', '.join(tools)}"
        else:
            try:
                observation = tool(arg)
            except Exception as err:  # noqa: BLE001 - tool errors go back to the model
                observation = f"error: {err}"
        steps.append(Step(reply[: action.end()], name, arg, observation))
        transcript += f"Thought:{reply[: action.end()]}\nObservation: {observation}\n"
    return ReactResult(None, "max_steps", steps)


_BIN_OPS: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}


def calculator(expression: str) -> str:
    """Arithmetic-only evaluator for model-written input. Never ``eval()`` model output."""

    def ev(node: ast.AST) -> float:
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return node.value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub | ast.UAdd):
            value = ev(node.operand)
            return -value if isinstance(node.op, ast.USub) else value
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
            left, right = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 64:
                raise ValueError("exponent too large")
            return _BIN_OPS[type(node.op)](left, right)
        raise ValueError(f"unsupported expression: {ast.dump(node)[:40]}")

    if len(expression) > 200:
        raise ValueError("expression too long")
    result = ev(ast.parse(expression, mode="eval").body)
    if isinstance(result, float) and result.is_integer():
        result = int(result)
    return str(result)


# ---------------------------------------------------------------- chains


def run_chain(
    model: ChatModel,
    steps: Sequence[tuple[str, PromptTemplate]],
    **inputs: str,
) -> dict[str, str]:
    """Run templates in order. Each output is stored under its step name for later steps."""
    values: dict[str, str] = dict(inputs)
    for name, template in steps:
        missing = [f for f in template.fields if f not in values]
        if missing:
            raise KeyError(f"step '{name}' needs {missing}, which no earlier step produced")
        prompt = template.render(**{f: values[f] for f in template.fields})
        values[name] = model.complete(prompt).strip()
    return values
