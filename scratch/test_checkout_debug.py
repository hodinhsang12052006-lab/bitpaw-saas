import sys
import os
import uuid

# Bind workspace path to import supabase_client
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from supabase_client import supabase

def main():
    print("Debugging checkout_table for Table ID 2...")
    table_id = 2
    product_id = 1 # UAT Inventory Product
    
    # 1. Insert a temporary order item into table_orders to guarantee it exists
    print(f"Ensuring there is an item in table_orders for Table ID {table_id}...")
    try:
        # Xóa các orders cũ của bàn này trước
        supabase.table('table_orders').delete().eq('table_id', table_id).execute()
        
        # Insert record mới
        insert_res = supabase.table('table_orders').insert({
            'table_id': table_id,
            'product_id': product_id,
            'quantity': 2
        }).execute()
        print(f"Inserted item into table_orders: {insert_res.data}")
    except Exception as e:
        print(f"Failed inserting to table_orders: {str(e)}")
        sys.exit(1)
        
    # 2. Chạy thử logic checkout
    orders = supabase.table('table_orders').select('*').eq('table_id', table_id).execute()
    print(f"table_orders query data: {orders.data}")
    
    if orders.data:
        order_code = f"FNB-{uuid.uuid4().hex[:8].upper()}"
        total_bill = 0
        for item in orders.data:
            prod = supabase.table('products').select('price, stock').eq('id', item['product_id']).execute()
            if prod.data:
                price = prod.data[0]['price']
                total_bill += item['quantity'] * price
                new_stock = prod.data[0]['stock'] - item['quantity']
                print(f"Product ID {item['product_id']} price={price}, stock={prod.data[0]['stock']} -> new_stock={new_stock}")
                
        # Thử insert orders
        print("\nTrying to insert into 'orders'...")
        try:
            order_data_to_insert = {
                'order_code': order_code,
                'channel': 'fnb',
                'total_amount': total_bill
            }
            print(f"Payload orders: {order_data_to_insert}")
            order_res = supabase.table('orders').insert(order_data_to_insert).execute()
            print(f"Insert orders success! Data: {order_res.data}")
            order_id = order_res.data[0]['id']
            
            # Thử insert order_items
            for item in orders.data:
                prod = supabase.table('products').select('price').eq('id', item['product_id']).execute()
                price = prod.data[0]['price']
                total_price = item['quantity'] * price
                print(f"Trying to insert into 'order_items' for product {item['product_id']}...")
                item_res = supabase.table('order_items').insert({
                    'order_id': order_id,
                    'product_id': item['product_id'],
                    'quantity': item['quantity'],
                    'price': price,
                    'total_price': total_price
                }).execute()
                print(f"Insert order_item success! Data: {item_res.data}")
                
        except Exception as e:
            print(f"[🔴 ERROR DETECTED DURING CHECKOUT RUNTIME] {str(e)}")

if __name__ == '__main__':
    main()
