import sys
import os

# Add root folder to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from supabase_client import supabase, SUPABASE_STATUS

print(f"Supabase status: {SUPABASE_STATUS}")

try:
    res = supabase.table('system_settings').select('*').limit(1).execute()
    print("SUCCESS: system_settings table exists and is accessible!")
    print(f"Data: {res.data}")
except Exception as e:
    print(f"FAIL: system_settings table query failed: {str(e)}")
