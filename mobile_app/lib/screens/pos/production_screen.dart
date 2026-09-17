import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../models/employee_model.dart';
import '../../models/production_output_model.dart';
import '../../models/raw_material_model.dart';
import '../../services/api_service.dart';
import '../../services/pos_service.dart';
import '../../services/production_service.dart';

/// Ghi nhận sản lượng cho ngành Sản xuất — mirror production_output.html/production_materials.html
/// (web) qua /api/production/*: form ghi nhận (công nhân/công đoạn/số lượng) tự trừ NVL theo
/// công thức nếu khớp, tab Tồn kho NVL xem nhanh nguyên liệu sắp hết/đã âm.
class ProductionScreen extends StatefulWidget {
  const ProductionScreen({super.key});

  @override
  State<ProductionScreen> createState() => _ProductionScreenState();
}

class _ProductionScreenState extends State<ProductionScreen> with SingleTickerProviderStateMixin {
  late final TabController _tabController;
  late final ProductionService _productionService;
  late final PosService _posService;

  bool _isLoading = true;
  String? _loadError;
  List<EmployeeModel> _employees = [];
  List<RawMaterialModel> _materials = [];
  List<ProductionOutputModel> _recentOutput = [];

  EmployeeModel? _selectedEmployee;
  final _congDoanController = TextEditingController();
  final _soLuongController = TextEditingController();
  final _caLamController = TextEditingController();
  final _ghiChuController = TextEditingController();
  bool _isSubmitting = false;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 2, vsync: this);
    final apiService = context.read<ApiService>();
    _productionService = ProductionService(apiService);
    _posService = PosService(apiService);
    _loadAll();
  }

  @override
  void dispose() {
    _tabController.dispose();
    _congDoanController.dispose();
    _soLuongController.dispose();
    _caLamController.dispose();
    _ghiChuController.dispose();
    super.dispose();
  }

  Future<void> _loadAll() async {
    setState(() {
      _isLoading = true;
      _loadError = null;
    });
    try {
      final results = await Future.wait([
        _posService.fetchEmployees(),
        _productionService.fetchMaterials(),
        _productionService.fetchRecentOutput(),
      ]);
      if (!mounted) return;
      setState(() {
        _employees = results[0] as List<EmployeeModel>;
        _materials = results[1] as List<RawMaterialModel>;
        _recentOutput = results[2] as List<ProductionOutputModel>;
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

  Future<void> _submit() async {
    final congDoan = _congDoanController.text.trim();
    final soLuong = int.tryParse(_soLuongController.text.trim());
    if (_selectedEmployee == null) {
      _showSnack('Vui lòng chọn công nhân.', isError: true);
      return;
    }
    if (congDoan.isEmpty) {
      _showSnack('Vui lòng nhập công đoạn/sản phẩm.', isError: true);
      return;
    }
    if (soLuong == null || soLuong <= 0) {
      _showSnack('Số lượng phải lớn hơn 0.', isError: true);
      return;
    }
    setState(() => _isSubmitting = true);
    final result = await _productionService.submitOutput(
      maNv: _selectedEmployee!.maNv,
      congDoan: congDoan,
      soLuong: soLuong,
      caLam: _caLamController.text.trim(),
      ghiChu: _ghiChuController.text.trim(),
    );
    if (!mounted) return;
    setState(() => _isSubmitting = false);
    if (result.success) {
      _congDoanController.clear();
      _soLuongController.clear();
      _caLamController.clear();
      _ghiChuController.clear();
      _showSnack(result.message, isError: false);
      if (result.materialWarnings.isNotEmpty) {
        for (final w in result.materialWarnings) {
          _showSnack(w, isError: true);
        }
      }
      await _loadAll();
    } else {
      _showSnack(result.message, isError: true);
    }
  }

  void _showSnack(String message, {required bool isError}) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message), backgroundColor: isError ? Colors.redAccent : Colors.green),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Sản xuất'),
        bottom: TabBar(
          controller: _tabController,
          tabs: const [Tab(text: 'Ghi nhận sản lượng'), Tab(text: 'Tồn kho NVL')],
        ),
      ),
      body: _isLoading
          ? const Center(child: CircularProgressIndicator(color: Color(0xFF06B6D4)))
          : _loadError != null
              ? Center(child: Padding(padding: const EdgeInsets.all(20), child: Text(_loadError!, style: const TextStyle(color: Colors.redAccent))))
              : TabBarView(
                  controller: _tabController,
                  children: [_buildOutputForm(), _buildMaterialsTab()],
                ),
    );
  }

  Widget _buildOutputForm() {
    return RefreshIndicator(
      onRefresh: _loadAll,
      color: const Color(0xFF06B6D4),
      child: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          const Text('Ghi nhận sản lượng', style: TextStyle(color: Colors.white, fontSize: 18, fontWeight: FontWeight.bold)),
          const SizedBox(height: 16),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12),
            decoration: BoxDecoration(color: Colors.white.withOpacity(0.05), borderRadius: BorderRadius.circular(10)),
            child: DropdownButtonHideUnderline(
              child: DropdownButton<EmployeeModel>(
                isExpanded: true,
                value: _selectedEmployee,
                hint: const Text('-- Chọn công nhân --', style: TextStyle(color: Colors.white38)),
                dropdownColor: const Color(0xFF14192E),
                items: _employees
                    .map((e) => DropdownMenuItem(value: e, child: Text(e.hoTen, style: const TextStyle(color: Colors.white))))
                    .toList(),
                onChanged: (v) => setState(() => _selectedEmployee = v),
              ),
            ),
          ),
          const SizedBox(height: 12),
          _field(_congDoanController, 'Công đoạn / Sản phẩm'),
          const SizedBox(height: 12),
          _field(_soLuongController, 'Số lượng', keyboardType: TextInputType.number),
          const SizedBox(height: 12),
          _field(_caLamController, 'Ca làm (tuỳ chọn)'),
          const SizedBox(height: 12),
          _field(_ghiChuController, 'Ghi chú (tuỳ chọn)'),
          const SizedBox(height: 20),
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
                  : const Text('Ghi nhận', style: TextStyle(fontWeight: FontWeight.bold)),
            ),
          ),
          const SizedBox(height: 28),
          const Text('Gần đây', style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold)),
          const SizedBox(height: 8),
          if (_recentOutput.isEmpty)
            const Padding(padding: EdgeInsets.symmetric(vertical: 8), child: Text('Chưa có bản ghi nào.', style: TextStyle(color: Colors.white38)))
          else
            ..._recentOutput.take(20).map((o) => Padding(
                  padding: const EdgeInsets.symmetric(vertical: 4),
                  child: Row(
                    children: [
                      Expanded(child: Text('${o.hoTen} · ${o.congDoan}', style: const TextStyle(color: Colors.white))),
                      Text('${o.soLuong}', style: const TextStyle(color: Color(0xFF06B6D4), fontWeight: FontWeight.bold)),
                      const SizedBox(width: 8),
                      Text(o.ngay, style: const TextStyle(color: Colors.white38, fontSize: 11)),
                    ],
                  ),
                )),
        ],
      ),
    );
  }

  Widget _buildMaterialsTab() {
    return RefreshIndicator(
      onRefresh: _loadAll,
      color: const Color(0xFF06B6D4),
      child: _materials.isEmpty
          ? ListView(
              padding: const EdgeInsets.all(20),
              children: const [SizedBox(height: 80), Text('Chưa có nguyên vật liệu nào.', style: TextStyle(color: Colors.white38), textAlign: TextAlign.center)],
            )
          : ListView.separated(
              padding: const EdgeInsets.all(20),
              itemCount: _materials.length,
              separatorBuilder: (_, __) => const Divider(color: Colors.white12),
              itemBuilder: (context, index) {
                final m = _materials[index];
                return ListTile(
                  contentPadding: EdgeInsets.zero,
                  title: Text(m.name, style: const TextStyle(color: Colors.white)),
                  trailing: Text(
                    '${m.stockQty.toStringAsFixed(1)} ${m.unit}',
                    style: TextStyle(color: m.isLow ? Colors.redAccent : Colors.white70, fontWeight: m.isLow ? FontWeight.bold : FontWeight.normal),
                  ),
                );
              },
            ),
    );
  }

  Widget _field(TextEditingController controller, String label, {TextInputType? keyboardType}) {
    return TextField(
      controller: controller,
      keyboardType: keyboardType,
      style: const TextStyle(color: Colors.white),
      decoration: InputDecoration(
        labelText: label,
        labelStyle: const TextStyle(color: Colors.white54),
        filled: true,
        fillColor: Colors.white.withOpacity(0.05),
        border: OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: BorderSide.none),
      ),
    );
  }
}
