import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../models/employee_model.dart';
import '../../models/job_task_model.dart';
import '../../services/api_service.dart';
import '../../services/pos_service.dart';
import '../../services/technical_job_service.dart';
import 'technical_job_detail_screen.dart';

/// Điều phối job Kỹ Thuật — mirror chamcong_kythuat.html (web): kỹ thuật viên chọn tên mình
/// (thiết bị dùng chung, cùng mô hình với AttendanceScreen), xem việc "Chờ Nhận" (bấm để nhận)
/// và "Đã Nhận" của riêng mình (bấm để mở chi tiết/hoàn thành).
class TechnicalJobsScreen extends StatefulWidget {
  const TechnicalJobsScreen({super.key});

  @override
  State<TechnicalJobsScreen> createState() => _TechnicalJobsScreenState();
}

class _TechnicalJobsScreenState extends State<TechnicalJobsScreen> {
  late final PosService _posService;
  late final TechnicalJobService _jobService;

  bool _isLoadingEmployees = true;
  String? _loadError;
  List<EmployeeModel> _employees = [];
  EmployeeModel? _selectedTech;

  bool _isLoadingJobs = false;
  List<JobTaskModel> _jobs = [];

  @override
  void initState() {
    super.initState();
    final apiService = context.read<ApiService>();
    _posService = PosService(apiService);
    _jobService = TechnicalJobService(apiService);
    _loadEmployees();
  }

  Future<void> _loadEmployees() async {
    setState(() {
      _isLoadingEmployees = true;
      _loadError = null;
    });
    try {
      final employees = await _posService.fetchEmployees();
      if (!mounted) return;
      setState(() {
        _employees = employees;
        _isLoadingEmployees = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loadError = 'Không tải được danh sách kỹ thuật viên. Kéo xuống để thử lại.';
        _isLoadingEmployees = false;
      });
    }
  }

  Future<void> _loadJobs() async {
    if (_selectedTech == null) return;
    setState(() => _isLoadingJobs = true);
    try {
      final jobs = await _jobService.fetchJobsForWorker(_selectedTech!.hoTen);
      if (!mounted) return;
      setState(() {
        _jobs = jobs;
        _isLoadingJobs = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _isLoadingJobs = false);
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Không tải được công việc: $e'), backgroundColor: Colors.redAccent));
    }
  }

  Future<void> _handleJobTap(JobTaskModel job) async {
    if (job.trangThai == 'Chờ Nhận') {
      try {
        await _jobService.acceptJob(job.id, _selectedTech!.hoTen);
        await _loadJobs();
      } catch (e) {
        if (!mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$e'), backgroundColor: Colors.redAccent));
      }
    } else {
      await Navigator.of(context).push(
        MaterialPageRoute(builder: (_) => TechnicalJobDetailScreen(job: job, workerName: _selectedTech!.hoTen)),
      );
      if (mounted) _loadJobs();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Điều phối — Kỹ thuật')),
      body: _isLoadingEmployees
          ? const Center(child: CircularProgressIndicator(color: Color(0xFF06B6D4)))
          : _loadError != null
              ? Center(child: Padding(padding: const EdgeInsets.all(20), child: Text(_loadError!, style: const TextStyle(color: Colors.redAccent))))
              : Column(
                  children: [
                    Padding(
                      padding: const EdgeInsets.all(16),
                      child: Container(
                        padding: const EdgeInsets.symmetric(horizontal: 12),
                        decoration: BoxDecoration(color: Colors.white.withOpacity(0.05), borderRadius: BorderRadius.circular(10)),
                        child: DropdownButtonHideUnderline(
                          child: DropdownButton<EmployeeModel>(
                            isExpanded: true,
                            value: _selectedTech,
                            hint: const Text('-- Chọn tên kỹ thuật viên --', style: TextStyle(color: Colors.white38)),
                            dropdownColor: const Color(0xFF14192E),
                            items: _employees
                                .map((e) => DropdownMenuItem(value: e, child: Text(e.hoTen, style: const TextStyle(color: Colors.white))))
                                .toList(),
                            onChanged: (v) {
                              setState(() => _selectedTech = v);
                              _loadJobs();
                            },
                          ),
                        ),
                      ),
                    ),
                    Expanded(child: _buildJobList()),
                  ],
                ),
    );
  }

  Widget _buildJobList() {
    if (_selectedTech == null) {
      return const Center(child: Text('Chọn tên để xem công việc được giao.', style: TextStyle(color: Colors.white38)));
    }
    if (_isLoadingJobs) {
      return const Center(child: CircularProgressIndicator(color: Color(0xFF06B6D4)));
    }
    if (_jobs.isEmpty) {
      return const Center(child: Text('Không có công việc nào.', style: TextStyle(color: Colors.white38)));
    }
    return RefreshIndicator(
      onRefresh: _loadJobs,
      color: const Color(0xFF06B6D4),
      child: ListView.separated(
        padding: const EdgeInsets.all(16),
        itemCount: _jobs.length,
        separatorBuilder: (_, __) => const SizedBox(height: 10),
        itemBuilder: (context, index) {
          final job = _jobs[index];
          final isPending = job.trangThai == 'Chờ Nhận';
          final color = isPending ? Colors.blueAccent : Colors.orangeAccent;
          return Material(
            color: Colors.white.withOpacity(0.05),
            borderRadius: BorderRadius.circular(12),
            child: InkWell(
              borderRadius: BorderRadius.circular(12),
              onTap: () => _handleJobTap(job),
              child: Padding(
                padding: const EdgeInsets.all(14),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Expanded(child: Text(job.tenKhach, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold))),
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                          decoration: BoxDecoration(color: color.withOpacity(0.15), borderRadius: BorderRadius.circular(20)),
                          child: Text(job.trangThai, style: TextStyle(color: color, fontSize: 11)),
                        ),
                      ],
                    ),
                    const SizedBox(height: 4),
                    Text(job.diaChi, style: const TextStyle(color: Colors.white54, fontSize: 12)),
                    const SizedBox(height: 6),
                    Text(job.noiDung, style: const TextStyle(color: Colors.white70, fontSize: 13), maxLines: 2, overflow: TextOverflow.ellipsis),
                    if (isPending) ...[
                      const SizedBox(height: 8),
                      const Text('Bấm để nhận việc', style: TextStyle(color: Color(0xFF06B6D4), fontSize: 12, fontWeight: FontWeight.w600)),
                    ],
                  ],
                ),
              ),
            ),
          );
        },
      ),
    );
  }
}
