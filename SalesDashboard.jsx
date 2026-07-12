import React, { useState } from 'react';

const SalesDashboard = () => {
  // Dữ liệu mẫu tạm thời (Sau này sẽ gọi API từ Backend)
  const [products] = useState([
    { id: 1, name: 'Giấy in Ford A4 70gsm', stock: 500, price: '60.000 đ' },
    { id: 2, name: 'Mực in Offset Xanh Cyan', stock: 50, price: '180.000 đ' },
    { id: 3, name: 'Decal nhựa sữa', stock: 1000, price: '8.500 đ' },
  ]);

  return (
    <div style={{ backgroundColor: '#0f111a', minHeight: '100vh', padding: '24px', color: '#fff', fontFamily: 'sans-serif' }}>
      
      {/* Header */}
      <div style={{ marginBottom: '32px' }}>
        <h1 style={{ fontSize: '28px', fontWeight: 'bold', margin: '0 0 8px 0' }}>Quản lý Bán Hàng 🛍️</h1>
        <p style={{ color: '#8b949e', margin: 0 }}>Theo dõi doanh thu và xuất nhập kho BitPaw OS.</p>
      </div>

      {/* Cards Thống kê (Thiết kế giống hình) */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '20px', marginBottom: '32px' }}>
        
        {/* Card 1 */}
        <div style={{ background: 'linear-gradient(135deg, #1e1b38 0%, #151828 100%)', padding: '24px', borderRadius: '12px', border: '1px solid #2a2c3d' }}>
          <div style={{ color: '#20d3d5', fontSize: '14px', marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span>📦</span> TỔNG SẢN PHẨM
          </div>
          <div style={{ fontSize: '32px', fontWeight: 'bold' }}>{products.length}</div>
        </div>

        {/* Card 2 */}
        <div style={{ background: 'linear-gradient(135deg, #1e1b38 0%, #151828 100%)', padding: '24px', borderRadius: '12px', border: '1px solid #2a2c3d' }}>
          <div style={{ color: '#a55eea', fontSize: '14px', marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span>💰</span> DOANH THU HÔM NAY
          </div>
          <div style={{ fontSize: '32px', fontWeight: 'bold' }}>0 đ</div>
        </div>

        {/* Card 3 */}
        <div style={{ background: 'linear-gradient(135deg, #1e1b38 0%, #151828 100%)', padding: '24px', borderRadius: '12px', border: '1px solid #2a2c3d' }}>
          <div style={{ color: '#ff6b6b', fontSize: '14px', marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span>📉</span> CHI TIÊU THÁNG
          </div>
          <div style={{ fontSize: '32px', fontWeight: 'bold' }}>0 đ</div>
        </div>
      </div>

      {/* Bảng Danh sách sản phẩm */}
      <div style={{ background: '#151828', borderRadius: '12px', padding: '24px', border: '1px solid #2a2c3d' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
          <h2 style={{ fontSize: '18px', margin: 0 }}>Kho Hàng Hiện Tại</h2>
          <button style={{ background: '#20d3d5', color: '#000', border: 'none', padding: '8px 16px', borderRadius: '6px', fontWeight: 'bold', cursor: 'pointer' }}>
            + Thêm Sản Phẩm
          </button>
        </div>

        <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid #2a2c3d', color: '#8b949e' }}>
              <th style={{ padding: '12px 0' }}>ID</th>
              <th style={{ padding: '12px 0' }}>Tên Sản Phẩm</th>
              <th style={{ padding: '12px 0' }}>Tồn Kho</th>
              <th style={{ padding: '12px 0' }}>Giá Bán</th>
              <th style={{ padding: '12px 0' }}>Thao Tác</th>
            </tr>
          </thead>
          <tbody>
            {products.map(product => (
              <tr key={product.id} style={{ borderBottom: '1px solid #2a2c3d' }}>
                <td style={{ padding: '16px 0' }}>#{product.id}</td>
                <td style={{ padding: '16px 0', fontWeight: '500' }}>{product.name}</td>
                <td style={{ padding: '16px 0', color: '#20d3d5' }}>{product.stock}</td>
                <td style={{ padding: '16px 0' }}>{product.price}</td>
                <td style={{ padding: '16px 0' }}>
                  <button style={{ background: 'transparent', color: '#20d3d5', border: '1px solid #20d3d5', padding: '4px 12px', borderRadius: '4px', cursor: 'pointer' }}>Tạo Đơn</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

    </div>
  );
};

export default SalesDashboard;