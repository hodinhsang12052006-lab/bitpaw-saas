from supabase_client import supabase, SUPABASE_STATUS

class SupabaseRuntimeAdapter:
    @staticmethod
    def get_business_mode(business_id=None):
        """Reads industry mode for current tenant from Supabase system_settings or defaults to retail."""
        if SUPABASE_STATUS == "CONNECTED" and business_id:
            try:
                res = supabase.table('system_settings').select('value').eq('key', 'business_mode').eq('business_id', business_id).execute()
                if res.data:
                    return res.data[0]['value']
            except Exception as e:
                print(f"[!] Supabase business mode load failed: {str(e)}")
        return "retail"

    @staticmethod
    def log_user_action(user_email, action, description, ip_address, business_id=None):
        """Logs user logs cleanly to Supabase user_logs or fallbacks silently."""
        if SUPABASE_STATUS == "CONNECTED":
            try:
                supabase.table('user_logs').insert({
                    'user_email': user_email,
                    'action': action,
                    'description': description,
                    'ip_address': ip_address,
                    'business_id': business_id
                }).execute()
            except Exception as e:
                print(f"[!] Supabase user action logging failed: {str(e)}")

    @staticmethod
    def get_products(channel_type, business_id=None):
        """Gets active products by channel/industry category from Supabase or returns empty catalog."""
        if SUPABASE_STATUS == "CONNECTED":
            try:
                query = supabase.table('products').select('*').eq('is_active', 1).eq('channel_type', channel_type)
                if business_id:
                    query = query.eq('business_id', business_id)
                res = query.execute()
                return res.data or []
            except Exception as e:
                print(f"[!] Supabase products loading failed: {str(e)}")
        return []

    @staticmethod
    def get_expenses(business_id=None):
        """Gets expense records dynamically from Supabase."""
        if SUPABASE_STATUS == "CONNECTED":
            try:
                query = supabase.table('expenses').select('*').order('expense_date', desc=True)
                if business_id:
                    query = query.eq('business_id', business_id)
                res = query.execute()
                return res.data or []
            except Exception as e:
                print(f"[!] Supabase expenses loading failed: {str(e)}")
        return []
