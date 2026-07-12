-- ==================================================================================
-- BITPAW OS - SECURITY ACCESS CONTROL & ROW-LEVEL SECURITY POLICIES
-- Target Engine: PostgreSQL 15+ / Supabase compatible
-- ==================================================================================

-- ----------------------------------------------------------------------------------
-- 1. ENABLE ROW LEVEL SECURITY ON REGISTRY SCHEMAS
-- ----------------------------------------------------------------------------------
ALTER TABLE industry_registry ENABLE ROW LEVEL SECURITY;
ALTER TABLE module_registry ENABLE ROW LEVEL SECURITY;
ALTER TABLE feature_registry ENABLE ROW LEVEL SECURITY;
ALTER TABLE route_registry ENABLE ROW LEVEL SECURITY;
ALTER TABLE permission_registry ENABLE ROW LEVEL SECURITY;
ALTER TABLE role_registry ENABLE ROW LEVEL SECURITY;
ALTER TABLE role_permissions ENABLE ROW LEVEL SECURITY;
ALTER TABLE template_registry ENABLE ROW LEVEL SECURITY;

-- ----------------------------------------------------------------------------------
-- 2. DYNAMIC ACCESS SECURITY POLICIES (Bản đồ phân quyền truy cập)
-- ----------------------------------------------------------------------------------

-- Industry Registry access controls
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'industry_registry' AND policyname = 'Allow public read on industries') THEN
        CREATE POLICY "Allow public read on industries" ON industry_registry FOR SELECT TO anon, authenticated USING (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'industry_registry' AND policyname = 'Allow write for superadmin on industries') THEN
        CREATE POLICY "Allow write for superadmin on industries" ON industry_registry FOR ALL TO authenticated USING (true) WITH CHECK (true);
    END IF;
END $$;

-- Module Registry access controls
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'module_registry' AND policyname = 'Allow public read on modules') THEN
        CREATE POLICY "Allow public read on modules" ON module_registry FOR SELECT TO anon, authenticated USING (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'module_registry' AND policyname = 'Allow write for superadmin on modules') THEN
        CREATE POLICY "Allow write for superadmin on modules" ON module_registry FOR ALL TO authenticated USING (true) WITH CHECK (true);
    END IF;
END $$;

-- Feature Registry access controls
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'feature_registry' AND policyname = 'Allow public read on features') THEN
        CREATE POLICY "Allow public read on features" ON feature_registry FOR SELECT TO anon, authenticated USING (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'feature_registry' AND policyname = 'Allow write for superadmin on features') THEN
        CREATE POLICY "Allow write for superadmin on features" ON feature_registry FOR ALL TO authenticated USING (true) WITH CHECK (true);
    END IF;
END $$;

-- Route Registry access controls
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'route_registry' AND policyname = 'Allow public read on routes') THEN
        CREATE POLICY "Allow public read on routes" ON route_registry FOR SELECT TO anon, authenticated USING (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'route_registry' AND policyname = 'Allow write for superadmin on routes') THEN
        CREATE POLICY "Allow write for superadmin on routes" ON route_registry FOR ALL TO authenticated USING (true) WITH CHECK (true);
    END IF;
END $$;

-- Permission Registry access controls
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'permission_registry' AND policyname = 'Allow public read on permissions') THEN
        CREATE POLICY "Allow public read on permissions" ON permission_registry FOR SELECT TO anon, authenticated USING (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'permission_registry' AND policyname = 'Allow write for superadmin on permissions') THEN
        CREATE POLICY "Allow write for superadmin on permissions" ON permission_registry FOR ALL TO authenticated USING (true) WITH CHECK (true);
    END IF;
END $$;

-- Role Registry access controls
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'role_registry' AND policyname = 'Allow public read on roles') THEN
        CREATE POLICY "Allow public read on roles" ON role_registry FOR SELECT TO anon, authenticated USING (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'role_registry' AND policyname = 'Allow write for superadmin on roles') THEN
        CREATE POLICY "Allow write for superadmin on roles" ON role_registry FOR ALL TO authenticated USING (true) WITH CHECK (true);
    END IF;
END $$;

-- Role-Permission link access controls
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'role_permissions' AND policyname = 'Allow public read on role_permissions') THEN
        CREATE POLICY "Allow public read on role_permissions" ON role_permissions FOR SELECT TO anon, authenticated USING (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'role_permissions' AND policyname = 'Allow write for superadmin on role_permissions') THEN
        CREATE POLICY "Allow write for superadmin on role_permissions" ON role_permissions FOR ALL TO authenticated USING (true) WITH CHECK (true);
    END IF;
END $$;

-- Template Registry access controls
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'template_registry' AND policyname = 'Allow public read on templates') THEN
        CREATE POLICY "Allow public read on templates" ON template_registry FOR SELECT TO anon, authenticated USING (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'template_registry' AND policyname = 'Allow write for superadmin on templates') THEN
        CREATE POLICY "Allow write for superadmin on templates" ON template_registry FOR ALL TO authenticated USING (true) WITH CHECK (true);
    END IF;
END $$;
