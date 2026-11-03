import pytest

from app.messages import Conversation, edge_order, pack_documents


def convo() -> Conversation:
    return Conversation("You classify alerts.").user("Disk 91% full").assistant("SEV-3").user("DB down")


def test_openai_chat_puts_instructions_first():
    body = convo().to_openai_chat()
    assert body["messages"][0] == {"role": "system", "content": "You classify alerts."}
    assert convo().to_openai_chat("developer")["messages"][0]["role"] == "developer"


def test_responses_and_anthropic_keep_instructions_out_of_messages():
    responses = convo().to_openai_responses()
    assert responses["instructions"] == "You classify alerts."
    assert all(m["role"] in {"user", "assistant"} for m in responses["input"])
    anthropic = convo().to_anthropic()
    assert anthropic["system"] == "You classify alerts."
    assert len(anthropic["messages"]) == 3


def test_gemini_renames_assistant_to_model():
    body = convo().to_gemini()
    assert [c["role"] for c in body["contents"]] == ["user", "model", "user"]
    assert body["system_instruction"]["parts"][0]["text"] == "You classify alerts."


@pytest.mark.parametrize(
    "build",
    [
        lambda: Conversation("s"),
        lambda: Conversation("s").assistant("hi"),
        lambda: Conversation("s").user("a").user("b"),
    ],
)
def test_invalid_turn_order_is_rejected(build):
    with pytest.raises(ValueError):
        build().to_anthropic()


def test_edge_order_puts_best_items_at_both_ends():
    assert edge_order(["a", "b", "c", "d", "e"]) == ["a", "c", "e", "d", "b"]
    assert edge_order([]) == []


def test_pack_documents_respects_budget_and_rank():
    docs = ["x" * 40, "y" * 400, "z" * 20]  # 10, 100 and 5 estimated tokens
    assert pack_documents(docs, budget_tokens=20) == ["x" * 40, "z" * 20]
