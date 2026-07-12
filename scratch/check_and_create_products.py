import sys
import os

# Bind workspace path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from supabase_client import supabase

def main():
    print("Checking existing products on Supabase...")
    try:
        res = supabase.table('products').select('*').eq('channel_type', 'retail').eq('is_active', 1).execute()
        products = res.data
        print(f"Found {len(products)} active retail products.")
        for p in products:
            print(f" - ID: {p['id']}, Name: {p['name']}, Price: {p['price']}, Stock: {p['stock']}")
            
        if len(products) == 0:
            print("No active retail products found. Inserting UAT products...")
            uat_products = [
                {
                    'name': 'UAT POS Trà Sữa',
                    'category': 'Đồ uống',
                    'channel_type': 'retail',
                    'stock': 100,
                    'price': 35000.0,
                    'cost_price': 15000.0,
                    'is_active': 1
                },
                {
                    'name': 'UAT POS Bánh Ngọt',
                    'category': 'Đồ ăn vặt',
                    'channel_type': 'retail',
                    'stock': 50,
                    'price': 25000.0,
                    'cost_price': 10000.0,
                    'is_active': 1
                }
            ]
            for prod in uat_products:
                res_insert = supabase.table('products').insert(prod).execute()
                print(f"Inserted: {res_insert.data[0]['name']} with ID {res_insert.data[0]['id']}")
        
        # Kiểm tra danh sách bàn ăn
        print("\nChecking existing dining tables on Supabase...")
        res_tables = supabase.table('dining_tables').select('*').execute()
        tables = res_tables.data
        print(f"Found {len(tables)} dining tables.")
        for t in tables:
            print(f" - Table ID: {t['id']}, Name: {t['name']}, Status: {t['status']}, Token: {t['qr_token']}")
            
    except Exception as e:
        print(f"Error checking/creating products: {str(e)}")

if __name__ == '__main__':
    main()
