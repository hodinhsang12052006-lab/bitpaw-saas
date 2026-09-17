import 'dart:io';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';
import 'package:signature/signature.dart';

import '../../models/job_task_model.dart';
import '../../services/api_service.dart';
import '../../services/technical_job_service.dart';

/// Hoàn thành job Kỹ Thuật với bằng chứng — mirror phần "Ảnh/chữ ký + phụ tùng" của
/// chamcong_kythuat.html (web): chụp ảnh hiện trường, khách ký xác nhận trên máy, liệt kê phụ
/// tùng đã dùng (tự tính tiền + tạo hoá đơn phía backend nếu > 0).
class TechnicalJobDetailScreen extends StatefulWidget {
  final JobTaskModel job;
  final String workerName;

  const TechnicalJobDetailScreen({super.key, required this.job, required this.workerName});

  @override
  State<TechnicalJobDetailScreen> createState() => _TechnicalJobDetailScreenState();
}

class _TechnicalJobDetailScreenState extends State<TechnicalJobDetailScreen> {
  late final TechnicalJobService _jobService;
  final ImagePicker _imagePicker = ImagePicker();
  final SignatureController _signatureController = SignatureController(penStrokeWidth: 3, penColor: Colors.black, exportBackgroundColor: Colors.white);

  final List<XFile> _photos = [];
  final List<_PartRow> _parts = [];
  bool _isSubmitting = false;

  final _currencyFormat = NumberFormat.currency(locale: 'vi_VN', symbol: 'đ', decimalDigits: 0);

  @override
  void initState() {
    super.initState();
    _jobService = TechnicalJobService(context.read<ApiService>());
  }

  @override
  void dispose() {
    _signatureController.dispose();
    for (final p in _parts) {
      p.dispose();
    }
    super.dispose();
  }

  Future<void> _takePhoto() async {
    final photo = await _imagePicker.pickImage(source: ImageSource.camera, imageQuality: 80, maxWidth: 1600);
    if (photo != null) setState(() => _photos.add(photo));
  }

  void _addPartRow() {
    setState(() => _parts.add(_PartRow()));
  }

  void _removePartRow(_PartRow row) {
    setState(() {
      _parts.remove(row);
      row.dispose();
    });
  }

  double get _partsTotal => _parts.fold(0, (sum, p) => sum + p.lineTotal);

  Future<void> _submit() async {
    setState(() => _isSubmitting = true);
    try {
      final photoUrls = <String>[];
      for (final photo in _photos) {
        final bytes = await File(photo.path).readAsBytes();
        final url = await _jobService.uploadImage(bytes, photo.name, 'job_photo');
        photoUrls.add(url);
      }

      String? signatureUrl;
      if (_signatureController.isNotEmpty) {
        final sigBytes = await _signatureController.toPngBytes();
        if (sigBytes != null) {
          signatureUrl = await _jobService.uploadImage(sigBytes, 'signature_${widget.job.id}.png', 'job_signature');
        }
      }

      final parts = _parts
          .where((p) => p.isValid)
          .map((p) => PartUsed(name: p.nameController.text.trim(), qty: p.qty, unitPrice: p.unitPrice))
          .toList();

      final result = await _jobService.completeJob(
        widget.job.id,
        widget.workerName,
        photoUrls: photoUrls,
        signatureUrl: signatureUrl,
        partsUsed: parts,
      );
      if (!mounted) return;
      setState(() => _isSubmitting = false);
      if (result.success) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(result.message), backgroundColor: Colors.green));
        Navigator.of(context).pop();
      } else {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(result.message), backgroundColor: Colors.redAccent));
      }
    } catch (e) {
      if (!mounted) return;
      setState(() => _isSubmitting = false);
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Lỗi: $e'), backgroundColor: Colors.redAccent));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(widget.job.tenKhach)),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          Text(widget.job.diaChi, style: const TextStyle(color: Colors.white70)),
          const SizedBox(height: 4),
          Text(widget.job.noiDung, style: const TextStyle(color: Colors.white54, fontSize: 13)),
          const SizedBox(height: 24),

          const Text('Ảnh hiện trường', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 16)),
          const SizedBox(height: 10),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              ..._photos.map((p) => ClipRRect(
                    borderRadius: BorderRadius.circular(10),
                    child: Image.file(File(p.path), width: 80, height: 80, fit: BoxFit.cover),
                  )),
              InkWell(
                onTap: _takePhoto,
                borderRadius: BorderRadius.circular(10),
                child: Container(
                  width: 80,
                  height: 80,
                  decoration: BoxDecoration(color: Colors.white.withOpacity(0.05), borderRadius: BorderRadius.circular(10)),
                  child: const Icon(Icons.add_a_photo_rounded, color: Colors.white38),
                ),
              ),
            ],
          ),

          const SizedBox(height: 24),
          const Text('Chữ ký khách hàng', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 16)),
          const SizedBox(height: 10),
          Container(
            height: 180,
            decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(10)),
            child: Signature(controller: _signatureController, backgroundColor: Colors.white),
          ),
          Align(
            alignment: Alignment.centerRight,
            child: TextButton(onPressed: () => setState(() => _signatureController.clear()), child: const Text('Xoá chữ ký')),
          ),

          const SizedBox(height: 12),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              const Text('Phụ tùng đã dùng', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 16)),
              TextButton.icon(onPressed: _addPartRow, icon: const Icon(Icons.add_rounded, size: 18), label: const Text('Thêm')),
            ],
          ),
          ..._parts.map((row) => _buildPartRow(row)),
          if (_parts.isNotEmpty)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  const Text('Tổng phụ tùng', style: TextStyle(color: Colors.white70)),
                  Text(_currencyFormat.format(_partsTotal), style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
                ],
              ),
            ),

          const SizedBox(height: 24),
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
                  : const Text('Hoàn thành công việc', style: TextStyle(fontWeight: FontWeight.bold)),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildPartRow(_PartRow row) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        children: [
          Expanded(
            flex: 3,
            child: TextField(
              controller: row.nameController,
              style: const TextStyle(color: Colors.white, fontSize: 13),
              decoration: const InputDecoration(hintText: 'Tên phụ tùng', hintStyle: TextStyle(color: Colors.white38, fontSize: 13), isDense: true),
            ),
          ),
          const SizedBox(width: 6),
          Expanded(
            flex: 1,
            child: TextField(
              controller: row.qtyController,
              keyboardType: TextInputType.number,
              style: const TextStyle(color: Colors.white, fontSize: 13),
              decoration: const InputDecoration(hintText: 'SL', hintStyle: TextStyle(color: Colors.white38, fontSize: 13), isDense: true),
              onChanged: (_) => setState(() {}),
            ),
          ),
          const SizedBox(width: 6),
          Expanded(
            flex: 2,
            child: TextField(
              controller: row.priceController,
              keyboardType: TextInputType.number,
              style: const TextStyle(color: Colors.white, fontSize: 13),
              decoration: const InputDecoration(hintText: 'Đơn giá', hintStyle: TextStyle(color: Colors.white38, fontSize: 13), isDense: true),
              onChanged: (_) => setState(() {}),
            ),
          ),
          IconButton(
            icon: const Icon(Icons.close_rounded, color: Colors.white38, size: 18),
            onPressed: () => _removePartRow(row),
          ),
        ],
      ),
    );
  }
}

class _PartRow {
  final nameController = TextEditingController();
  final qtyController = TextEditingController(text: '1');
  final priceController = TextEditingController(text: '0');

  double get qty => double.tryParse(qtyController.text.replaceAll(',', '.')) ?? 0;
  double get unitPrice => double.tryParse(priceController.text.replaceAll(',', '.')) ?? 0;
  double get lineTotal => qty * unitPrice;
  bool get isValid => nameController.text.trim().isNotEmpty && qty > 0 && unitPrice >= 0;

  void dispose() {
    nameController.dispose();
    qtyController.dispose();
    priceController.dispose();
  }
}
