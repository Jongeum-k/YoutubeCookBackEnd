# app/models/recipe.py

import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Recipe(Base):
    """One language version of the recipe extracted from a video.

    Keyed off youtube_video_id as a plain natural key (not a FK to
    video_analyses/analysis_id, and not a FK to any separate "videos"
    table either -- the extracted video id is already a normalized,
    stable identifier on its own, and nothing else needs to reference
    it). video_analyses stays an untouched request/attempt log with
    one row per request. A video has at most one Recipe per language
    (see uq_recipe_video_language) -- 'ko' and 'en' are separate rows,
    each with their own ingredients/steps, rather than parallel
    translated columns.
    """

    __tablename__ = "recipes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    youtube_video_id: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    language: Mapped[str] = mapped_column(
        String(5),
        nullable=False,
    )

    title: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    servings: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    cuisine: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    tips: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        default=list,
        server_default="{}",
    )

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    ingredients: Mapped[list["RecipeIngredient"]] = relationship(
        back_populates="recipe",
        cascade="all, delete-orphan",
        order_by="RecipeIngredient.sort_order",
    )

    steps: Mapped[list["RecipeStep"]] = relationship(
        back_populates="recipe",
        cascade="all, delete-orphan",
        order_by="RecipeStep.step_order",
    )

    __table_args__ = (
        UniqueConstraint(
            "youtube_video_id",
            "language",
            name="uq_recipe_video_language",
        ),
        CheckConstraint(
            "language IN ('ko', 'en')",
            name="chk_recipe_language",
        ),
    )


class RecipeIngredient(Base):
    __tablename__ = "recipe_ingredients"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    recipe_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "recipes.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    sort_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    name: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    amount: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    unit: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    note: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    recipe: Mapped["Recipe"] = relationship(
        back_populates="ingredients",
    )

    __table_args__ = (
        UniqueConstraint(
            "recipe_id",
            "sort_order",
            name="uq_recipe_ingredient_sort_order",
        ),
        CheckConstraint(
            "sort_order >= 0",
            name="chk_ingredient_sort_order_non_negative",
        ),
    )


class RecipeStep(Base):
    __tablename__ = "recipe_steps"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    recipe_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "recipes.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    step_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    instruction: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    start_seconds: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    end_seconds: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    temperature: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    duration: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    recipe: Mapped["Recipe"] = relationship(
        back_populates="steps",
    )

    __table_args__ = (
        UniqueConstraint(
            "recipe_id",
            "step_order",
            name="uq_recipe_step_order",
        ),
        CheckConstraint(
            "step_order >= 0",
            name="chk_step_order_non_negative",
        ),
        CheckConstraint(
            "start_seconds IS NULL OR start_seconds >= 0",
            name="chk_step_start_seconds_non_negative",
        ),
        CheckConstraint(
            "end_seconds IS NULL OR end_seconds >= 0",
            name="chk_step_end_seconds_non_negative",
        ),
        CheckConstraint(
            "start_seconds IS NULL OR end_seconds IS NULL "
            "OR end_seconds >= start_seconds",
            name="chk_step_seconds_order",
        ),
    )
