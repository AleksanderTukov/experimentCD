from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator, List

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import ForeignKey, Integer, String, Text, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, selectinload

DATABASE_URL = "sqlite+aiosqlite:///./cookbook.db"

engine = create_async_engine(DATABASE_URL, echo=False)
async_session_maker = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class RecipeIngredient(Base):
    __tablename__ = "recipe_ingredients"

    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipes.id", ondelete="CASCADE"), primary_key=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id", ondelete="CASCADE"), primary_key=True)


class Recipe(Base):
    __tablename__ = "recipes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    cooking_time: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    views: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    ingredients: Mapped[list["Ingredient"]] = relationship(
        secondary="recipe_ingredients",
        back_populates="recipes",
        lazy="selectin",
    )


class Ingredient(Base):
    __tablename__ = "ingredients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)

    recipes: Mapped[list[Recipe]] = relationship(
        secondary="recipe_ingredients",
        back_populates="ingredients",
        lazy="selectin",
    )


class IngredientOut(BaseModel):
    id: int
    name: str

    model_config = ConfigDict(from_attributes=True)


class RecipeListItemOut(BaseModel):
    id: int
    name: str
    views: int
    cooking_time: int

    model_config = ConfigDict(from_attributes=True)


class RecipeDetailOut(BaseModel):
    id: int
    name: str
    views: int
    cooking_time: int
    ingredients: List[IngredientOut]
    description: str

    model_config = ConfigDict(from_attributes=True)


class RecipeCreateIngredientIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class RecipeCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=255, examples=["Борщ"])
    cooking_time: int = Field(gt=0, examples=[90])
    description: str = Field(min_length=1, examples=["Пошаговое описание рецепта"])
    ingredients: list[RecipeCreateIngredientIn] = Field(min_length=1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(
    title="Cookbook API",
    version="1.0.0",
    description="Асинхронный API кулинарной книги на FastAPI и SQLAlchemy.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session


@app.get(
    "/recipes",
    response_model=list[RecipeListItemOut],
    summary="Список рецептов",
    description="Возвращает все рецепты, отсортированные по популярности и времени готовки.",
)
async def get_recipes(session: AsyncSession = Depends(get_session)):
    stmt = select(Recipe).order_by(Recipe.views.desc(), Recipe.cooking_time.asc(), Recipe.name.asc())
    result = await session.execute(stmt)
    recipes = result.scalars().all()
    return recipes


@app.get(
    "/recipes/{recipe_id}",
    response_model=RecipeDetailOut,
    summary="Детальный рецепт",
    description="Возвращает полную информацию о рецепте и увеличивает счётчик просмотров на 1.",
)
async def get_recipe(recipe_id: int, session: AsyncSession = Depends(get_session)):
    stmt = (
        select(Recipe)
        .options(selectinload(Recipe.ingredients))
        .where(Recipe.id == recipe_id)
    )
    result = await session.execute(stmt)
    recipe = result.scalar_one_or_none()
    if recipe is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recipe not found")

    recipe.views += 1
    await session.commit()
    await session.refresh(recipe)
    return recipe


@app.post(
    "/recipes",
    response_model=RecipeDetailOut,
    status_code=status.HTTP_201_CREATED,
    summary="Создать рецепт",
    description="Создаёт новый рецепт вместе со списком ингредиентов.",
)
async def create_recipe(payload: RecipeCreateIn, session: AsyncSession = Depends(get_session)):
    ingredient_names = [item.name.strip() for item in payload.ingredients]
    ingredients: list[Ingredient] = []

    for name in ingredient_names:
        stmt = select(Ingredient).where(func.lower(Ingredient.name) == name.lower())
        result = await session.execute(stmt)
        ingredient = result.scalar_one_or_none()
        if ingredient is None:
            ingredient = Ingredient(name=name)
            session.add(ingredient)
            await session.flush()
        ingredients.append(ingredient)

    recipe = Recipe(
        name=payload.name,
        cooking_time=payload.cooking_time,
        description=payload.description,
        ingredients=ingredients,
    )
    session.add(recipe)
    await session.commit()

    stmt = select(Recipe).options(selectinload(Recipe.ingredients)).where(Recipe.id == recipe.id)
    result = await session.execute(stmt)
    created = result.scalar_one()
    return created
