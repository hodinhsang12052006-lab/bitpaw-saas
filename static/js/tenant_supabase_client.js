// Preserve original Supabase library reference to prevent client instances in template scripts from overwriting it on window.supabase
if (!window.supabaseLib && window.supabase) {
    window.supabaseLib = window.supabase;
}

// Tạo Supabase client có gắn JWT chứa business_id (lấy từ session Flask hiện tại)
// vào header Authorization, để Postgres RLS phân biệt được tenant nào đang gọi.
// Không có hàm này, mọi request client-side chỉ mang anon key trần -> RLS không lọc được business_id.
//
// url/key: TUỲ CHỌN — nếu bỏ trống, hàm tự lấy từ window.ENV (bơm bởi Jinja2 lúc render HTML,
// xem base.html/super_admin.html) thay vì phải hardcode hoặc truyền tay ở từng trang. Các trang
// cũ vẫn truyền thẳng 2 tham số này thì vẫn chạy y như trước, không phá vỡ gì.
async function createTenantSupabaseClient(supabaseUrl, supabaseAnonKey) {
    supabaseUrl = supabaseUrl || (window.ENV && window.ENV.SUPABASE_URL);
    supabaseAnonKey = supabaseAnonKey || (window.ENV && window.ENV.SUPABASE_KEY);
    if (!supabaseUrl || !supabaseAnonKey) {
        throw new Error('Thiếu SUPABASE_URL/SUPABASE_KEY: không có tham số truyền vào lẫn window.ENV.');
    }

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
    
    const lib = window.supabaseLib || window.supabase;
    return lib.createClient(supabaseUrl, supabaseAnonKey, options);
}
