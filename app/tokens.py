"""Stage 1: a byte-pair-encoding (BPE) tokenizer small enough to read in one sitting.

Production tokenizers (tiktoken, SentencePiece, Hugging Face ``tokenizers``) work on
bytes and ship vocabularies of 100k-200k entries, but the algorithm is the same:
split text into pre-tokens, then repeatedly merge the most frequent adjacent pair.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable

# GPT-style pre-tokenizer: a word keeps its leading space, digits come in runs of
# at most three, punctuation is grouped, whitespace stands alone.
_PRETOKEN = re.compile(r" ?[A-Za-z]+| ?\d{1,3}| ?[^\sA-Za-z\d]+|\s+")

UNK = "<unk>"


def pretokenize(text: str) -> list[str]:
    """Split text into the pieces BPE merges inside. Merges never cross pieces."""
    return _PRETOKEN.findall(text)


def _merge(word: tuple[str, ...], pair: tuple[str, str]) -> tuple[str, ...]:
    a, b = pair
    out: list[str] = []
    i = 0
    while i < len(word):
        if i + 1 < len(word) and word[i] == a and word[i + 1] == b:
            out.append(a + b)
            i += 2
        else:
            out.append(word[i])
            i += 1
    return tuple(out)


class BPETokenizer:
    """Applies a ranked list of merges. Lower rank means the merge was learned earlier."""

    def __init__(self, merges: Iterable[tuple[str, str]], alphabet: Iterable[str] = ()):
        self.merges = list(merges)
        self._ranks = {pair: rank for rank, pair in enumerate(self.merges)}
        symbols = sorted(set(alphabet) | {ch for pair in self.merges for part in pair for ch in part})
        self.vocab: dict[str, int] = {UNK: 0}
        for sym in symbols:
            self.vocab.setdefault(sym, len(self.vocab))
        for a, b in self.merges:
            self.vocab.setdefault(a + b, len(self.vocab))

    def _encode_piece(self, piece: str) -> list[str]:
        symbols = tuple(piece)
        while len(symbols) > 1:
            candidates = [
                (self._ranks[pair], pair)
                for pair in zip(symbols, symbols[1:], strict=False)
                if pair in self._ranks
            ]
            if not candidates:
                break
            _, best = min(candidates)
            symbols = _merge(symbols, best)
        return list(symbols)

    def encode(self, text: str) -> list[str]:
        """Return token strings. Joining them gives back the original text."""
        tokens: list[str] = []
        for piece in pretokenize(text):
            tokens.extend(self._encode_piece(piece))
        return tokens

    def encode_ids(self, text: str) -> list[int]:
        return [self.vocab.get(tok, self.vocab[UNK]) for tok in self.encode(text)]


def train_bpe(corpus: str, num_merges: int) -> BPETokenizer:
    """Learn up to ``num_merges`` merges from ``corpus``.

    Ties between equally frequent pairs are broken alphabetically so training is
    deterministic. Training stops early when no pair occurs at least twice.
    """
    words = Counter(tuple(piece) for piece in pretokenize(corpus))
    alphabet = {ch for word in words for ch in word}
    merges: list[tuple[str, str]] = []
    for _ in range(num_merges):
        pairs: Counter[tuple[str, str]] = Counter()
        for word, freq in words.items():
            for pair in zip(word, word[1:], strict=False):
                pairs[pair] += freq
        if not pairs:
            break
        best = min(pairs, key=lambda p: (-pairs[p], p))
        if pairs[best] < 2:
            break
        merges.append(best)
        words = Counter({_merge(word, best): freq for word, freq in words.items()})
    return BPETokenizer(merges, alphabet)


def estimate_tokens(text: str, chars_per_token: float = 4.0) -> int:
    """Rough budget check for English prose. Use the provider's tokenizer for billing."""
    if not text:
        return 0
    return math.ceil(len(text) / chars_per_token)
