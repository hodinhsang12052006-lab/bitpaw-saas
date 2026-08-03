# File này được auto_build.py TỰ SINH mỗi lần chạy — sửa tay sẽ bị ghi đè ở lần chạy kế
# tiếp. Muốn đổi vĩnh viễn, sửa hàm write_build_spec() trong auto_build.py.
block_cipher = None

a = Analysis(
    ['desktop_app/launcher.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('templates', 'templates'),
        ('static', 'static'),
        ('translations', 'translations'),
        # KHÔNG đóng gói '.env' — tránh lộ API key dùng chung mọi tenant vào file .exe.
    ],
    hiddenimports=[
        'ai_context_engine', 'ai_sales_prompts', 'ai_memory_engine', 'ai_vector_rag',
        'ai_nurturing_engine', 'email_service', 'tenant_engine', 'currency_utils',
        'payment_us_engine', 'auth_service', 'i18n', 'blueprints.spa_bp',
        'ai_function_tools', 'ai_deepseek_client',
        'desktop_app.secure_db', 'desktop_app.license_manager',
        'desktop_app.updater', 'desktop_app.realtime_client',
        'pymongo', 'bson', 'gridfs',
        'montydb', 'montydb.storage', 'montydb.storage.sqlite', 'montydb.types',
        'sqlalchemy', 'sqlalchemy.dialects.sqlite',
        # sqlcipher3 CỐ Ý không có ở đây — auto_build.py loại gói này khỏi bước cài đặt (hay
        # lỗi build từ source trên Windows). desktop_app/secure_db.py tự báo lỗi rõ ràng lúc
        # chạy nếu thiếu, không làm sập cả app (xem ai_function_tools.py: book_appointment()).
        'keyring.backends.Windows', 'keyring.backends.fail',
        'socketio', 'engineio', 'engineio.async_drivers.threading',
        'webview.platforms.edgechromium', 'webview.platforms.winforms', 'clr_loader', 'clr',
        'flask_limiter', 'flask_limiter.util',
    ] + [],
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
    console=False,
    icon='desktop_app/temp_icon.ico',
)
