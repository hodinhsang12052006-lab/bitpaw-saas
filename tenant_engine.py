from flask import session
from supabase_client import supabase, SUPABASE_STATUS

class TenantEngine:
    @staticmethod
    def resolve_tenant(user_id):
        """Resolves tenant business_id and details based on user_id."""
        if not user_id:
            return None
        
        # Test bypass
        if user_id == "mock-user-123":
            return {
                "business_id": "mock-business-123",
                "business_name": "BitPaw Demo Store",
                "industry_code": session.get('business_mode', 'retail')
            }

        if SUPABASE_STATUS == "CONNECTED":
            try:
                # Query profiles associated with auth user
                res = supabase.table('profiles').select('business_id, role').eq('id', user_id).execute()
                if res.data:
                    prof = res.data[0]
                    b_id = prof['business_id']
                    role = prof['role']
                    
                    # Query business details
                    bus_res = supabase.table('businesses').select('*').eq('id', b_id).execute()
                    if bus_res.data:
                        bus = bus_res.data[0]
                        return {
                            "business_id": b_id,
                            "business_name": bus['name'],
                            "industry_code": bus['industry_code'],
                            "role": role
                        }
            except Exception as e:
                print(f"[!] Tenant resolving failed: {str(e)}")
                
        return None
