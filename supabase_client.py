import os
from supabase import create_client

# Resilient dummy client to fallback gracefully if Supabase URL/Key is missing or connection fails
class DummySupabaseClient:
    def table(self, *args, **kwargs):
        class DummyTable:
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
                raise Exception("Supabase database offline or table schema not configured. Local memory bypass active.")
        return DummyTable()
    
    @property
    def auth(self):
        class DummyAuth:
            def sign_up(self, *args, **kwargs):
                raise Exception("Supabase authentication server offline or unconfigured.")
            def sign_in_with_password(self, *args, **kwargs):
                raise Exception("Supabase authentication server offline or unconfigured.")
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

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://iojtglaxgdwsxxalhubx.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImlvanRnbGF4Z2R3c3h4YWxodWJ4Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzc1NjgzNTIsImV4cCI6MjA5MzE0NDM1Mn0.KA7wdsZsK3oA6ybi5Gl_KnkzAKZM-ESI3Eyzx-mipwM")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

supabase = None
supabase_admin = None
SUPABASE_STATUS = "NOT CONFIGURED"
NEED_RUN_SUPABASE_SCHEMA = "NO"

if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        SUPABASE_STATUS = "CONNECTED"
        print(f"[*] Supabase client successfully initialized. (Target: {SUPABASE_URL})")
        
        # Probe database connection to see if schema exists and is accessible
        try:
            # Query system_settings to see if the table exists
            res = supabase.table('system_settings').select('*').limit(1).execute()
            print("[*] Supabase database schema probe: SUCCESS. Tables exist.")
        except Exception as probe_err:
            err_msg = str(probe_err).lower()
            print(f"[!] Warning: Supabase database schema probe failed: {str(probe_err)}")
            # Detect missing relation / tables in PostgreSQL response
            if "relation" in err_msg or "does not exist" in err_msg or "404" in err_msg or "not found" in err_msg:
                NEED_RUN_SUPABASE_SCHEMA = "YES"
                print("[!] Action Required: Supabase connection active but required tables are missing. NEED_RUN_SUPABASE_SCHEMA = YES")
    except Exception as init_err:
        print(f"[!] Critical: Failed to establish Supabase client connection -> {str(init_err)}")
        SUPABASE_STATUS = "NOT CONFIGURED"
        supabase = DummySupabaseClient()
else:
    print("[!] Warning: Supabase credentials not found in environment or fallback keys.")
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

