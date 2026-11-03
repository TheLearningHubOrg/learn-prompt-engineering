"""Adapters from the official SDKs to ``ChatModel``. Not used by the tests.

Install the SDK you need (``pip install openai`` or ``pip install anthropic``), set the
API key in the environment, and pass a model id you have access to, for example::

    from app.providers import AnthropicModel
    from app.reasoning import self_consistency

    model = AnthropicModel(model=os.environ["ANTHROPIC_MODEL"])
    print(self_consistency(model, "What is 17 * 24? End with 'Answer: <n>'.", n=5))
"""

from __future__ import annotations


class OpenAIModel:  # pragma: no cover - needs network and a key
    def __init__(self, model: str, temperature: float | None = None):
        from openai import OpenAI

        self._client = OpenAI()
        self._model = model
        self._temperature = temperature  # leave None for reasoning models, which reject it

    def complete(self, prompt: str) -> str:
        kwargs = {} if self._temperature is None else {"temperature": self._temperature}
        response = self._client.responses.create(model=self._model, input=prompt, **kwargs)
        return response.output_text


class AnthropicModel:  # pragma: no cover - needs network and a key
    def __init__(self, model: str, max_tokens: int = 1024, temperature: float | None = None):
        import anthropic

        self._client = anthropic.Anthropic()
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature

    def complete(self, prompt: str) -> str:
        kwargs = {} if self._temperature is None else {"temperature": self._temperature}
        message = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            messages=[{"role": "user", "content": prompt}],
            **kwargs,
        )
        return "".join(block.text for block in message.content if block.type == "text")
