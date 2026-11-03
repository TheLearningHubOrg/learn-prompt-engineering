from app.main import TOKENIZER
from app.tokens import BPETokenizer, estimate_tokens, pretokenize, train_bpe


def test_pretokenizer_keeps_leading_space_and_chunks_digits():
    assert pretokenize("Pay 1000000 now!") == ["Pay", " 100", "000", "0", " now", "!"]
    assert pretokenize("1000000") == ["100", "000", "0"]


def test_encoding_round_trips():
    text = "The prompt sets the format, and tokens cost money."
    assert "".join(TOKENIZER.encode(text)) == text


def test_frequent_words_become_single_tokens():
    assert TOKENIZER.encode(" prompt") == [" prompt"]
    # The same letters without the leading space are a different token sequence.
    assert TOKENIZER.encode("prompt") != [" prompt"]


def test_unseen_words_fall_back_to_smaller_pieces():
    tokens = TOKENIZER.encode(" zebra")
    assert len(tokens) > 1
    assert "".join(tokens) == " zebra"


def test_training_is_deterministic_and_stops_early():
    first = train_bpe("ab ab ab", 50)
    second = train_bpe("ab ab ab", 50)
    assert first.merges == second.merges
    assert len(first.merges) < 50


def test_unknown_characters_map_to_unk_id():
    tok = BPETokenizer([("a", "b")], alphabet="ab")
    assert tok.encode_ids("abz") == [tok.vocab["ab"], 0]


def test_estimate_tokens():
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd" * 10) == 10
