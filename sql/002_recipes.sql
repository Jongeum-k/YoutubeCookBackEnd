-- ============================================================
-- YouTube Cook - Dashboard Schema v2
-- Adds language-forked recipe storage.
--
-- video_analyses is untouched: it stays a request/attempt log,
-- one row per request regardless of outcome, exactly as it works
-- today. recipes.youtube_video_id is a plain natural key (the
-- normalized id extracted from the URL) -- no FK to video_analyses
-- and no separate "videos" identity table either, since nothing
-- else needs to reference video identity right now.
-- PostgreSQL / Neon
-- ============================================================


-- ------------------------------------------------------------
-- 0. gemini_requests: distinguish a real video analysis call
-- from a cheap text-only translation call, and record which
-- language each call produced.
-- ------------------------------------------------------------

ALTER TABLE gemini_requests
    ADD COLUMN request_type VARCHAR(20) NOT NULL DEFAULT 'analysis',
    ADD COLUMN language VARCHAR(5);

ALTER TABLE gemini_requests
    ADD CONSTRAINT chk_gemini_request_type
        CHECK (request_type IN ('analysis', 'translation')),
    ADD CONSTRAINT chk_gemini_request_language
        CHECK (language IS NULL OR language IN ('ko', 'en'));


-- ------------------------------------------------------------
-- 1. Recipe
-- One row per (video, language). youtube_video_id is a plain
-- natural key -- not a FK to video_analyses/analysis_id, so a
-- recipe survives independent of any one analysis attempt.
-- ------------------------------------------------------------

CREATE TABLE recipes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    youtube_video_id VARCHAR(32) NOT NULL,

    language VARCHAR(5) NOT NULL
        CHECK (language IN ('ko', 'en')),

    -- basic_info
    title TEXT NOT NULL,
    description TEXT,
    servings VARCHAR(50),
    cuisine VARCHAR(50),

    -- Free-form cooking tips, in display order
    tips TEXT[] NOT NULL DEFAULT '{}',

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_recipe_video_language
        UNIQUE (youtube_video_id, language)
);



-- ------------------------------------------------------------
-- 2. Recipe Ingredient
-- One row per ingredient line, ordered within a recipe.
-- ------------------------------------------------------------

CREATE TABLE recipe_ingredients (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    recipe_id UUID NOT NULL
        REFERENCES recipes(id)
        ON DELETE CASCADE,

    sort_order INTEGER NOT NULL,

    name TEXT NOT NULL,
    amount VARCHAR(50),
    unit VARCHAR(50),
    note TEXT,

    CONSTRAINT uq_recipe_ingredient_sort_order
        UNIQUE (recipe_id, sort_order),

    CONSTRAINT chk_ingredient_sort_order_non_negative
        CHECK (sort_order >= 0)
);



-- ------------------------------------------------------------
-- 3. Recipe Step
-- One row per cooking step, ordered within a recipe.
-- Timestamps (start/end seconds) tie a step back to the source
-- video and are language-independent -- a translated recipe
-- carries the same timestamps as its source.
-- ------------------------------------------------------------

CREATE TABLE recipe_steps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    recipe_id UUID NOT NULL
        REFERENCES recipes(id)
        ON DELETE CASCADE,

    step_order INTEGER NOT NULL,
    instruction TEXT NOT NULL,

    start_seconds INTEGER,
    end_seconds INTEGER,

    temperature VARCHAR(50),
    duration VARCHAR(50),

    CONSTRAINT uq_recipe_step_order
        UNIQUE (recipe_id, step_order),

    CONSTRAINT chk_step_order_non_negative
        CHECK (step_order >= 0),

    CONSTRAINT chk_step_start_seconds_non_negative
        CHECK (start_seconds IS NULL OR start_seconds >= 0),

    CONSTRAINT chk_step_end_seconds_non_negative
        CHECK (end_seconds IS NULL OR end_seconds >= 0),

    CONSTRAINT chk_step_seconds_order
        CHECK (
            start_seconds IS NULL
            OR end_seconds IS NULL
            OR end_seconds >= start_seconds
        )
);



-- ============================================================
-- Indexes
-- ============================================================

-- Ingredient list for a recipe, in order
CREATE INDEX idx_recipe_ingredients_recipe_id
    ON recipe_ingredients (recipe_id, sort_order);

-- Step list for a recipe, in order
CREATE INDEX idx_recipe_steps_recipe_id
    ON recipe_steps (recipe_id, step_order);

-- Gemini usage dashboard: filter/breakdown by call type
CREATE INDEX idx_gemini_requests_request_type
    ON gemini_requests (request_type);
