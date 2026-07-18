import glob
import re

files = glob.glob('templates/chamcong*.html') + ['templates/app_nhanvien.html', 'templates/chamcong.html']
for fp in sorted(list(set(files))):
    print(f"=== File: {fp} ===")
    with open(fp, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    # Search for script files or APIs
    apis = re.findall(r'[\'"](/api/[^?\'"]+)[\'"]', content)
    supabase_calls = re.findall(r'supabase\.from\([\'"](\w+)[\'"]\)', content)
    print(f"  Local APIs used: {set(apis)}")
    print(f"  Supabase tables queried: {set(supabase_calls)}")
