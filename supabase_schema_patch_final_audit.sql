-- ==================================================================================
-- BITPAW OS - SUPPLEMENTARY DATABASE SCHEMA PATCH
-- Target Database Engine: PostgreSQL 15+ / Supabase compatible
-- Objective: Fix findings from the final go-live audit.
-- Safety: purely additive (ADD COLUMN IF NOT EXISTS / CREATE OR REPLACE FUNCTION /
--         CREATE TRIGGER). Does not touch or delete any existing row.
-- ==================================================================================

-- 1. Auto-populate business_id on orders/order_items from the request's JWT claims,
--    instead of trusting the client to send it. spa.html and karaoke.html already
--    upgrade their Supabase client to carry a short-lived JWT with a `business_id`
--    claim (minted server-side by _mint_tenant_jwt in app.py, used for RLS tenant
--    scoping) — but nothing was copying that claim onto the row itself, so every
--    order/order_item written from those pages had business_id = NULL. This broke
--    AIContextEngine's purchase-history lookup (ai_context_engine.py), which filters
--    strictly on business_id + customer_phone and therefore always returned empty.
--
--    This trigger reads the SAME JWT claim already used by RLS
--    (current_setting('request.jwt.claims', true)::json ->> 'business_id') and, if
--    the incoming row's business_id is NULL, fills it in server-side. The client
--    JS is intentionally left untouched — business_id is not something the browser
--    should be trusted to set directly.

CREATE OR REPLACE FUNCTION set_business_id_from_jwt()
RETURNS TRIGGER AS $$
DECLARE
    jwt_business_id TEXT;
BEGIN
    IF NEW.business_id IS NULL THEN
        jwt_business_id := current_setting('request.jwt.claims', true)::json ->> 'business_id';
        IF jwt_business_id IS NOT NULL THEN
            NEW.business_id := jwt_business_id::uuid;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_orders_set_business_id ON orders;
CREATE TRIGGER trg_orders_set_business_id
    BEFORE INSERT ON orders
    FOR EACH ROW EXECUTE FUNCTION set_business_id_from_jwt();

DROP TRIGGER IF EXISTS trg_order_items_set_business_id ON order_items;
CREATE TRIGGER trg_order_items_set_business_id
    BEFORE INSERT ON order_items
    FOR EACH ROW EXECUTE FUNCTION set_business_id_from_jwt();

-- 2. cauhinh_luong.html's "Save" button posts to /api/cauhinh_luong/<staff_id>, a
--    Flask route that never existed — every salary-config save was a guaranteed
--    404. The `staff` table has no columns for the detailed salary fields this page
--    edits (luong_cung, luong_gio, hoa_hong, phu_cap, tang_ca), so store them as a
--    single flexible JSON blob rather than adding five narrow columns.
--
--    NOTE: this is a SEPARATE, narrower fix from the app's other HR/payroll system
--    (the `employees` + `chamcong` tables used by nhanvien.html/bangluong.html,
--    which are not defined in any tracked schema file — see final audit report).
--    cauhinh_luong.html operates on the `staff` table (via staff_id), which is a
--    different registry than `employees` (keyed by ma_nv). This patch only makes
--    cauhinh_luong.html's own save button work against ITS OWN data source; it does
--    NOT reconcile it with employees/bangluong.html's payroll calculation, which is
--    a bigger product decision left to the team.
ALTER TABLE staff ADD COLUMN IF NOT EXISTS salary_config JSONB DEFAULT '{}'::jsonb;
