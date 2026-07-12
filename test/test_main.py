import pytest
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.main import Base, Ingredient, Recipe, app, get_session

TEST_DATABASE_URL = "sqlite+aiosqlite:///./test_cookbook.db"
engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestingSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture(scope="session", autouse=True)
async def prepare_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def override_get_session():
    async with TestingSessionLocal() as session:
        yield session


app.dependency_overrides[get_session] = override_get_session


@pytest.fixture(autouse=True)
async def clean_tables():
    async with TestingSessionLocal() as session:
        await session.execute(delete(Recipe))
        await session.execute(delete(Ingredient))
        await session.commit()
    yield


@pytest.mark.anyio
async def test_create_recipe_and_get_detail():
    payload = {
        "name": "Омлет",
        "cooking_time": 10,
        "description": "Взбить яйца и приготовить на сковороде.",
        "ingredients": [{"name": "Яйца"}, {"name": "Соль"}],
    }

    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.post("/recipes", json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Омлет"
    assert len(data["ingredients"]) == 2

    recipe_id = data["id"]
    async with AsyncClient(app=app, base_url="http://test") as client:
        detail = await client.get(f"/recipes/{recipe_id}")

    assert detail.status_code == 200
    detail_data = detail.json()
    assert detail_data["name"] == "Омлет"
    assert detail_data["views"] == 1
    assert detail_data["description"].startswith("Взбить")


@pytest.mark.anyio
async def test_recipes_sorted_by_popularity_then_time():
    async with TestingSessionLocal() as session:
        r1 = Recipe(name="A", cooking_time=30, description="A", views=5)
        r2 = Recipe(name="B", cooking_time=10, description="B", views=5)
        r3 = Recipe(name="C", cooking_time=20, description="C", views=2)
        session.add_all([r1, r2, r3])
        await session.commit()

    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/recipes")

    assert response.status_code == 200
    names = [item["name"] for item in response.json()]
    assert names == ["B", "A", "C"]
