-- ==================================================================================
-- BITPAW OS - SUPPLEMENTARY DATABASE SCHEMA PATCH
-- Target Database Engine: PostgreSQL 15+ / Supabase compatible
-- Objective: Campaign 2 (HR) — SAFE bridge between `staff` (used by
--            staff_management.html / cauhinh_luong.html) and `employees`
--            (used by the real, live payroll/attendance system across 17
--            templates: bangluong.html, nhanvien.html, app_nhanvien.html,
--            chamcong_*.html, map_dashboard.html, dashboard.html, etc.)
--
-- Why a bridge and not a full merge: reconnaissance found `employees`/`chamcong`
-- are a fully independent, deeply-integrated attendance/payroll system (GPS
-- tracking, checkin photos, production QC, tip pooling, kudo points, offline
-- sync) spanning 17 live templates, keyed by a human-typed string `ma_nv` —
-- structurally unrelated to `staff`'s numeric auto-increment `id`. Ripping this
-- out and migrating everything to `staff.id` the night before go-live is a much
-- higher-risk operation than the actual goal (make cauhinh_luong.html's salary
-- config usable by real payroll) requires. This patch adds an OPTIONAL link
-- instead — additive only, zero behavior change until an admin actually creates
-- a link, and bangluong.html's existing (correct) formula is untouched.
--
-- Safety: purely additive (ADD COLUMN IF NOT EXISTS). Does not touch or delete
-- any existing row, table, or the employees/chamcong system in any way.
-- ==================================================================================

ALTER TABLE employees ADD COLUMN IF NOT EXISTS staff_id BIGINT REFERENCES staff(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_employees_staff_id ON employees(staff_id);
