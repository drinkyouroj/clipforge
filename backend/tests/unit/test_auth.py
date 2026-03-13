import pytest


@pytest.mark.asyncio
async def test_register_user(client):
    resp = await client.post("/auth/register", json={
        "email": "test@example.com",
        "password": "StrongPass123!",
        "tos_accepted": True,
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == "test@example.com"
    assert "id" in data


@pytest.mark.asyncio
async def test_register_requires_tos(client):
    resp = await client.post("/auth/register", json={
        "email": "notos@example.com",
        "password": "StrongPass123!",
        "tos_accepted": False,
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_register_duplicate_email(client):
    payload = {"email": "dupe@example.com", "password": "StrongPass123!", "tos_accepted": True}
    await client.post("/auth/register", json=payload)
    resp = await client.post("/auth/register", json=payload)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_login_sets_httponly_cookie(client):
    await client.post("/auth/register", json={
        "email": "login@example.com",
        "password": "StrongPass123!",
        "tos_accepted": True,
    })
    resp = await client.post("/auth/login", json={
        "email": "login@example.com",
        "password": "StrongPass123!",
    })
    assert resp.status_code == 200
    assert "access_token" in resp.cookies


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    await client.post("/auth/register", json={
        "email": "wrong@example.com",
        "password": "StrongPass123!",
        "tos_accepted": True,
    })
    resp = await client.post("/auth/login", json={
        "email": "wrong@example.com",
        "password": "WrongPassword!",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_endpoint_with_cookie(client):
    await client.post("/auth/register", json={
        "email": "me@example.com",
        "password": "StrongPass123!",
        "tos_accepted": True,
    })
    await client.post("/auth/login", json={
        "email": "me@example.com",
        "password": "StrongPass123!",
    })
    resp = await client.get("/auth/me")
    assert resp.status_code == 200
    assert resp.json()["email"] == "me@example.com"


@pytest.mark.asyncio
async def test_me_endpoint_unauthenticated(client):
    resp = await client.get("/auth/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_logout_clears_cookie(client):
    await client.post("/auth/register", json={
        "email": "logout@example.com",
        "password": "StrongPass123!",
        "tos_accepted": True,
    })
    await client.post("/auth/login", json={
        "email": "logout@example.com",
        "password": "StrongPass123!",
    })
    resp = await client.post("/auth/logout")
    assert resp.status_code == 200
    # After logout, /me should fail
    resp = await client.get("/auth/me")
    assert resp.status_code == 401
