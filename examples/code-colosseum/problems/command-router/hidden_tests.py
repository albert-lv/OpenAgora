from solution import match_route


def test_route_order_wins():
    routes = [
        ("static", "/users/me"),
        ("param", "/users/:id"),
    ]
    assert match_route("/users/me", routes) == ("static", {})
    assert match_route("/users/alice", routes) == ("param", {"id": "alice"})


def test_catch_all():
    routes = [("files", "/files/*")]
    assert match_route("/files/a/b/c", routes) == ("files", {"*": "a/b/c"})
    assert match_route("/files", routes) == ("files", {"*": ""})


def test_multiple_params():
    routes = [("post", "/users/:user_id/posts/:post_id")]
    assert match_route("/users/42/posts/7", routes) == (
        "post",
        {"user_id": "42", "post_id": "7"},
    )


def test_no_match():
    routes = [("users", "/users")]
    assert match_route("/posts", routes) is None
    assert match_route("/users/extra", routes) is None


def test_static_over_param_by_order():
    routes = [
        ("param", "/users/:id"),
        ("static", "/users/me"),
    ]
    assert match_route("/users/me", routes) == ("param", {"id": "me"})


def test_param_not_empty():
    routes = [("user", "/users/:id")]
    assert match_route("/users/", routes) is None


def test_trailing_slash():
    routes = [("user", "/users/:id")]
    assert match_route("/users/123/", routes) == ("user", {"id": "123"})
