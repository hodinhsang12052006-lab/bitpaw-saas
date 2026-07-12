-- SUPABASE & SQLITE RESILIENT AI NURTURING PLATFORM SCHEMA
-- Design: Scope all tables by multi-tenant business_id

-- 1. Platform Connections: Manage status/connections (Zalo, FB, WhatsApp, etc.)
CREATE TABLE IF NOT EXISTS platform_connections (
    id TEXT PRIMARY KEY,
    business_id TEXT NOT NULL,
    platform TEXT NOT NULL, -- 'messenger', 'zalo_oa', 'whatsapp', 'webform'
    connection_status TEXT DEFAULT 'DISCONNECTED', -- 'CONNECTED', 'DISCONNECTED', 'PAUSED'
    config_data TEXT, -- JSON configurations / Access Tokens
    connected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Customer Profiles: central customer repository
CREATE TABLE IF NOT EXISTS customer_profiles (
    id TEXT PRIMARY KEY,
    business_id TEXT NOT NULL,
    name TEXT NOT NULL,
    phone TEXT,
    email TEXT,
    industry TEXT, -- e.g., 'nail', 'spa', 'fnb', etc.
    source_platform TEXT, -- e.g. 'pos', 'booking', 'messenger', 'zalo_oa'
    last_purchase_at TIMESTAMP,
    total_spending REAL DEFAULT 0,
    services_of_interest TEXT, -- comma-separated
    nurturing_status TEXT DEFAULT 'NEW', -- 'NEW', 'REGULAR', 'HIBERNATING', 'NEEDS_CARE', 'ABOUT_TO_REPURCHASE', 'CHURN_RISK'
    ai_notes TEXT,
    potential_score REAL DEFAULT 50, -- 1-100 score
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 3. Customer Tags: specific label tags (e.g. VIP, Churn risk, Cận ngày sinh nhật)
CREATE TABLE IF NOT EXISTS customer_tags (
    id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    tag TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 4. Customer Events: log events for AI trigger parsing
CREATE TABLE IF NOT EXISTS customer_events (
    id TEXT PRIMARY KEY,
    business_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    event_type TEXT NOT NULL, -- 'checkout', 'booking', 'opt-out', 'visit'
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 5. Message Threads: chat transcripts from multi-channels
CREATE TABLE IF NOT EXISTS message_threads (
    id TEXT PRIMARY KEY,
    business_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    channel TEXT NOT NULL, -- 'messenger', 'zalo', 'whatsapp'
    sender_role TEXT NOT NULL, -- 'AI', 'CUSTOMER', 'OWNER'
    message_content TEXT NOT NULL,
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 6. Nurturing Segments: categorized cohorts
CREATE TABLE IF NOT EXISTS nurturing_segments (
    id TEXT PRIMARY KEY,
    business_id TEXT NOT NULL,
    name TEXT NOT NULL, -- e.g. 'Khách hàng VIP 30 ngày chưa quay lại'
    filter_criteria TEXT, -- JSON query criteria
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 7. Nurturing Campaigns: marketing campaigns details
CREATE TABLE IF NOT EXISTS nurturing_campaigns (
    id TEXT PRIMARY KEY,
    business_id TEXT NOT NULL,
    name TEXT NOT NULL,
    target_segment_id TEXT,
    campaign_goal TEXT, -- 'RECALL', 'UPSELL', 'REVIEW', 'BIRTHDAY', 'PROMO'
    channel TEXT, -- 'FB', 'ZALO', 'WHATSAPP', 'SMS'
    tone TEXT, -- 'friendly', 'premium', 'close', 'urgent', 'professional'
    is_active INTEGER DEFAULT 1, -- 0: Inactive, 1: Active
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 8. Campaign Steps: sequential schedule rules (3, 7, 14 days)
CREATE TABLE IF NOT EXISTS campaign_steps (
    id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL,
    day_delay INTEGER NOT NULL, -- 3, 7, 14 days
    step_title TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 9. Message Templates: dynamic text templates
CREATE TABLE IF NOT EXISTS message_templates (
    id TEXT PRIMARY KEY,
    business_id TEXT NOT NULL,
    industry TEXT NOT NULL,
    campaign_goal TEXT NOT NULL,
    tone TEXT NOT NULL,
    template_text TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 10. Campaign Messages & Approval Queue: owner must approve before dispatching
CREATE TABLE IF NOT EXISTS campaign_messages (
    id TEXT PRIMARY KEY,
    business_id TEXT NOT NULL,
    campaign_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    step_delay INTEGER NOT NULL,
    message_body TEXT NOT NULL,
    approval_status TEXT DEFAULT 'PENDING', -- 'PENDING', 'APPROVED', 'REJECTED'
    scheduled_send_at TIMESTAMP,
    sent_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 11. Message Logs: history of sent messaging
CREATE TABLE IF NOT EXISTS message_logs (
    id TEXT PRIMARY KEY,
    business_id TEXT NOT NULL,
    customer_id TEXT,
    recipient_address TEXT,
    channel TEXT NOT NULL,
    message_content TEXT NOT NULL,
    delivery_status TEXT DEFAULT 'SENT', -- 'SENT', 'DELIVERED', 'FAILED'
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 12. AI Recommendations: customized insights for owners
CREATE TABLE IF NOT EXISTS ai_recommendations (
    id TEXT PRIMARY KEY,
    business_id TEXT NOT NULL,
    insight_type TEXT NOT NULL, -- 'CHURN_ALERT', 'CAMPAIGN_SUGGESTION', 'REVENUE_OPTIMIZE'
    recommendation_text TEXT NOT NULL,
    is_resolved INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
