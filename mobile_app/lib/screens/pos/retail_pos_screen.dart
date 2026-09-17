import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../../models/cart_item_model.dart';
import '../../models/product_model.dart';
import '../../services/api_service.dart';
import '../../services/pos_service.dart';
import '../../services/sales_checkout_service.dart';
import 'barcode_scanner_screen.dart';

/// Màn hình bán hàng cho ngành Retail — mirror retail_pos.html (web): quét mã vạch bằng camera
/// HOẶC gõ tay mã, tự tra cứu qua /api/products/lookup_barcode rồi thêm vào giỏ, thanh toán qua
/// /api/sales/checkout (KHÔNG gán thợ/tip — khớp đúng payload retail_pos.html gửi, chỉ
/// items + payment_method).
class RetailPosScreen extends StatefulWidget {
  const RetailPosScreen({super.key});

  @override
  State<RetailPosScreen> createState() => _RetailPosScreenState();
}

class _RetailPosScreenState extends State<RetailPosScreen> {
  late final PosService _posService;
  late final SalesCheckoutService _checkoutService;
  final _manualCodeController = TextEditingController();

  final List<CartItemModel> _cart = [];
  bool _isLookingUp = false;
  String? _lookupError;

  final _currencyFormat = NumberFormat.currency(locale: 'vi_VN', symbol: 'đ', decimalDigits: 0);

  @override
  void initState() {
    super.initState();
    final apiService = context.read<ApiService>();
    _posService = PosService(apiService);
    _checkoutService = SalesCheckoutService(apiService);
  }

  @override
  void dispose() {
    _manualCodeController.dispose();
    super.dispose();
  }

  double get _cartTotal => _cart.fold(0, (sum, item) => sum + item.lineTotal);

  Future<void> _lookupAndAdd(String barcode) async {
    if (barcode.trim().isEmpty) return;
    setState(() {
      _isLookingUp = true;
      _lookupError = null;
    });
    try {
      final ProductModel? product = await _posService.lookupBarcode(barcode.trim());
      if (!mounted) return;
      if (product == null) {
        setState(() => _lookupError = 'Không tìm thấy sản phẩm với mã vạch "$barcode".');
        return;
      }
      setState(() {
        final existing = _cart.where((c) => c.productId == product.id);
        if (existing.isNotEmpty) {
          existing.first.quantity += 1;
        } else {
          _cart.add(CartItemModel(productId: product.id, name: product.name, price: product.price));
        }
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _lookupError = 'Lỗi tra cứu sản phẩm. Vui lòng thử lại.');
    } finally {
      if (mounted) setState(() => _isLookingUp = false);
    }
  }

  Future<void> _openScanner() async {
    final code = await Navigator.of(context).push<String>(
      MaterialPageRoute(builder: (_) => const BarcodeScannerScreen()),
    );
    if (code != null && mounted) {
      await _lookupAndAdd(code);
    }
  }

  Future<void> _checkout(String paymentMethod) async {
    if (_cart.isEmpty) return;
    final result = await _checkoutService.checkout(items: _cart, paymentMethod: paymentMethod);
    if (!mounted) return;
    if (result.success) {
      setState(() => _cart.clear());
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('${result.message} Tổng: ${_currencyFormat.format(result.totalAmount ?? 0)}'),
          backgroundColor: Colors.green,
        ),
      );
    } else {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(result.message), backgroundColor: Colors.redAccent));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Bán hàng — Retail')),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(16),
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _manualCodeController,
                    style: const TextStyle(color: Colors.white),
                    decoration: InputDecoration(
                      hintText: 'Gõ mã vạch hoặc dùng camera quét',
                      hintStyle: const TextStyle(color: Colors.white38),
                      filled: true,
                      fillColor: Colors.white.withOpacity(0.05),
                      border: OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: BorderSide.none),
                    ),
                    onSubmitted: (value) {
                      _lookupAndAdd(value);
                      _manualCodeController.clear();
                    },
                  ),
                ),
                const SizedBox(width: 8),
                IconButton.filled(
                  onPressed: _openScanner,
                  icon: const Icon(Icons.qr_code_scanner_rounded),
                  style: IconButton.styleFrom(backgroundColor: const Color(0xFF06B6D4), foregroundColor: Colors.black),
                ),
              ],
            ),
          ),
          if (_isLookingUp) const LinearProgressIndicator(color: Color(0xFF06B6D4)),
          if (_lookupError != null)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: Text(_lookupError!, style: const TextStyle(color: Colors.redAccent, fontSize: 13)),
            ),
          const SizedBox(height: 8),
          Expanded(
            child: _cart.isEmpty
                ? const Center(child: Text('Giỏ hàng trống — quét hoặc gõ mã vạch để thêm sản phẩm.', style: TextStyle(color: Colors.white38)))
                : ListView.separated(
                    padding: const EdgeInsets.symmetric(horizontal: 16),
                    itemCount: _cart.length,
                    separatorBuilder: (_, __) => const Divider(color: Colors.white12),
                    itemBuilder: (context, index) {
                      final item = _cart[index];
                      return ListTile(
                        contentPadding: EdgeInsets.zero,
                        title: Text(item.name, style: const TextStyle(color: Colors.white)),
                        subtitle: Text(_currencyFormat.format(item.price), style: const TextStyle(color: Colors.white54)),
                        trailing: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            IconButton(
                              icon: const Icon(Icons.remove_circle_outline, color: Colors.white54, size: 20),
                              onPressed: item.quantity > 1 ? () => setState(() => item.quantity -= 1) : null,
                            ),
                            Text('${item.quantity}', style: const TextStyle(color: Colors.white)),
                            IconButton(
                              icon: const Icon(Icons.add_circle_outline, color: Colors.white54, size: 20),
                              onPressed: () => setState(() => item.quantity += 1),
                            ),
                            IconButton(
                              icon: const Icon(Icons.close_rounded, color: Colors.white38, size: 18),
                              onPressed: () => setState(() => _cart.remove(item)),
                            ),
                          ],
                        ),
                      );
                    },
                  ),
          ),
        ],
      ),
      bottomNavigationBar: _cart.isEmpty
          ? null
          : SafeArea(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        const Text('Tổng cộng', style: TextStyle(color: Colors.white70)),
                        Text(_currencyFormat.format(_cartTotal), style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 18)),
                      ],
                    ),
                    const SizedBox(height: 12),
                    Row(
                      children: [
                        Expanded(
                          child: OutlinedButton(
                            onPressed: () => _checkout('cash'),
                            style: OutlinedButton.styleFrom(padding: const EdgeInsets.symmetric(vertical: 14)),
                            child: const Text('Tiền mặt'),
                          ),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: ElevatedButton(
                            onPressed: () => _checkout('card'),
                            style: ElevatedButton.styleFrom(
                              backgroundColor: const Color(0xFF06B6D4),
                              foregroundColor: Colors.black,
                              padding: const EdgeInsets.symmetric(vertical: 14),
                            ),
                            child: const Text('Thẻ/Chuyển khoản'),
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ),
    );
  }
}
