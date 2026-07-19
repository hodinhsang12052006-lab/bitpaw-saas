from mongo_client import db, MONGO_STATUS, next_mongo_id

class SupabaseRuntimeAdapter:
    @staticmethod
    def get_business_mode(business_id=None):
        """Reads industry mode for current tenant from MongoDB system_settings or defaults to retail."""
        if MONGO_STATUS == "CONNECTED" and business_id:
            try:
                doc = db.system_settings.find_one(
                    {'key': 'business_mode', 'business_id': business_id}, {'value': 1, '_id': 0}
                )
                if doc:
                    return doc['value']
            except Exception as e:
                print(f"[!] MongoDB business mode load failed: {str(e)}")
        return "retail"

    @staticmethod
    def log_user_action(user_email, action, description, ip_address, business_id=None):
        """Logs user logs cleanly to MongoDB user_logs or fallbacks silently."""
        if MONGO_STATUS == "CONNECTED":
            try:
                db.user_logs.insert_one({
                    'id': next_mongo_id('user_logs'),
                    'user_email': user_email,
                    'action': action,
                    'description': description,
                    'ip_address': ip_address,
                    'business_id': business_id
                })
            except Exception as e:
                print(f"[!] MongoDB user action logging failed: {str(e)}")

    @staticmethod
    def get_products(channel_type, business_id=None):
        """Gets active products by channel/industry category from MongoDB or returns empty catalog."""
        if MONGO_STATUS == "CONNECTED":
            try:
                query_filter = {'is_active': 1, 'channel_type': channel_type}
                if business_id:
                    query_filter['business_id'] = business_id
                return list(db.products.find(query_filter, {'_id': 0}))
            except Exception as e:
                print(f"[!] MongoDB products loading failed: {str(e)}")
        return []

    @staticmethod
    def get_expenses(business_id=None):
        """Gets expense records dynamically from MongoDB."""
        if MONGO_STATUS == "CONNECTED":
            try:
                query_filter = {}
                if business_id:
                    query_filter['business_id'] = business_id
                return list(db.expenses.find(query_filter, {'_id': 0}).sort('expense_date', -1))
            except Exception as e:
                print(f"[!] MongoDB expenses loading failed: {str(e)}")
        return []
