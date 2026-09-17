import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../../models/product_model.dart';
import '../../models/table_order_item_model.dart';
import '../../services/api_service.dart';
import '../../services/fnb_service.dart';
import '../../services/pos_service.dart';

/// Gọi món + thanh toán cho 1 bàn cụ thể — mirror table_order.html/view_table (web). Mỗi thao
/// tác gọi món/xoá món gọi thẳng API rồi tải lại danh sách từ server (KHÔNG tự tính local) vì
/// nhiều nhân viên có thể cùng thao tác trên 1 bàn cùng lúc — server luôn là nguồn dữ liệu đúng.
class TableOrderScreen extends StatefulWidget {
  final int tableId;
  final String tableName;

  const TableOrderScreen({super.key, required this.tableId, required this.tableName});

  @override
  State<TableOrderScreen> createState() => _TableOrderScreenState();
}

class _TableOrderScreenState extends State<TableOrderScreen> {
  late final FnbService _fnbService;
  late final PosService _posService;

  bool _isLoading = true;
  bool _isCheckingOut = false;
  String? _loadError;
  List<TableOrderItemModel> _orderItems = [];
  List<ProductModel> _menu = [];
  String _selectedCategory = 'Tất cả';

  final _currencyFormat = NumberFormat.currency(locale: 'vi_VN', symbol: 'đ', decimalDigits: 0);

  @override
  void initState() {
    super.initState();
    final apiService = context.read<ApiService>();
    _fnbService = FnbService(apiService);
    _posService = PosService(apiService);
    _loadAll();
  }

  Future<void> _loadAll() async {
    setState(() {
      _isLoading = true;
      _loadError = null;
    });
    try {
      final results = await Future.wait([
        _fnbService.fetchTableOrders(widget.tableId),
        _posService.fetchProducts(),
      ]);
      if (!mounted) return;
      setState(() {
        _orderItems = results[0] as List<TableOrderItemModel>;
        _menu = (results[1] as List<ProductModel>).where((p) => p.channelType == 'fnb').toList();
        _isLoading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loadError = 'Không tải được dữ liệu bàn. Kéo xuống để thử lại.';
        _isLoading = false;
      });
    }
  }

  Future<void> _reloadOrdersOnly() async {
    try {
      final items = await _fnbService.fetchTableOrders(widget.tableId);
      if (mounted) setState(() => _orderItems = items);
    } catch (_) {
      // best-effort — nếu lỗi, dữ liệu cũ vẫn còn hiển thị đúng cho tới lần pull-to-refresh kế tiếp
    }
  }

  Future<void> _addItem(ProductModel product) async {
    try {
      await _fnbService.addOrderItem(widget.tableId, product.id);
      await _reloadOrdersOnly();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Gọi món thất bại: $e'), backgroundColor: Colors.redAccent));
    }
  }

  Future<void> _removeItem(TableOrderItemModel item) async {
    try {
      await _fnbService.removeOrderItem(item.id);
      await _reloadOrdersOnly();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Xoá món thất bại: $e'), backgroundColor: Colors.redAccent));
    }
  }

  double get _totalBill => _orderItems.fold(0, (sum, item) => sum + item.lineTotal);

  Future<void> _checkout() async {
    if (_orderItems.isEmpty) return;
    setState(() => _isCheckingOut = true);
    final result = await _fnbService.checkoutTable(widget.tableId);
    if (!mounted) return;
    setState(() => _isCheckingOut = false);
    if (result.success) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(result.message), backgroundColor: Colors.green),
      );
      if (result.orderId != null) Navigator.of(context).pop();
    } else {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(result.message), backgroundColor: Colors.redAccent));
    }
  }

  List<String> get _categories {
    final set = <String>{'Tất cả'};
    for (final p in _menu) {
      if (p.category != null && p.category!.trim().isNotEmpty) set.add(p.category!);
    }
    return set.toList();
  }

  List<ProductModel> get _filteredMenu =>
      _selectedCategory == 'Tất cả' ? _menu : _menu.where((p) => p.category == _selectedCategory).toList();

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(widget.tableName)),
      body: RefreshIndicator(onRefresh: _loadAll, color: const Color(0xFF06B6D4), child: _buildBody()),
      bottomNavigationBar: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  const Text('Tổng hoá đơn', style: TextStyle(color: Colors.white70)),
                  Text(_currencyFormat.format(_totalBill), style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 18)),
                ],
              ),
              const SizedBox(height: 10),
              SizedBox(
                width: double.infinity,
                child: ElevatedButton(
                  onPressed: (_orderItems.isEmpty || _isCheckingOut) ? null : _checkout,
                  style: ElevatedButton.styleFrom(
                    backgroundColor: const Color(0xFF06B6D4),
                    foregroundColor: Colors.black,
                    padding: const EdgeInsets.symmetric(vertical: 14),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                  ),
                  child: _isCheckingOut
                      ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.black))
                      : const Text('Thanh toán bàn', style: TextStyle(fontWeight: FontWeight.bold)),
                ),
              ),
            ],
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
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        const Text('Món đã gọi', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 16)),
        const SizedBox(height: 8),
        if (_orderItems.isEmpty)
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 8),
            child: Text('Chưa gọi món nào.', style: TextStyle(color: Colors.white38)),
          )
        else
          ..._orderItems.map((item) => Padding(
                padding: const EdgeInsets.symmetric(vertical: 4),
                child: Row(
                  children: [
                    Expanded(child: Text('${item.name} x${item.quantity}', style: const TextStyle(color: Colors.white))),
                    Text(_currencyFormat.format(item.lineTotal), style: const TextStyle(color: Colors.white70)),
                    IconButton(
                      icon: const Icon(Icons.close_rounded, color: Colors.white38, size: 18),
                      onPressed: () => _removeItem(item),
                    ),
                  ],
                ),
              )),
        const SizedBox(height: 20),
        const Text('Thực đơn', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 16)),
        const SizedBox(height: 8),
        SizedBox(
          height: 40,
          child: ListView.separated(
            scrollDirection: Axis.horizontal,
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
        const SizedBox(height: 12),
        if (_menu.isEmpty)
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 8),
            child: Text('Chưa có món nào trong thực đơn.', style: TextStyle(color: Colors.white38)),
          )
        else
          GridView.builder(
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
              crossAxisCount: 2,
              mainAxisSpacing: 10,
              crossAxisSpacing: 10,
              childAspectRatio: 1.3,
            ),
            itemCount: _filteredMenu.length,
            itemBuilder: (context, index) {
              final product = _filteredMenu[index];
              return Material(
                color: Colors.white.withOpacity(0.05),
                borderRadius: BorderRadius.circular(12),
                child: InkWell(
                  borderRadius: BorderRadius.circular(12),
                  onTap: () => _addItem(product),
                  child: Padding(
                    padding: const EdgeInsets.all(10),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      mainAxisAlignment: MainAxisAlignment.end,
                      children: [
                        Text(product.name, maxLines: 2, overflow: TextOverflow.ellipsis, style: const TextStyle(color: Colors.white, fontSize: 13, fontWeight: FontWeight.w600)),
                        const SizedBox(height: 4),
                        Text(_currencyFormat.format(product.price), style: const TextStyle(color: Color(0xFF06B6D4), fontSize: 12)),
                      ],
                    ),
                  ),
                ),
              );
            },
          ),
      ],
    );
  }
}
