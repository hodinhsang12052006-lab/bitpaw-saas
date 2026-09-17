import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../models/dining_table_model.dart';
import '../../services/api_service.dart';
import '../../services/fnb_service.dart';
import 'table_order_screen.dart';

/// Sơ đồ bàn cho ngành F&B — mirror pos.html (web): lưới bàn, màu theo trạng thái (xanh = còn
/// trống, cam = đang phục vụ), bấm vào bàn để gọi món/thanh toán.
class FnbTablesScreen extends StatefulWidget {
  const FnbTablesScreen({super.key});

  @override
  State<FnbTablesScreen> createState() => _FnbTablesScreenState();
}

class _FnbTablesScreenState extends State<FnbTablesScreen> {
  late final FnbService _fnbService;
  bool _isLoading = true;
  String? _loadError;
  List<DiningTableModel> _tables = [];

  @override
  void initState() {
    super.initState();
    _fnbService = FnbService(context.read<ApiService>());
    _loadTables();
  }

  Future<void> _loadTables() async {
    setState(() {
      _isLoading = true;
      _loadError = null;
    });
    try {
      final tables = await _fnbService.fetchTables();
      if (!mounted) return;
      setState(() {
        _tables = tables;
        _isLoading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loadError = 'Không tải được danh sách bàn. Kéo xuống để thử lại.';
        _isLoading = false;
      });
    }
  }

  Future<void> _openTable(DiningTableModel table) async {
    await Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => TableOrderScreen(tableId: table.id, tableName: table.name)),
    );
    if (mounted) _loadTables();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Bán hàng — Sơ đồ bàn')),
      body: RefreshIndicator(
        onRefresh: _loadTables,
        color: const Color(0xFF06B6D4),
        child: _buildBody(),
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
    if (_tables.isEmpty) {
      return ListView(
        padding: const EdgeInsets.all(20),
        children: const [
          SizedBox(height: 80),
          Text(
            'Chưa có bàn nào. Mở màn "Bán hàng" trên web (POS) một lần để hệ thống tự tạo sẵn danh sách bàn.',
            style: TextStyle(color: Colors.white54),
            textAlign: TextAlign.center,
          ),
        ],
      );
    }
    return GridView.builder(
      padding: const EdgeInsets.all(16),
      gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
        crossAxisCount: 3,
        mainAxisSpacing: 12,
        crossAxisSpacing: 12,
        childAspectRatio: 1,
      ),
      itemCount: _tables.length,
      itemBuilder: (context, index) {
        final table = _tables[index];
        final color = table.isAvailable ? Colors.greenAccent : Colors.orangeAccent;
        return Material(
          color: color.withOpacity(0.12),
          borderRadius: BorderRadius.circular(14),
          child: InkWell(
            borderRadius: BorderRadius.circular(14),
            onTap: () => _openTable(table),
            child: Container(
              decoration: BoxDecoration(border: Border.all(color: color.withOpacity(0.4)), borderRadius: BorderRadius.circular(14)),
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Icon(Icons.table_restaurant_rounded, color: color, size: 26),
                  const SizedBox(height: 6),
                  Text(table.name, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w600)),
                  const SizedBox(height: 2),
                  Text(table.status, style: TextStyle(color: color, fontSize: 11)),
                ],
              ),
            ),
          ),
        );
      },
    );
  }
}
