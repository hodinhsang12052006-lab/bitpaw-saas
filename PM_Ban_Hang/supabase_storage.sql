-- ==================================================================================
-- BITPAW OS - CLOUD OBJECT STORAGE ARCHITECTURE BUCKET PROFILES
-- Target: PostgreSQL / Supabase storage bucket configurations
-- ==================================================================================

-- ----------------------------------------------------------------------------------
-- 1. BUCKETS CONFIGURATION INSTRUCTIONS
-- ----------------------------------------------------------------------------------
-- Supabase storage is managed via the 'storage' schema in PostgreSQL.
-- The DDL commands below securely register and pre-configure standard buckets.

-- ----------------------------------------------------------------------------------
-- 2. CREATE STANDARD BUCKET PROFILES (backups, uploads, assets)
-- ----------------------------------------------------------------------------------
INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types) VALUES 
('backups', 'backups', false, 52428800, ARRAY['application/json']), -- 50MB limit, JSON backups only
('uploads', 'uploads', true, 10485760, ARRAY['image/png', 'image/jpeg', 'image/webp', 'image/jpg']), -- 10MB image limit
('assets', 'assets', true, 20971520, NULL) -- 20MB limit for general assets, logos, and catalogs
ON CONFLICT (id) DO UPDATE SET 
    public = EXCLUDED.public, file_size_limit = EXCLUDED.file_size_limit, allowed_mime_types = EXCLUDED.allowed_mime_types;

-- ----------------------------------------------------------------------------------
-- 3. ENABLE ROW LEVEL SECURITY AND POLICIES FOR SECURE OBJECT DOWNLOADS
-- ----------------------------------------------------------------------------------
-- Allow public select on public buckets ('uploads' and 'assets')
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE tablename = 'objects' AND schemaname = 'storage' AND policyname = 'Allow public select on public buckets'
    ) THEN
        CREATE POLICY "Allow public select on public buckets" ON storage.objects FOR SELECT TO anon, authenticated USING (
            bucket_id IN ('uploads', 'assets')
        );
    END IF;
END $$;

-- Allow authenticated uploads and deletes on all storage objects
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE tablename = 'objects' AND schemaname = 'storage' AND policyname = 'Allow authenticated users write operations'
    ) THEN
        CREATE POLICY "Allow authenticated users write operations" ON storage.objects FOR ALL TO authenticated USING (true) WITH CHECK (true);
    END IF;
END $$;
