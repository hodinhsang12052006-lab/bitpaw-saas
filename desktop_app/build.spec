# Build bằng: pyinstaller desktop_app/build.spec --distpath dist --workpath build
# Chạy lệnh này từ THƯ MỤC GỐC project (không phải trong desktop_app/) để pathex/datas đúng.
# Chỉ build ra .exe Windows nếu chạy TRÊN Windows — PyInstaller không cross-compile,
# xem ghi chú macOS ở cuối hướng dẫn build (không dùng file .spec này để build macOS).
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
        # --- Module nội bộ của app.py (import động/try-except PyInstaller không tự dò hết) ---
        'ai_context_engine', 'ai_sales_prompts', 'ai_memory_engine',
        'ai_vector_rag', 'ai_nurturing_engine', 'email_service',
        'tenant_engine', 'currency_utils', 'payment_us_engine',
        'auth_service', 'i18n', 'blueprints.spa_bp',
        'ai_function_tools', 'ai_deepseek_client',

        # --- Desktop app modules (import trễ bên trong hàm, PyInstaller cần khai báo tay) ---
        'desktop_app.secure_db', 'desktop_app.license_manager',
        'desktop_app.updater', 'desktop_app.realtime_client',

        # --- pymongo/bson/gridfs (vẫn dùng cho mongo_client.py cũ + local_db.py) ---
        'pymongo', 'bson', 'gridfs',

        # --- montydb: tự chọn storage engine lúc CHẠY (không phải lúc import), PyInstaller
        # không dò ra được — thiếu dòng này sẽ lỗi "no module named montydb.storage.sqlite" ---
        'montydb', 'montydb.storage', 'montydb.storage.sqlite', 'montydb.types',

        # --- sqlalchemy + sqlcipher3 (desktop_app/secure_db.py) ---
        'sqlalchemy', 'sqlalchemy.dialects.sqlite', 'sqlcipher3', 'sqlcipher3.dbapi2',

        # --- keyring: chọn backend qua entry_points lúc CHẠY, PyInstaller không tự thấy —
        # thiếu dòng backends.Windows sẽ lỗi "No recommended backend found" khi gọi keyring ---
        'keyring.backends.Windows', 'keyring.backends.fail',

        # --- python-socketio client (desktop_app/realtime_client.py) ---
        'socketio', 'engineio', 'engineio.async_drivers.threading',

        # --- pywebview trên Windows: backend mặc định là WebView2 (Edge Chromium) qua pythonnet ---
        'webview.platforms.edgechromium', 'webview.platforms.winforms',
        'clr_loader', 'clr',

        'flask_limiter', 'flask_limiter.util',
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
    console=False,   # False = ẩn cửa sổ console đen, chỉ hiện webview (chế độ "windowed")
    icon='desktop_app/icon.ico',  # tự thêm file icon.ico 256x256, hoặc xoá dòng này để dùng icon mặc định
)
