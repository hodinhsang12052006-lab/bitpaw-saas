/// Model cho response GET /api/dashboard/stats (xem app.py::api_dashboard_stats) — CHỈ
/// admin/super_admin gọi được (role_required), khớp đúng field trả về, không suy đoán thêm.
class DashboardStats {
  final int totalEmployees;
  final int employeesWorkedThisMonth;
  final double totalPayrollThisMonth;
  final List<String> chartLabels;
  final List<int> chartCong;
  final List<double> chartTien;
  final List<LeaveEntry> leaves;
  final TaskCounts tasks;

  DashboardStats({
    required this.totalEmployees,
    required this.employeesWorkedThisMonth,
    required this.totalPayrollThisMonth,
    required this.chartLabels,
    required this.chartCong,
    required this.chartTien,
    required this.leaves,
    required this.tasks,
  });

  factory DashboardStats.fromJson(Map<String, dynamic> json) {
    final chart = json['chart'] as Map<String, dynamic>? ?? {};
    return DashboardStats(
      totalEmployees: (json['total_employees'] as num?)?.toInt() ?? 0,
      employeesWorkedThisMonth: (json['employees_worked_this_month'] as num?)?.toInt() ?? 0,
      totalPayrollThisMonth: (json['total_payroll_this_month'] as num?)?.toDouble() ?? 0,
      chartLabels: (chart['labels'] as List<dynamic>? ?? []).map((e) => e.toString()).toList(),
      chartCong: (chart['cong'] as List<dynamic>? ?? []).map((e) => (e as num).toInt()).toList(),
      chartTien: (chart['tien'] as List<dynamic>? ?? []).map((e) => (e as num).toDouble()).toList(),
      leaves: (json['leaves'] as List<dynamic>? ?? [])
          .map((e) => LeaveEntry.fromJson(e as Map<String, dynamic>))
          .toList(),
      tasks: TaskCounts.fromJson(json['tasks'] as Map<String, dynamic>? ?? {}),
    );
  }
}

class LeaveEntry {
  final int day;
  final String note;

  LeaveEntry({required this.day, required this.note});

  factory LeaveEntry.fromJson(Map<String, dynamic> json) {
    return LeaveEntry(
      day: (json['day'] as num?)?.toInt() ?? 0,
      note: json['note']?.toString() ?? '',
    );
  }
}

class TaskCounts {
  final int pending;
  final int doing;
  final int done;

  TaskCounts({required this.pending, required this.doing, required this.done});

  factory TaskCounts.fromJson(Map<String, dynamic> json) {
    return TaskCounts(
      pending: (json['pending'] as num?)?.toInt() ?? 0,
      doing: (json['doing'] as num?)?.toInt() ?? 0,
      done: (json['done'] as num?)?.toInt() ?? 0,
    );
  }
}
