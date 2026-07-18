from flask import session
from supabase_client import supabase, SUPABASE_STATUS

class TenantEngine:
    @classmethod
    def get_region_config(cls, business_id=None):
        # Fallback an toàn để không bị lỗi 500
        return {"country": "VN", "currency": "VND"}
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

    @staticmethod
    def get_region_config(business_id):
        """Returns {'country': 'VN'|'US', 'currency': 'VND'|'USD'} for a tenant.

        Multi-region: each business row carries its own country/currency (see
        supabase_schema_patch_us_market_multiregion.sql) — there is no global
        default beyond VN/VND, and no FX conversion happens here or anywhere else.
        Defaults to VN/VND whenever the business can't be resolved (unknown
        business_id, disconnected DB, mock/test session) so existing behavior for
        every current tenant is unchanged.
        """
        default = {"country": "VN", "currency": "VND"}
        if not business_id or SUPABASE_STATUS != "CONNECTED":
            return default
        try:
            res = supabase.table('businesses').select('country, currency').eq('id', business_id).limit(1).execute()
            if res.data:
                row = res.data[0]
                return {
                    "country": row.get('country') or 'VN',
                    "currency": row.get('currency') or 'VND'
                }
        except Exception as e:
            print(f"[!] get_region_config failed for business_id={business_id}: {str(e)}")
        return default
