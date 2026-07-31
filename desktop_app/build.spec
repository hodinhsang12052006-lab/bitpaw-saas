# Build bằng: pyinstaller desktop_app/build.spec --distpath dist --workpath build
# Chạy lệnh này từ THƯ MỤC GỐC project (không phải trong desktop_app/) để pathex đúng.
import sys

block_cipher = None

a = Analysis(
    ['desktop_app/launcher.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('templates', 'templates'),
        ('static', 'static'),
        ('translations', 'translations'),
        # KHÔNG đóng gói '.env' vào đây — file .exe có thể bị giải nén/đọc ngược bởi khách hàng,
        # để lộ SQUARE_ACCESS_TOKEN/DEEPSEEK_API_KEY dùng chung cho mọi tenant. Xem license_manager.py:
        # các secret nên được cấp về qua response của API verify license, không bundle sẵn.
    ],
    hiddenimports=[
        # PyInstaller không tự dò được các import động/try-except trong app.py — thêm thủ công.
        # Nếu chạy .exe báo "ModuleNotFoundError: X", thêm X vào danh sách này rồi build lại.
        'pymongo', 'bson', 'gridfs', 'montydb',
        'flask_limiter', 'flask_limiter.util',
        'ai_context_engine', 'ai_sales_prompts', 'ai_memory_engine',
        'ai_vector_rag', 'ai_nurturing_engine', 'email_service',
        'tenant_engine', 'currency_utils', 'payment_us_engine',
        'auth_service', 'i18n', 'blueprints.spa_bp',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='BitPawOS',
    debug=False,
    strip=False,
    upx=True,
    console=False,   # False = ẩn cửa sổ console đen, chỉ hiện webview
    icon='desktop_app/icon.ico',  # tự thêm file icon.ico, hoặc xoá dòng này để dùng icon mặc định
)
