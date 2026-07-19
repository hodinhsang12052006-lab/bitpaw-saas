from mongo_client import db, MONGO_STATUS

class ModuleLoader:
    @staticmethod
    def verify_module_access(business_id, module_code):
        """Verifies if the tenant has access to a specific SaaS module."""
        if not business_id or not module_code:
            return False

        if MONGO_STATUS == "CONNECTED":
            try:
                # Query dynamic module registry allocations
                doc = db.business_modules.find_one({'code': module_code}, {'is_active': 1, '_id': 0})
                if doc:
                    return doc['is_active']
            except Exception as e:
                print(f"[!] Module access check failed: {str(e)}")

        return False

    @staticmethod
    def load_active_modules(industry_code):
        """Loads default modules list for an industry from registry catalog."""
        if MONGO_STATUS == "CONNECTED":
            try:
                docs = db.template_registry.find({}, {'module_code': 1, '_id': 0})
                codes = {item['module_code'] for item in docs if item.get('module_code')}
                if codes:
                    return list(codes)
            except Exception as e:
                print(f"[!] Registry module query failed: {str(e)}")
        return ["dashboard", "ai_bot"]
