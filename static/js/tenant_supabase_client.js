// Tạo Supabase client có gắn JWT chứa business_id (lấy từ session Flask hiện tại)
// vào header Authorization, để Postgres RLS phân biệt được tenant nào đang gọi.
// Không có hàm này, mọi request client-side chỉ mang anon key trần -> RLS không lọc được business_id.
async function createTenantSupabaseClient(supabaseUrl, supabaseAnonKey) {
    let token = null;
    try {
        const res = await fetch('/api/session/supabase_token', { credentials: 'same-origin' });
        const json = await res.json();
        if (json && json.success) {
            token = json.token;
        } else {
            console.error('Không lấy được tenant token:', json && json.error);
        }
    } catch (e) {
        console.error('Lỗi khi gọi /api/session/supabase_token:', e);
    }

    const options = token
        ? { global: { headers: { Authorization: `Bearer ${token}` } } }
        : {};
    return window.supabase.createClient(supabaseUrl, supabaseAnonKey, options);
}
