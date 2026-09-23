def login_client(client, nickname="user1"):
    client.get("/")
    with client.session_transaction() as state:
        token = state["csrf_token"]
    return client.post("/", data={"nickname": nickname, "csrf_token": token})


def logout_client(client):
    with client.session_transaction() as state:
        token = state.get("csrf_token", "")
    return client.post("/logout", data={"csrf_token": token})
