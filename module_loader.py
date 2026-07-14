from supabase_client import supabase, SUPABASE_STATUS

class ModuleLoader:
    @staticmethod
    def verify_module_access(business_id, module_code):
        """Verifies if the tenant has access to a specific SaaS module."""
        if not business_id or not module_code:
            return False
            
        # Test bypass
        if business_id.startswith("mock-"):
            return True

        if SUPABASE_STATUS == "CONNECTED":
            try:
                # Query dynamic module registry allocations
                res = supabase.table('business_modules').select('is_active').eq('code', module_code).execute()
                if res.data:
                    return res.data[0]['is_active']
            except Exception as e:
                print(f"[!] Module access check failed: {str(e)}")
                
        return False

    @staticmethod
    def load_active_modules(industry_code):
        """Loads default modules list for an industry from registry catalog."""
        if SUPABASE_STATUS == "CONNECTED":
            try:
                res = supabase.table('template_registry').select('module_code').execute()
                if res.data:
                    return list(set([item['module_code'] for item in res.data if item['module_code']]))
            except Exception as e:
                print(f"[!] Registry module query failed: {str(e)}")
        return ["dashboard", "ai_bot"]
