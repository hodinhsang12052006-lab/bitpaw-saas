-- =========================================================================
-- BITPAW NETWORK - DATABASE SCHEMA PATCH
-- VERSION: 1.0.0
-- PHASE: 1B (DRAFT Blueprints - Do NOT execute directly on production Supabase)
-- =========================================================================

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- =========================================================================
-- 1. REFERENCE TABLES
-- =========================================================================

-- Table: network_industries
CREATE TABLE IF NOT EXISTS network_industries (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    code VARCHAR(50) UNIQUE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
COMMENT ON TABLE network_industries IS 'Categories of industries (e.g. Nails, Spa, F&B, Retail, HVAC)';

-- Table: network_locations
CREATE TABLE IF NOT EXISTS network_locations (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL,
    country VARCHAR(10) NOT NULL DEFAULT 'VN',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
COMMENT ON TABLE network_locations IS 'Geographic service regions & municipal areas';

-- Table: network_service_categories
CREATE TABLE IF NOT EXISTS network_service_categories (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    slug VARCHAR(100) UNIQUE NOT NULL,
    icon_class VARCHAR(100) NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
COMMENT ON TABLE network_service_categories IS 'Service catalogs (e.g. Nails art, hair styling, aircon repair)';

-- =========================================================================
-- 2. ACCOUNTS & PROFILES
-- =========================================================================

-- Table: network_profiles
CREATE TABLE IF NOT EXISTS network_profiles (
    user_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(100) UNIQUE NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    avatar TEXT NULL,
    cover_photo TEXT NULL,
    headline VARCHAR(255) NULL,
    bio TEXT NULL,
    location_id INT REFERENCES network_locations(id) ON DELETE SET NULL,
    role VARCHAR(50) NOT NULL CHECK (role IN ('job_seeker', 'employer', 'provider', 'local_business', 'client', 'admin')),
    skills VARCHAR(255)[] NULL,
    experience JSONB NULL,
    portfolio_media JSONB NULL,
    salary_expect VARCHAR(100) NULL,
    is_verified BOOLEAN DEFAULT FALSE,
    is_demo BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
COMMENT ON TABLE network_profiles IS 'Candidate & Provider profiles';

-- Table: network_business_profiles
CREATE TABLE IF NOT EXISTS network_business_profiles (
    user_id UUID PRIMARY KEY REFERENCES network_profiles(user_id) ON DELETE CASCADE,
    business_name VARCHAR(255) NOT NULL,
    slug VARCHAR(100) UNIQUE NOT NULL,
    industry_id INT REFERENCES network_industries(id) ON DELETE SET NULL,
    logo TEXT NULL,
    banner TEXT NULL,
    address TEXT NULL,
    phone VARCHAR(50) NULL,
    is_claimed BOOLEAN DEFAULT TRUE,
    google_place_id VARCHAR(255) NULL,
    is_demo BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
COMMENT ON TABLE network_business_profiles IS 'Business/Merchant profile details';

-- =========================================================================
-- 3. CVS & JOBS MARKETPLACE
-- =========================================================================

-- Table: network_cvs
CREATE TABLE IF NOT EXISTS network_cvs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES network_profiles(user_id) ON DELETE CASCADE,
    pdf_url TEXT NULL,
    cv_json JSONB NULL,
    is_public BOOLEAN DEFAULT TRUE,
    is_demo BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
COMMENT ON TABLE network_cvs IS 'Candidate uploaded or digital resumes';

-- Table: network_job_posts
CREATE TABLE IF NOT EXISTS network_job_posts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    employer_id UUID NOT NULL REFERENCES network_profiles(user_id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    industry_id INT NOT NULL REFERENCES network_industries(id),
    location_id INT NOT NULL REFERENCES network_locations(id),
    salary_min DECIMAL(15,2) NULL,
    salary_max DECIMAL(15,2) NULL,
    employment_type VARCHAR(50) NOT NULL CHECK (employment_type IN ('full_time', 'part_time', 'shift_work', 'commission')),
    status VARCHAR(50) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'filled', 'closed', 'paused')),
    is_urgent BOOLEAN DEFAULT FALSE,
    is_demo BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
COMMENT ON TABLE network_job_posts IS 'Hiring vacancy specifications';

-- Table: network_job_applications
CREATE TABLE IF NOT EXISTS network_job_applications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID NOT NULL REFERENCES network_job_posts(id) ON DELETE CASCADE,
    candidate_id UUID NOT NULL REFERENCES network_profiles(user_id) ON DELETE CASCADE,
    cv_id UUID REFERENCES network_cvs(id) ON DELETE SET NULL,
    cover_letter TEXT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'reviewed', 'shortlisted', 'rejected', 'hired')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
COMMENT ON TABLE network_job_applications IS 'Resume submissions tracking table';

-- =========================================================================
-- 4. SERVICES DIRECTORY
-- =========================================================================

-- Table: network_service_listings
CREATE TABLE IF NOT EXISTS network_service_listings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider_id UUID NOT NULL REFERENCES network_profiles(user_id) ON DELETE CASCADE,
    category_id INT NOT NULL REFERENCES network_service_categories(id),
    title VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    price DECIMAL(15,2) NOT NULL DEFAULT 0.0,
    location_id INT NOT NULL REFERENCES network_locations(id),
    status VARCHAR(50) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused', 'inactive')),
    is_demo BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
COMMENT ON TABLE network_service_listings IS 'Services published by providers';

-- Table: network_service_requests
CREATE TABLE IF NOT EXISTS network_service_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    listing_id UUID NOT NULL REFERENCES network_service_listings(id) ON DELETE CASCADE,
    client_id UUID NOT NULL REFERENCES network_profiles(user_id) ON DELETE CASCADE,
    status VARCHAR(50) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'accepted', 'scheduled', 'completed', 'cancelled')),
    proposed_date TIMESTAMP WITH TIME ZONE NOT NULL,
    notes TEXT NULL,
    is_demo BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
COMMENT ON TABLE network_service_requests IS 'Bookings/Inquiries generated for services';

-- =========================================================================
-- 5. REVIEWS, COMMUNITY FEED, AND CHATS
-- =========================================================================

-- Table: network_reviews
CREATE TABLE IF NOT EXISTS network_reviews (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    target_user_id UUID NOT NULL REFERENCES network_profiles(user_id) ON DELETE CASCADE,
    reviewer_id UUID NOT NULL REFERENCES network_profiles(user_id) ON DELETE CASCADE,
    rating INT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment TEXT NULL,
    is_google_sync BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
COMMENT ON TABLE network_reviews IS 'Verified user review timeline';

-- Table: network_posts
CREATE TABLE IF NOT EXISTS network_posts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    author_id UUID NOT NULL REFERENCES network_profiles(user_id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    industry_id INT REFERENCES network_industries(id) ON DELETE SET NULL,
    is_demo BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
COMMENT ON TABLE network_posts IS 'Community discussions and text posts';

-- Table: network_follows
CREATE TABLE IF NOT EXISTS network_follows (
    follower_id UUID NOT NULL REFERENCES network_profiles(user_id) ON DELETE CASCADE,
    followed_id UUID NOT NULL REFERENCES network_profiles(user_id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    PRIMARY KEY (follower_id, followed_id)
);
COMMENT ON TABLE network_follows IS 'Profile connection indexing table';

-- Table: network_messages
CREATE TABLE IF NOT EXISTS network_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sender_id UUID NOT NULL REFERENCES network_profiles(user_id) ON DELETE CASCADE,
    receiver_id UUID NOT NULL REFERENCES network_profiles(user_id) ON DELETE CASCADE,
    message TEXT NOT NULL,
    is_read BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
COMMENT ON TABLE network_messages IS 'Direct in-app messages';

-- Table: network_notifications
CREATE TABLE IF NOT EXISTS network_notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES network_profiles(user_id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    link TEXT NULL,
    is_read BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
COMMENT ON TABLE network_notifications IS 'Dynamic platform event notifications';

-- =========================================================================
-- 6. ANALYTICS, SEEDING & GROWTH ENGAGEMENT
-- =========================================================================

-- Table: network_growth_events
CREATE TABLE IF NOT EXISTS network_growth_events (
    id SERIAL PRIMARY KEY,
    event_type VARCHAR(100) NOT NULL,
    metadata JSONB NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
COMMENT ON TABLE network_growth_events IS 'Referral metrics and platform analytics outbox';

-- Table: network_seed_entities
CREATE TABLE IF NOT EXISTS network_seed_entities (
    id SERIAL PRIMARY KEY,
    entity_type VARCHAR(100) NOT NULL, -- e.g. 'profile', 'job', 'service'
    entity_id UUID NOT NULL,
    seeder_label VARCHAR(100) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
COMMENT ON TABLE network_seed_entities IS 'Diagnostic directory tracking demo seeder actions';

-- =========================================================================
-- 7. INDEX STRUCTURES (FILTER OPTIMIZATION)
-- =========================================================================

-- Profiles Indexes
CREATE INDEX IF NOT EXISTS idx_net_profiles_role ON network_profiles(role);
CREATE INDEX IF NOT EXISTS idx_net_profiles_loc ON network_profiles(location_id);
CREATE INDEX IF NOT EXISTS idx_net_profiles_demo ON network_profiles(is_demo);

-- Job Posts Indexes
CREATE INDEX IF NOT EXISTS idx_net_job_posts_loc ON network_job_posts(location_id);
CREATE INDEX IF NOT EXISTS idx_net_job_posts_ind ON network_job_posts(industry_id);
CREATE INDEX IF NOT EXISTS idx_net_job_posts_status ON network_job_posts(status);
CREATE INDEX IF NOT EXISTS idx_net_job_posts_demo ON network_job_posts(is_demo);
CREATE INDEX IF NOT EXISTS idx_net_job_posts_created ON network_job_posts(created_at DESC);

-- Job Applications Indexes
CREATE INDEX IF NOT EXISTS idx_net_job_apps_job ON network_job_applications(job_id);
CREATE INDEX IF NOT EXISTS idx_net_job_apps_candidate ON network_job_applications(candidate_id);

-- Service Listings Indexes
CREATE INDEX IF NOT EXISTS idx_net_service_list_provider ON network_service_listings(provider_id);
CREATE INDEX IF NOT EXISTS idx_net_service_list_cat ON network_service_listings(category_id);
CREATE INDEX IF NOT EXISTS idx_net_service_list_loc ON network_service_listings(location_id);
CREATE INDEX IF NOT EXISTS idx_net_service_list_status ON network_service_listings(status);
CREATE INDEX IF NOT EXISTS idx_net_service_list_demo ON network_service_listings(is_demo);
CREATE INDEX IF NOT EXISTS idx_net_service_list_created ON network_service_listings(created_at DESC);

-- Community Feed Indexes
CREATE INDEX IF NOT EXISTS idx_net_posts_author ON network_posts(author_id);
CREATE INDEX IF NOT EXISTS idx_net_posts_created ON network_posts(created_at DESC);

-- Reviews Indexes
CREATE INDEX IF NOT EXISTS idx_net_reviews_target ON network_reviews(target_user_id);

-- Messages & Notifications Indexes
CREATE INDEX IF NOT EXISTS idx_net_messages_chat ON network_messages(sender_id, receiver_id);
CREATE INDEX IF NOT EXISTS idx_net_messages_receiver ON network_messages(receiver_id);
CREATE INDEX IF NOT EXISTS idx_net_messages_created ON network_messages(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_net_notifications_created ON network_notifications(created_at DESC);


-- =========================================================================
-- 8. AUTOMATIC TIMESTAMPS MODIFICATION TRIGGER
-- =========================================================================

-- Trigger function definition
CREATE OR REPLACE FUNCTION update_modified_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply triggers
CREATE TRIGGER update_net_profiles_modtime BEFORE UPDATE ON network_profiles FOR EACH ROW EXECUTE FUNCTION update_modified_column();
CREATE TRIGGER update_net_biz_profiles_modtime BEFORE UPDATE ON network_business_profiles FOR EACH ROW EXECUTE FUNCTION update_modified_column();
CREATE TRIGGER update_net_cvs_modtime BEFORE UPDATE ON network_cvs FOR EACH ROW EXECUTE FUNCTION update_modified_column();
CREATE TRIGGER update_net_job_posts_modtime BEFORE UPDATE ON network_job_posts FOR EACH ROW EXECUTE FUNCTION update_modified_column();
CREATE TRIGGER update_net_job_apps_modtime BEFORE UPDATE ON network_job_applications FOR EACH ROW EXECUTE FUNCTION update_modified_column();
CREATE TRIGGER update_net_service_list_modtime BEFORE UPDATE ON network_service_listings FOR EACH ROW EXECUTE FUNCTION update_modified_column();
CREATE TRIGGER update_net_service_req_modtime BEFORE UPDATE ON network_service_requests FOR EACH ROW EXECUTE FUNCTION update_modified_column();
CREATE TRIGGER update_net_posts_modtime BEFORE UPDATE ON network_posts FOR EACH ROW EXECUTE FUNCTION update_modified_column();

-- =========================================================================
-- 9. PROPOSED ROW LEVEL SECURITY (RLS) POLICIES
-- =========================================================================

/*
-- NOTE: Uncomment and run these statements only once Row Level Security configuration is officially locked down

ALTER TABLE network_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE network_business_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE network_cvs ENABLE ROW LEVEL SECURITY;
ALTER TABLE network_job_posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE network_job_applications ENABLE ROW LEVEL SECURITY;
ALTER TABLE network_service_listings ENABLE ROW LEVEL SECURITY;
ALTER TABLE network_service_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE network_posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE network_follows ENABLE ROW LEVEL SECURITY;
ALTER TABLE network_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE network_notifications ENABLE ROW LEVEL SECURITY;

-- 1. Public Read Profiles
CREATE POLICY "Public profiles can be read by anyone" ON network_profiles
    FOR SELECT USING (TRUE);

-- 2. Owner Write Profile
CREATE POLICY "Profiles can only be edited by owner" ON network_profiles
    FOR UPDATE USING (auth.uid() = user_id);

-- 3. Candidate Private CV Read
CREATE POLICY "Candidates can read their own CVs, employers read public CVs" ON network_cvs
    FOR SELECT USING (auth.uid() = user_id OR is_public = TRUE);

-- 4. Direct Messages Security
CREATE POLICY "Only sender and receiver can read messages" ON network_messages
    FOR SELECT USING (auth.uid() = sender_id OR auth.uid() = receiver_id);
*/
