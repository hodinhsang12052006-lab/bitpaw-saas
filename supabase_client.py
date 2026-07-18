import os
from supabase import create_client

class DummySession:
    def __init__(self):
        self.access_token = "mock-access-token-12345"

class DummyUser:
    def __init__(self, email="mock@test.com", id="mock-admin-uuid"):
        self.id = id
        self.email = email

class DummyAuthResponse:
    def __init__(self, email="mock@test.com", id="mock-admin-uuid"):
        self.user = DummyUser(email, id)
        self.session = DummySession()

# Resilient dummy client to fallback gracefully if Supabase URL/Key is missing or connection fails
class DummySupabaseClient:
    def table(self, table_name, *args, **kwargs):
        class DummyTable:
            def __init__(self, name):
                self.name = name
            def select(self, *args, **kwargs): return self
            def insert(self, *args, **kwargs): return self
            def update(self, *args, **kwargs): return self
            def upsert(self, *args, **kwargs): return self
            def delete(self, *args, **kwargs): return self
            def eq(self, *args, **kwargs): return self
            def gte(self, *args, **kwargs): return self
            def lte(self, *args, **kwargs): return self
            def order(self, *args, **kwargs): return self
            def limit(self, *args, **kwargs): return self
            def execute(self, *args, **kwargs):
                class MockResult:
                    def __init__(self, data):
                        self.data = data
                return MockResult([])
        return DummyTable(table_name)
    
    @property
    def auth(self):
        class DummyAuth:
            def sign_up(self, credentials, *args, **kwargs):
                email = credentials.get("email", "mock@test.com")
                return DummyAuthResponse(email=email)
            def sign_in_with_password(self, credentials, *args, **kwargs):
                email = credentials.get("email", "mock@test.com")
                return DummyAuthResponse(email=email)
        return DummyAuth()

# Custom environment loader to parse .env line-by-line without external dependencies
def load_env_file():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    if os.path.exists(env_path):
        print("[*] Reading environment parameters from local '.env' file...")
        try:
            with open(env_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        k, v = line.split('=', 1)
                        # Strip spacing and optional surrounding quotes
                        k_clean = k.strip()
                        v_clean = v.strip().strip('"').strip("'")
                        os.environ[k_clean] = v_clean
        except Exception as e:
            print(f"[!] Warning: Failed parsing '.env' file: {str(e)}")

# Initialize environment variables
load_env_file()

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

supabase = None
supabase_admin = None
SUPABASE_STATUS = "NOT CONFIGURED"
NEED_RUN_SUPABASE_SCHEMA = "NO"

if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        print(f"[*] Supabase client object created. (Target: {SUPABASE_URL}) Probing connection...")

        # Probe database connection để xác nhận kết nối THẬT SỰ hoạt động (không chỉ khởi tạo
        # object thành công). Nếu host giả (vd: mock.supabase.co) hoặc mất mạng, request này sẽ
        # raise lỗi kết nối (DNS/timeout/connection refused) và status phải chuyển sang lỗi,
        # tuyệt đối không được giữ nguyên "CONNECTED" đánh lừa phần còn lại của hệ thống.
        try:
            # Query system_settings to see if the table exists
            res = supabase.table('system_settings').select('*').limit(1).execute()
            SUPABASE_STATUS = "CONNECTED"
            print("[*] Supabase database schema probe: SUCCESS. Tables exist.")
        except Exception as probe_err:
            err_msg = str(probe_err).lower()
            # Detect missing relation / tables in PostgreSQL response — kết nối vẫn hoạt động,
            # chỉ là schema chưa được tạo, nên KHÔNG coi là lỗi kết nối.
            if "relation" in err_msg or "does not exist" in err_msg or "404" in err_msg or "not found" in err_msg:
                SUPABASE_STATUS = "CONNECTED"
                NEED_RUN_SUPABASE_SCHEMA = "YES"
                print(f"[!] Warning: Supabase database schema probe failed: {str(probe_err)}")
                print("[!] Action Required: Supabase connection active but required tables are missing. NEED_RUN_SUPABASE_SCHEMA = YES")
            else:
                # Lỗi kết nối thật sự (mất mạng, host giả/không tồn tại, timeout, auth sai...)
                SUPABASE_STATUS = "DISCONNECTED"
                supabase = DummySupabaseClient()
                print(f"[!] Critical: Supabase connection probe failed -> {str(probe_err)}")
                print("[!] Supabase marked DISCONNECTED. Falling back to DummySupabaseClient.")
    except Exception as init_err:
        print(f"[!] Critical: Failed to establish Supabase client connection -> {str(init_err)}")
        SUPABASE_STATUS = "DISCONNECTED"
        supabase = DummySupabaseClient()
else:
    print("[!] Warning: Supabase credentials not found in environment or fallback keys.")
    SUPABASE_STATUS = "NOT CONFIGURED"
    supabase = DummySupabaseClient()

# Initialize Supabase Admin Client using Service Role Key for server-side operations (e.g. backup)
if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY:
    try:
        supabase_admin = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
        print("[*] Supabase admin client successfully initialized with service role key.")
    except Exception as admin_err:
        print(f"[!] Warning: Failed to establish Supabase admin client connection -> {str(admin_err)}")
        supabase_admin = None
else:
    print("[!] Warning: SUPABASE_SERVICE_ROLE_KEY not found in environment variables. Backup storage operations will be disabled.")
    supabase_admin = None

