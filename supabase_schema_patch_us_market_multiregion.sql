-- ==================================================================================
-- BITPAW OS - SUPPLEMENTARY DATABASE SCHEMA PATCH
-- Target Database Engine: PostgreSQL 15+ / Supabase compatible
-- Objective: US Market Pivot — Multi-Region tenant support.
--
-- BitPaw OS now runs two independent markets side by side (US and VN) instead of
-- a single global currency/locale. Each tenant in `businesses` carries its own
-- `country` and `currency`. Existing rows (all current VN tenants) default to
-- ('VN', 'VND') — zero behavior change for them. New US tenants are provisioned
-- with ('US', 'USD') and store amounts natively in USD (no FX conversion of
-- historical VND figures happens anywhere in the app).
--
-- Safety: purely additive (ADD COLUMN IF NOT EXISTS with defaults). Does not
-- touch, convert, or delete any existing row or table.
-- ==================================================================================

ALTER TABLE businesses ADD COLUMN IF NOT EXISTS country TEXT NOT NULL DEFAULT 'VN' CHECK (country IN ('VN', 'US'));
ALTER TABLE businesses ADD COLUMN IF NOT EXISTS currency TEXT NOT NULL DEFAULT 'VND' CHECK (currency IN ('VND', 'USD'));

CREATE INDEX IF NOT EXISTS idx_businesses_country ON businesses(country);

-- payment_transactions.currency already exists (supabase_schema_patch_payment_transactions.sql,
-- DEFAULT 'VND', no CHECK constraint) — the Square flow just writes 'USD' into it, no patch needed here.
