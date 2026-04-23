from app.engine.token_accounting import TokenAccounting


def test_estimate_text_tokens_empty():
    ta = TokenAccounting()
    assert ta.estimate_text_tokens("") == 0
    assert ta.estimate_text_tokens("   ") == 0


def test_estimate_text_tokens_short():
    ta = TokenAccounting()
    assert ta.estimate_text_tokens("hello") == 2  # ceil(5/4)


def test_estimate_text_tokens_long():
    ta = TokenAccounting()
    text = "a" * 100
    assert ta.estimate_text_tokens(text) == 25  # ceil(100/4)


def test_estimate_many():
    ta = TokenAccounting()
    texts = ["hello", "", "world!"]
    result = ta.estimate_many(texts)
    assert result == 4  # 2 + 0 + 2
