from solution import word_break


def test_example_true():
    assert word_break("leetcode", ["leet", "code"]) is True


def test_example_false():
    assert word_break("catsandog", ["cats", "dog", "sand", "and", "cat"]) is False


def test_reuse_words():
    assert word_break("applepenapple", ["apple", "pen"]) is True


def test_single_char():
    assert word_break("a", ["a"]) is True


def test_empty_dict():
    assert word_break("hello", []) is False
