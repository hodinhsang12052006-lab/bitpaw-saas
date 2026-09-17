import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../../models/cart_item_model.dart';
import '../../models/employee_model.dart';
import '../../models/product_model.dart';
import '../../services/api_service.dart';
import '../../services/nail_pos_service.dart';
import '../../services/pos_service.dart';

/// Màn hình bán hàng cho ngành Nails — mirror pos_nail.html (web): chọn dịch vụ theo danh mục,
/// gán thợ cho TỪNG dòng để tính hoa hồng, thanh toán Cash/Card/Split kèm discount/tax/tip.
/// Không làm luồng Square Terminal (card-present) ở bản v1 di động — chỉ Cash/Card thủ công,
/// khớp đúng cách hầu hết salon nhỏ vẫn thao tác khi không có máy Square kết nối.
class NailPosScreen extends StatefulWidget {
  const NailPosScreen({super.key});

  @override
  State<NailPosScreen> createState() => _NailPosScreenState();
}

class _NailPosScreenState extends State<NailPosScreen> {
  late final PosService _posService;
  late final NailPosService _nailPosService;

  bool _isLoading = true;
  String? _loadError;
  List<ProductModel> _products = [];
  List<EmployeeModel> _technicians = [];
  final List<CartItemModel> _cart = [];
  String _selectedCategory = 'Tất cả';
  final _currencyFormat = NumberFormat.currency(locale: 'vi_VN', symbol: 'đ', decimalDigits: 0);

  @override
  void initState() {
    super.initState();
    final apiService = context.read<ApiService>();
    _posService = PosService(apiService);
    _nailPosService = NailPosService(apiService);
    _loadData();
  }

  Future<void> _loadData() async {
    setState(() {
      _isLoading = true;
      _loadError = null;
    });
    try {
      final results = await Future.wait([_posService.fetchProducts(), _posService.fetchEmployees()]);
      if (!mounted) return;
      setState(() {
        _products = results[0] as List<ProductModel>;
        _technicians = (results[1] as List<EmployeeModel>).where((e) => e.linhVuc == 'Nails').toList();
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

  List<ProductModel> get _filteredProducts {
    if (_selectedCategory == 'Tất cả') return _products;
    return _products.where((p) => p.category == _selectedCategory).toList();
  }

  void _addToCart(ProductModel product) {
    setState(() {
      final existing = _cart.where((c) => c.productId == product.id && c.assignedMaNv == null);
      if (existing.isNotEmpty) {
        existing.first.quantity += 1;
      } else {
        _cart.add(CartItemModel(productId: product.id, name: product.name, price: product.price));
      }
    });
  }

  void _addCustomItem(String name, double price) {
    setState(() {
      _cart.add(CartItemModel(name: name, price: price));
    });
  }

  void _removeCartItem(CartItemModel item) {
    setState(() => _cart.remove(item));
  }

  double get _cartSubtotal => _cart.fold(0, (sum, item) => sum + item.lineTotal);

  Future<void> _openCustomItemDialog() async {
    final nameController = TextEditingController();
    final priceController = TextEditingController();
    final result = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        backgroundColor: const Color(0xFF14192E),
        title: const Text('Thêm mục tuỳ chỉnh', style: TextStyle(color: Colors.white)),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: nameController,
              style: const TextStyle(color: Colors.white),
              decoration: const InputDecoration(labelText: 'Tên mục', labelStyle: TextStyle(color: Colors.white54)),
            ),
            TextField(
              controller: priceController,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              style: const TextStyle(color: Colors.white),
              decoration: const InputDecoration(labelText: 'Giá', labelStyle: TextStyle(color: Colors.white54)),
            ),
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(dialogContext, false), child: const Text('Huỷ')),
          TextButton(onPressed: () => Navigator.pop(dialogContext, true), child: const Text('Thêm')),
        ],
      ),
    );
    if (result == true) {
      final name = nameController.text.trim();
      final price = double.tryParse(priceController.text.replaceAll(',', '.'));
      if (name.isNotEmpty && price != null && price >= 0) {
        _addCustomItem(name, price);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Bán hàng — Nails'),
        actions: [
          IconButton(
            icon: const Icon(Icons.add_shopping_cart_rounded),
            tooltip: 'Thêm mục tuỳ chỉnh',
            onPressed: _openCustomItemDialog,
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: _loadData,
        color: const Color(0xFF06B6D4),
        child: _buildBody(),
      ),
      bottomNavigationBar: _cart.isEmpty
          ? null
          : SafeArea(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: ElevatedButton(
                  onPressed: () => _openCartSheet(context),
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
            padding: const EdgeInsets.fromLTRB(16, 4, 16, 16),
            gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
              crossAxisCount: 2,
              mainAxisSpacing: 12,
              crossAxisSpacing: 12,
              childAspectRatio: 1.3,
            ),
            itemCount: _filteredProducts.length,
            itemBuilder: (context, index) {
              final product = _filteredProducts[index];
              return _ProductCard(
                product: product,
                currencyFormat: _currencyFormat,
                onTap: () => _addToCart(product),
              );
            },
          ),
        ),
      ],
    );
  }

  void _openCartSheet(BuildContext context) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: const Color(0xFF0F1424),
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (sheetContext) {
        return StatefulBuilder(
          builder: (sheetContext, setSheetState) {
            return DraggableScrollableSheet(
              initialChildSize: 0.75,
              maxChildSize: 0.95,
              minChildSize: 0.4,
              expand: false,
              builder: (context, scrollController) {
                return Padding(
                  padding: const EdgeInsets.all(20),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text('Giỏ hàng', style: TextStyle(color: Colors.white, fontSize: 20, fontWeight: FontWeight.bold)),
                      const SizedBox(height: 12),
                      Expanded(
                        child: ListView.separated(
                          controller: scrollController,
                          itemCount: _cart.length,
                          separatorBuilder: (_, __) => const Divider(color: Colors.white12),
                          itemBuilder: (context, index) {
                            final item = _cart[index];
                            return _CartLineTile(
                              item: item,
                              technicians: _technicians,
                              currencyFormat: _currencyFormat,
                              onQuantityChanged: (qty) {
                                setState(() => item.quantity = qty);
                                setSheetState(() {});
                              },
                              onTechAssigned: (tech) {
                                setState(() {
                                  item.assignedMaNv = tech?.maNv;
                                  item.assignedTechName = tech?.hoTen;
                                });
                                setSheetState(() {});
                              },
                              onRemove: () {
                                _removeCartItem(item);
                                setSheetState(() {});
                                if (_cart.isEmpty && Navigator.canPop(sheetContext)) {
                                  Navigator.pop(sheetContext);
                                }
                              },
                            );
                          },
                        ),
                      ),
                      const Divider(color: Colors.white12),
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          const Text('Tạm tính', style: TextStyle(color: Colors.white70)),
                          Text(_currencyFormat.format(_cartSubtotal),
                              style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 16)),
                        ],
                      ),
                      const SizedBox(height: 12),
                      SizedBox(
                        width: double.infinity,
                        child: ElevatedButton(
                          onPressed: _cart.isEmpty
                              ? null
                              : () {
                                  Navigator.pop(sheetContext);
                                  _openCheckoutSheet(context);
                                },
                          style: ElevatedButton.styleFrom(
                            backgroundColor: const Color(0xFF06B6D4),
                            foregroundColor: Colors.black,
                            padding: const EdgeInsets.symmetric(vertical: 16),
                            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                          ),
                          child: const Text('Tiếp tục thanh toán', style: TextStyle(fontWeight: FontWeight.bold)),
                        ),
                      ),
                    ],
                  ),
                );
              },
            );
          },
        );
      },
    );
  }

  void _openCheckoutSheet(BuildContext context) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: const Color(0xFF0F1424),
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (sheetContext) => _CheckoutSheet(
        cart: List.unmodifiable(_cart),
        subtotal: _cartSubtotal,
        currencyFormat: _currencyFormat,
        nailPosService: _nailPosService,
        onSuccess: () {
          setState(() => _cart.clear());
        },
      ),
    );
  }
}

class _ProductCard extends StatelessWidget {
  final ProductModel product;
  final NumberFormat currencyFormat;
  final VoidCallback onTap;

  const _ProductCard({required this.product, required this.currencyFormat, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.white.withOpacity(0.05),
      borderRadius: BorderRadius.circular(14),
      child: InkWell(
        borderRadius: BorderRadius.circular(14),
        onTap: onTap,
        child: Padding(
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
      ),
    );
  }
}

class _CartLineTile extends StatelessWidget {
  final CartItemModel item;
  final List<EmployeeModel> technicians;
  final NumberFormat currencyFormat;
  final ValueChanged<int> onQuantityChanged;
  final ValueChanged<EmployeeModel?> onTechAssigned;
  final VoidCallback onRemove;

  const _CartLineTile({
    required this.item,
    required this.technicians,
    required this.currencyFormat,
    required this.onQuantityChanged,
    required this.onTechAssigned,
    required this.onRemove,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(item.name, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w600)),
              ),
              Text(currencyFormat.format(item.lineTotal), style: const TextStyle(color: Colors.white70)),
              IconButton(
                icon: const Icon(Icons.close_rounded, color: Colors.white38, size: 18),
                onPressed: onRemove,
              ),
            ],
          ),
          Row(
            children: [
              IconButton(
                icon: const Icon(Icons.remove_circle_outline, color: Colors.white54, size: 20),
                onPressed: item.quantity > 1 ? () => onQuantityChanged(item.quantity - 1) : null,
              ),
              Text('${item.quantity}', style: const TextStyle(color: Colors.white)),
              IconButton(
                icon: const Icon(Icons.add_circle_outline, color: Colors.white54, size: 20),
                onPressed: () => onQuantityChanged(item.quantity + 1),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: technicians.isEmpty
                    ? const Text('Chưa có thợ Nails', style: TextStyle(color: Colors.white24, fontSize: 12))
                    : DropdownButtonHideUnderline(
                        child: DropdownButton<String>(
                          isExpanded: true,
                          isDense: true,
                          value: item.assignedMaNv,
                          hint: const Text('-- Gán thợ --', style: TextStyle(color: Colors.white38, fontSize: 13)),
                          dropdownColor: const Color(0xFF14192E),
                          items: technicians
                              .map((t) => DropdownMenuItem(
                                    value: t.maNv,
                                    child: Text(t.hoTen, style: const TextStyle(color: Colors.white, fontSize: 13)),
                                  ))
                              .toList(),
                          onChanged: (maNv) {
                            final tech = technicians.where((t) => t.maNv == maNv).toList();
                            onTechAssigned(tech.isEmpty ? null : tech.first);
                          },
                        ),
                      ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _CheckoutSheet extends StatefulWidget {
  final List<CartItemModel> cart;
  final double subtotal;
  final NumberFormat currencyFormat;
  final NailPosService nailPosService;
  final VoidCallback onSuccess;

  const _CheckoutSheet({
    required this.cart,
    required this.subtotal,
    required this.currencyFormat,
    required this.nailPosService,
    required this.onSuccess,
  });

  @override
  State<_CheckoutSheet> createState() => _CheckoutSheetState();
}

class _CheckoutSheetState extends State<_CheckoutSheet> {
  String _paymentMethod = 'cash';
  final _discountController = TextEditingController(text: '0');
  final _taxController = TextEditingController(text: '0');
  final _cashTipController = TextEditingController(text: '0');
  final _cardTipController = TextEditingController(text: '0');
  final _splitCashController = TextEditingController(text: '0');
  final _splitCardController = TextEditingController(text: '0');
  bool _isSubmitting = false;

  double _num(TextEditingController c) => double.tryParse(c.text.replaceAll(',', '.')) ?? 0;

  double get _discountAmount => (widget.subtotal * (_num(_discountController) / 100)).clamp(0, widget.subtotal);
  double get _taxAmount => (widget.subtotal - _discountAmount) * (_num(_taxController) / 100);
  double get _totalTip => _num(_cashTipController) + _num(_cardTipController);
  double get _total => widget.subtotal - _discountAmount + _taxAmount + _totalTip;

  @override
  void dispose() {
    _discountController.dispose();
    _taxController.dispose();
    _cashTipController.dispose();
    _cardTipController.dispose();
    _splitCashController.dispose();
    _splitCardController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    setState(() => _isSubmitting = true);
    final result = await widget.nailPosService.checkout(
      items: widget.cart,
      paymentMethod: _paymentMethod,
      discountType: 'percent',
      discountValue: _num(_discountController),
      taxPercent: _num(_taxController),
      cashTip: _num(_cashTipController),
      cardTip: _num(_cardTipController),
      splitCashAmount: _paymentMethod == 'split' ? _num(_splitCashController) : null,
      splitCardAmount: _paymentMethod == 'split' ? _num(_splitCardController) : null,
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
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(result.message), backgroundColor: Colors.redAccent),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.only(
        left: 20,
        right: 20,
        top: 20,
        bottom: MediaQuery.of(context).viewInsets.bottom + 20,
      ),
      child: SingleChildScrollView(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text('Thanh toán', style: TextStyle(color: Colors.white, fontSize: 20, fontWeight: FontWeight.bold)),
            const SizedBox(height: 16),
            Row(
              children: [
                Expanded(child: _NumberField(label: 'Giảm giá (%)', controller: _discountController)),
                const SizedBox(width: 12),
                Expanded(child: _NumberField(label: 'Thuế (%)', controller: _taxController)),
              ],
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(child: _NumberField(label: 'Tip tiền mặt', controller: _cashTipController)),
                const SizedBox(width: 12),
                Expanded(child: _NumberField(label: 'Tip thẻ', controller: _cardTipController)),
              ],
            ),
            const SizedBox(height: 16),
            const Text('Phương thức thanh toán', style: TextStyle(color: Colors.white70, fontSize: 13)),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              children: [
                _PaymentChip(label: 'Tiền mặt', value: 'cash', groupValue: _paymentMethod, onSelect: (v) => setState(() => _paymentMethod = v)),
                _PaymentChip(label: 'Thẻ', value: 'card', groupValue: _paymentMethod, onSelect: (v) => setState(() => _paymentMethod = v)),
                _PaymentChip(label: 'Chia đôi', value: 'split', groupValue: _paymentMethod, onSelect: (v) => setState(() => _paymentMethod = v)),
              ],
            ),
            if (_paymentMethod == 'split') ...[
              const SizedBox(height: 12),
              Row(
                children: [
                  Expanded(child: _NumberField(label: 'Tiền mặt (đ)', controller: _splitCashController)),
                  const SizedBox(width: 12),
                  Expanded(child: _NumberField(label: 'Thẻ (đ)', controller: _splitCardController)),
                ],
              ),
            ],
            const SizedBox(height: 20),
            _SummaryRow(label: 'Tạm tính', value: widget.currencyFormat.format(widget.subtotal)),
            _SummaryRow(label: 'Giảm giá', value: '-${widget.currencyFormat.format(_discountAmount)}'),
            _SummaryRow(label: 'Thuế', value: widget.currencyFormat.format(_taxAmount)),
            _SummaryRow(label: 'Tip', value: widget.currencyFormat.format(_totalTip)),
            const Divider(color: Colors.white12),
            _SummaryRow(label: 'Tổng cộng', value: widget.currencyFormat.format(_total), isTotal: true),
            const SizedBox(height: 16),
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
      ),
    );
  }
}

class _NumberField extends StatelessWidget {
  final String label;
  final TextEditingController controller;

  const _NumberField({required this.label, required this.controller});

  @override
  Widget build(BuildContext context) {
    return TextField(
      controller: controller,
      keyboardType: const TextInputType.numberWithOptions(decimal: true),
      style: const TextStyle(color: Colors.white),
      decoration: InputDecoration(
        labelText: label,
        labelStyle: const TextStyle(color: Colors.white54, fontSize: 12),
        filled: true,
        fillColor: Colors.white.withOpacity(0.05),
        contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        border: OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: BorderSide.none),
      ),
    );
  }
}

class _PaymentChip extends StatelessWidget {
  final String label;
  final String value;
  final String groupValue;
  final ValueChanged<String> onSelect;

  const _PaymentChip({required this.label, required this.value, required this.groupValue, required this.onSelect});

  @override
  Widget build(BuildContext context) {
    final selected = value == groupValue;
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

class _SummaryRow extends StatelessWidget {
  final String label;
  final String value;
  final bool isTotal;

  const _SummaryRow({required this.label, required this.value, this.isTotal = false});

  @override
  Widget build(BuildContext context) {
    final style = TextStyle(
      color: isTotal ? Colors.white : Colors.white70,
      fontWeight: isTotal ? FontWeight.bold : FontWeight.normal,
      fontSize: isTotal ? 16 : 13,
    );
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [Text(label, style: style), Text(value, style: style)],
      ),
    );
  }
}
