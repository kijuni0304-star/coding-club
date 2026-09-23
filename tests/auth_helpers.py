def login_client(client, nickname="user1", password=None):
    client.get("/")
    with client.session_transaction() as state:
        token = state["csrf_token"]
    if password is None and nickname.startswith("user"):
        password = f"resu{nickname[4:]}!@"
    return client.post(
        "/",
        data={"nickname": nickname, "password": password or "", "csrf_token": token},
    )


def logout_client(client):
    with client.session_transaction() as state:
        token = state.get("csrf_token", "")
    return client.post("/logout", data={"csrf_token": token})
