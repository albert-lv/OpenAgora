from solution import match_route


def test_static_match():
    assert match_route("/users/123", [("user_detail", "/users/:id")]) == (
        "user_detail",
        {"id": "123"},
    )


def test_root():
    assert match_route("/", [("home", "/")]) == ("home", {})
