"""FastAPI service over the starter modules. No model calls, no API keys.

Run locally:   uvicorn app.main:app --reload
Production:    uvicorn app.main:app --host 0.0.0.0 --port 8000  (see Dockerfile)
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app import __version__
from app.cache import caching_cost
from app.guard import scan
from app.reasoning import extract_answer, majority_vote
from app.sampling import distribution, entropy_bits
from app.security import deep_scan, exfil_links
from app.templates import Example, FewShotPrompt, PromptTemplate, TemplateError, select_examples
from app.tokens import estimate_tokens, train_bpe

# A tiny training corpus so /tokenize shows real merges without downloading a vocabulary.
CORPUS = """
A prompt is the only input a model sees. The prompt sets the task, the prompt sets the format,
and the prompt sets the examples. Prompt templates keep prompts consistent. A model reads tokens,
not words, and the model predicts the next token from the tokens before it. Tokens cost money,
so count tokens before you send a long prompt. Examples in the prompt teach the model the format.
"""
TOKENIZER = train_bpe(CORPUS, num_merges=120)

app = FastAPI(title="Prompt Engineering Starter", version=__version__)


class TextIn(BaseModel):
    text: str


class SampleIn(BaseModel):
    logits: dict[str, float] = Field(min_length=1)
    temperature: float = Field(default=1.0, ge=0, le=2)
    top_k: int | None = Field(default=None, ge=1)
    top_p: float | None = Field(default=None, gt=0, le=1)


class RenderIn(BaseModel):
    template: str
    values: dict[str, str] = Field(default_factory=dict)
    escape: bool = True


class ExampleIn(BaseModel):
    input: str
    output: str
    reasoning: str | None = None


class FewShotIn(BaseModel):
    instruction: str
    examples: list[ExampleIn] = Field(min_length=1)
    query: str
    k: int = Field(default=3, ge=1, le=20)
    balance_labels: bool = False


class VoteIn(BaseModel):
    completions: list[str] = Field(min_length=1)


class CacheIn(BaseModel):
    prefix_tokens: int = Field(ge=0)
    suffix_tokens: int = Field(ge=0)
    requests: int = Field(ge=1)
    write_multiplier: float = Field(default=1.25, ge=0)
    read_multiplier: float = Field(default=0.10, ge=0)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.post("/tokenize")
def tokenize(body: TextIn) -> dict[str, object]:
    tokens = TOKENIZER.encode(body.text)
    return {
        "tokens": tokens,
        "ids": TOKENIZER.encode_ids(body.text),
        "count": len(tokens),
        "estimate": estimate_tokens(body.text),
    }


@app.post("/sample")
def sample(body: SampleIn) -> dict[str, object]:
    probs = distribution(body.logits, temperature=body.temperature, top_k=body.top_k, top_p=body.top_p)
    ranked = dict(sorted(probs.items(), key=lambda kv: (-kv[1], kv[0])))
    return {"distribution": {k: round(v, 4) for k, v in ranked.items()}, "entropy_bits": round(entropy_bits(probs), 4)}


@app.post("/render")
def render(body: RenderIn) -> dict[str, object]:
    try:
        template = PromptTemplate(body.template)
        prompt = template.render(escape=body.escape, **body.values)
    except TemplateError as err:
        raise HTTPException(status_code=422, detail=str(err)) from None
    return {"fields": list(template.fields), "prompt": prompt}


@app.post("/few-shot")
def few_shot(body: FewShotIn) -> dict[str, object]:
    pool = [Example(e.input, e.output, e.reasoning) for e in body.examples]
    chosen = select_examples(pool, body.query, body.k, balance_labels=body.balance_labels)
    try:
        prompt = FewShotPrompt(body.instruction, chosen).render(body.query)
    except TemplateError as err:
        raise HTTPException(status_code=422, detail=str(err)) from None
    return {"selected": [e.input for e in chosen], "prompt": prompt}


@app.post("/answer")
def answer(body: TextIn) -> dict[str, str | None]:
    return {"answer": extract_answer(body.text)}


@app.post("/vote")
def vote(body: VoteIn) -> dict[str, object]:
    result = majority_vote(body.completions)
    return {
        "answer": result.answer,
        "votes": result.votes,
        "total": result.total,
        "parsed": result.parsed,
        "confidence": round(result.confidence, 4),
    }


@app.post("/guard/scan")
def guard_scan(body: TextIn) -> dict[str, object]:
    matches = scan(body.text)
    return {"suspicious": bool(matches), "matches": matches}


class LinksIn(BaseModel):
    text: str
    allowed_domains: list[str] = Field(default_factory=list)


@app.post("/guard/deep-scan")
def guard_deep_scan(body: TextIn) -> dict[str, object]:
    matches = deep_scan(body.text)
    return {"suspicious": bool(matches), "matches": matches}


@app.post("/guard/links")
def guard_links(body: LinksIn) -> dict[str, object]:
    blocked = exfil_links(body.text, body.allowed_domains)
    return {"blocked": blocked, "safe": not blocked}


@app.post("/cache/savings")
def cache_savings(body: CacheIn) -> dict[str, float]:
    return caching_cost(
        body.prefix_tokens,
        body.suffix_tokens,
        body.requests,
        write_multiplier=body.write_multiplier,
        read_multiplier=body.read_multiplier,
    )
