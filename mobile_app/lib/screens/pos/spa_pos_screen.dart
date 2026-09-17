import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../../models/cart_item_model.dart';
import '../../models/product_model.dart';
import '../../models/staff_model.dart';
import '../../services/api_service.dart';
import '../../services/attendance_service.dart';
import '../../services/pos_service.dart';
import '../../services/sales_checkout_service.dart';

/// Màn hình bán hàng cho ngành Spa — mirror spa.html (web) qua POST /api/sales/checkout: chọn
/// dịch vụ, gán 1 thợ DUY NHẤT cho CẢ đơn (khác Nails — gán riêng từng dòng), tip, thanh toán
/// Cash/Card. Dùng db.staff (StaffModel, khoá id) — cùng nguồn với màn Chấm công GPS, KHÔNG
/// phải db.employees (ma_nv) mà Nail POS dùng.
class SpaPosScreen extends StatefulWidget {
  const SpaPosScreen({super.key});

  @override
  State<SpaPosScreen> createState() => _SpaPosScreenState();
}

class _SpaPosScreenState extends State<SpaPosScreen> {
  late final PosService _posService;
  late final AttendanceService _attendanceService;
  late final SalesCheckoutService _checkoutService;

  bool _isLoading = true;
  String? _loadError;
  List<ProductModel> _products = [];
  List<StaffModel> _staff = [];
  final List<CartItemModel> _cart = [];
  String _selectedCategory = 'Tất cả';
  final _currencyFormat = NumberFormat.currency(locale: 'vi_VN', symbol: 'đ', decimalDigits: 0);

  @override
  void initState() {
    super.initState();
    final apiService = context.read<ApiService>();
    _posService = PosService(apiService);
    _attendanceService = AttendanceService(apiService);
    _checkoutService = SalesCheckoutService(apiService);
    _loadData();
  }

  Future<void> _loadData() async {
    setState(() {
      _isLoading = true;
      _loadError = null;
    });
    try {
      final results = await Future.wait([_posService.fetchProducts(), _attendanceService.fetchStaffList()]);
      if (!mounted) return;
      setState(() {
        _products = results[0] as List<ProductModel>;
        _staff = results[1] as List<StaffModel>;
        _isLoading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loadError = 'Không tải được dữ liệu. Kéo xuống để thử lại.';
        _isLoading = false;
      });
    }
  }

  List<String> get _categories {
    final set = <String>{'Tất cả'};
    for (final p in _products) {
      if (p.category != null && p.category!.trim().isNotEmpty) set.add(p.category!);
    }
    return set.toList();
  }

  List<ProductModel> get _filteredProducts =>
      _selectedCategory == 'Tất cả' ? _products : _products.where((p) => p.category == _selectedCategory).toList();

  void _addToCart(ProductModel product) {
    setState(() {
      final existing = _cart.where((c) => c.productId == product.id);
      if (existing.isNotEmpty) {
        existing.first.quantity += 1;
      } else {
        _cart.add(CartItemModel(productId: product.id, name: product.name, price: product.price));
      }
    });
  }

  double get _cartSubtotal => _cart.fold(0, (sum, item) => sum + item.lineTotal);

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Bán hàng — Spa')),
      body: RefreshIndicator(onRefresh: _loadData, color: const Color(0xFF06B6D4), child: _buildBody()),
      bottomNavigationBar: _cart.isEmpty
          ? null
          : SafeArea(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: ElevatedButton(
                  onPressed: () => _openCheckoutSheet(context),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: const Color(0xFF06B6D4),
                    foregroundColor: Colors.black,
                    padding: const EdgeInsets.symmetric(vertical: 16),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                  ),
                  child: Text(
                    'Giỏ hàng (${_cart.length}) · ${_currencyFormat.format(_cartSubtotal)}',
                    style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 15),
                  ),
                ),
              ),
            ),
    );
  }

  Widget _buildBody() {
    if (_isLoading) {
      return const Center(child: CircularProgressIndicator(color: Color(0xFF06B6D4)));
    }
    if (_loadError != null) {
      return ListView(
        padding: const EdgeInsets.all(20),
        children: [
          const SizedBox(height: 80),
          Text(_loadError!, style: const TextStyle(color: Colors.redAccent), textAlign: TextAlign.center),
        ],
      );
    }
    if (_products.isEmpty) {
      return const Center(
        child: Text('Chưa có dịch vụ nào. Thêm dịch vụ trên web trước.', style: TextStyle(color: Colors.white54)),
      );
    }
    return Column(
      children: [
        SizedBox(
          height: 44,
          child: ListView.separated(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            itemCount: _categories.length,
            separatorBuilder: (_, __) => const SizedBox(width: 8),
            itemBuilder: (context, index) {
              final cat = _categories[index];
              final selected = cat == _selectedCategory;
              return ChoiceChip(
                label: Text(cat),
                selected: selected,
                onSelected: (_) => setState(() => _selectedCategory = cat),
                selectedColor: const Color(0xFF06B6D4),
                labelStyle: TextStyle(color: selected ? Colors.black : Colors.white70),
                backgroundColor: Colors.white.withOpacity(0.05),
              );
            },
          ),
        ),
        Expanded(
          child: GridView.builder(
            padding: const EdgeInsets.fromLTRB(16, 4, 16, 100),
            gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
              crossAxisCount: 2,
              mainAxisSpacing: 12,
              crossAxisSpacing: 12,
              childAspectRatio: 1.3,
            ),
            itemCount: _filteredProducts.length,
            itemBuilder: (context, index) {
              final product = _filteredProducts[index];
              return _SpaProductCard(
                product: product,
                currencyFormat: _currencyFormat,
                quantityInCart: _cart.where((c) => c.productId == product.id).fold(0, (s, c) => s + c.quantity),
                onTap: () => _addToCart(product),
              );
            },
          ),
        ),
      ],
    );
  }

  void _openCheckoutSheet(BuildContext context) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: const Color(0xFF0F1424),
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (sheetContext) => _SpaCheckoutSheet(
        cart: _cart,
        staff: _staff,
        subtotal: _cartSubtotal,
        currencyFormat: _currencyFormat,
        checkoutService: _checkoutService,
        onQuantityChanged: (item, qty) => setState(() => item.quantity = qty),
        onRemove: (item) => setState(() => _cart.remove(item)),
        onSuccess: () => setState(() => _cart.clear()),
      ),
    );
  }
}

class _SpaProductCard extends StatelessWidget {
  final ProductModel product;
  final NumberFormat currencyFormat;
  final int quantityInCart;
  final VoidCallback onTap;

  const _SpaProductCard({
    required this.product,
    required this.currencyFormat,
    required this.quantityInCart,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.white.withOpacity(0.05),
      borderRadius: BorderRadius.circular(14),
      child: InkWell(
        borderRadius: BorderRadius.circular(14),
        onTap: onTap,
        child: Stack(
          children: [
            Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  Text(
                    product.name,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w600, fontSize: 14),
                  ),
                  const SizedBox(height: 6),
                  Text(currencyFormat.format(product.price), style: const TextStyle(color: Color(0xFF06B6D4), fontSize: 13)),
                ],
              ),
            ),
            if (quantityInCart > 0)
              Positioned(
                top: 8,
                right: 8,
                child: CircleAvatar(
                  radius: 11,
                  backgroundColor: const Color(0xFF06B6D4),
                  child: Text('$quantityInCart', style: const TextStyle(color: Colors.black, fontSize: 11, fontWeight: FontWeight.bold)),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class _SpaCheckoutSheet extends StatefulWidget {
  final List<CartItemModel> cart;
  final List<StaffModel> staff;
  final double subtotal;
  final NumberFormat currencyFormat;
  final SalesCheckoutService checkoutService;
  final void Function(CartItemModel, int) onQuantityChanged;
  final void Function(CartItemModel) onRemove;
  final VoidCallback onSuccess;

  const _SpaCheckoutSheet({
    required this.cart,
    required this.staff,
    required this.subtotal,
    required this.currencyFormat,
    required this.checkoutService,
    required this.onQuantityChanged,
    required this.onRemove,
    required this.onSuccess,
  });

  @override
  State<_SpaCheckoutSheet> createState() => _SpaCheckoutSheetState();
}

class _SpaCheckoutSheetState extends State<_SpaCheckoutSheet> {
  StaffModel? _selectedStaff;
  String _paymentMethod = 'cash';
  final _tipController = TextEditingController(text: '0');
  bool _isSubmitting = false;

  double get _tipAmount => double.tryParse(_tipController.text.replaceAll(',', '.')) ?? 0;
  double get _total => widget.subtotal + _tipAmount;

  @override
  void dispose() {
    _tipController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (widget.cart.isEmpty) return;
    setState(() => _isSubmitting = true);
    final result = await widget.checkoutService.checkout(
      items: widget.cart,
      paymentMethod: _paymentMethod,
      staffId: _selectedStaff?.id,
      tipAmount: _tipAmount,
    );
    if (!mounted) return;
    setState(() => _isSubmitting = false);
    if (result.success) {
      widget.onSuccess();
      Navigator.pop(context);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('${result.message} Tổng: ${widget.currencyFormat.format(result.totalAmount ?? _total)}'),
          backgroundColor: Colors.green,
        ),
      );
    } else {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(result.message), backgroundColor: Colors.redAccent));
    }
  }

  @override
  Widget build(BuildContext context) {
    return StatefulBuilder(
      builder: (context, setSheetState) {
        return DraggableScrollableSheet(
          initialChildSize: 0.85,
          maxChildSize: 0.95,
          minChildSize: 0.5,
          expand: false,
          builder: (context, scrollController) {
            return Padding(
              padding: EdgeInsets.only(
                left: 20,
                right: 20,
                top: 20,
                bottom: MediaQuery.of(context).viewInsets.bottom + 20,
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text('Thanh toán', style: TextStyle(color: Colors.white, fontSize: 20, fontWeight: FontWeight.bold)),
                  const SizedBox(height: 12),
                  Expanded(
                    child: ListView(
                      controller: scrollController,
                      children: [
                        ...widget.cart.map((item) => Padding(
                              padding: const EdgeInsets.symmetric(vertical: 6),
                              child: Row(
                                children: [
                                  Expanded(child: Text(item.name, style: const TextStyle(color: Colors.white))),
                                  IconButton(
                                    icon: const Icon(Icons.remove_circle_outline, color: Colors.white54, size: 20),
                                    onPressed: item.quantity > 1
                                        ? () {
                                            widget.onQuantityChanged(item, item.quantity - 1);
                                            setSheetState(() {});
                                          }
                                        : null,
                                  ),
                                  Text('${item.quantity}', style: const TextStyle(color: Colors.white)),
                                  IconButton(
                                    icon: const Icon(Icons.add_circle_outline, color: Colors.white54, size: 20),
                                    onPressed: () {
                                      widget.onQuantityChanged(item, item.quantity + 1);
                                      setSheetState(() {});
                                    },
                                  ),
                                  Text(widget.currencyFormat.format(item.lineTotal), style: const TextStyle(color: Colors.white70)),
                                  IconButton(
                                    icon: const Icon(Icons.close_rounded, color: Colors.white38, size: 18),
                                    onPressed: () {
                                      widget.onRemove(item);
                                      setSheetState(() {});
                                      if (widget.cart.isEmpty) Navigator.pop(context);
                                    },
                                  ),
                                ],
                              ),
                            )),
                        const Divider(color: Colors.white12),
                        const SizedBox(height: 8),
                        const Text('Thợ phục vụ (tuỳ chọn)', style: TextStyle(color: Colors.white70, fontSize: 13)),
                        const SizedBox(height: 6),
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 12),
                          decoration: BoxDecoration(color: Colors.white.withOpacity(0.05), borderRadius: BorderRadius.circular(10)),
                          child: DropdownButtonHideUnderline(
                            child: DropdownButton<StaffModel>(
                              isExpanded: true,
                              isDense: true,
                              value: _selectedStaff,
                              hint: const Text('-- Không gán thợ --', style: TextStyle(color: Colors.white38, fontSize: 13)),
                              dropdownColor: const Color(0xFF14192E),
                              items: widget.staff
                                  .map((s) => DropdownMenuItem(value: s, child: Text(s.name, style: const TextStyle(color: Colors.white))))
                                  .toList(),
                              onChanged: (s) => setState(() => _selectedStaff = s),
                            ),
                          ),
                        ),
                        const SizedBox(height: 12),
                        TextField(
                          controller: _tipController,
                          keyboardType: const TextInputType.numberWithOptions(decimal: true),
                          style: const TextStyle(color: Colors.white),
                          decoration: InputDecoration(
                            labelText: 'Tip (đ)',
                            labelStyle: const TextStyle(color: Colors.white54),
                            filled: true,
                            fillColor: Colors.white.withOpacity(0.05),
                            border: OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: BorderSide.none),
                          ),
                          onChanged: (_) => setSheetState(() {}),
                        ),
                        const SizedBox(height: 12),
                        const Text('Phương thức thanh toán', style: TextStyle(color: Colors.white70, fontSize: 13)),
                        const SizedBox(height: 8),
                        Wrap(
                          spacing: 8,
                          children: [
                            _PayChip(label: 'Tiền mặt', value: 'cash', group: _paymentMethod, onSelect: (v) => setState(() => _paymentMethod = v)),
                            _PayChip(label: 'Thẻ/Chuyển khoản', value: 'card', group: _paymentMethod, onSelect: (v) => setState(() => _paymentMethod = v)),
                          ],
                        ),
                      ],
                    ),
                  ),
                  const Divider(color: Colors.white12),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      const Text('Tổng cộng', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 16)),
                      Text(widget.currencyFormat.format(_total), style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 16)),
                    ],
                  ),
                  const SizedBox(height: 12),
                  SizedBox(
                    width: double.infinity,
                    child: ElevatedButton(
                      onPressed: _isSubmitting ? null : _submit,
                      style: ElevatedButton.styleFrom(
                        backgroundColor: const Color(0xFF06B6D4),
                        foregroundColor: Colors.black,
                        padding: const EdgeInsets.symmetric(vertical: 16),
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                      ),
                      child: _isSubmitting
                          ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.black))
                          : const Text('Xác nhận thanh toán', style: TextStyle(fontWeight: FontWeight.bold)),
                    ),
                  ),
                ],
              ),
            );
          },
        );
      },
    );
  }
}

class _PayChip extends StatelessWidget {
  final String label;
  final String value;
  final String group;
  final ValueChanged<String> onSelect;

  const _PayChip({required this.label, required this.value, required this.group, required this.onSelect});

  @override
  Widget build(BuildContext context) {
    final selected = value == group;
    return ChoiceChip(
      label: Text(label),
      selected: selected,
      onSelected: (_) => onSelect(value),
      selectedColor: const Color(0xFF06B6D4),
      labelStyle: TextStyle(color: selected ? Colors.black : Colors.white70),
      backgroundColor: Colors.white.withOpacity(0.05),
    );
  }
}
