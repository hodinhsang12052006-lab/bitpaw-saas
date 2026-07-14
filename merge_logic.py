app_path = r"C:\Users\hodin\Desktop\PM_Ban_Hang\app.py"
core_app_path = r"C:\Users\hodin\Desktop\PM_Ban_Hang\.vscode\phanmemquanlydoanhthu\app (2).py"

# Read C:\Users\hodin\Desktop\PM_Ban_Hang\app.py
with open(app_path, 'r', encoding='utf-8') as f:
    app_content = f.read()

# Read app (2).py
with open(core_app_path, 'r', encoding='utf-8') as f:
    core_content = f.read()

# Extract imports and custom functions from core_content
# Let's import sqlite3, base64, SocketIO, requests
import_additions = "\nimport sqlite3\nimport base64\nfrom flask_socketio import SocketIO, emit, join_room\nimport requests\n"

# Replace app = Flask(...) to include socketio
# Let's search for "app = Flask(__name__, static_folder='static', template_folder='templates')"
flask_init = "app = Flask(__name__, static_folder='static', template_folder='templates')"
flask_init_replacement = "app = Flask(__name__, static_folder='static', template_folder='templates')\nsocketio = SocketIO(app, cors_allowed_origins='*')\n"

app_content = app_content.replace(flask_init, flask_init_replacement)

# Insert imports at the top
app_content = "import sqlite3\nimport base64\nfrom flask_socketio import SocketIO, emit, join_room\nimport requests\n" + app_content

# Now let's extract all custom functions, Socket.IO handlers, and endpoints from app (2).py
# The custom functions start around line 28 (def init_db():) and go until the end (line 1198)
# Let's extract this code from app (2).py
# We can find where "def init_db():" starts and slice until "if __name__ == '__main__':"
start_idx = core_content.find("def init_db():")
end_idx = core_content.find("if __name__ == '__main__':")

erp_logic = core_content[start_idx:end_idx]

# In erp_logic, let's resolve conflicts or duplicate routes:
# 1. @app.route('/') -> let's rename it to @app.route('/home_erp') so it does not conflict with @app.route('/') in app.py
erp_logic = erp_logic.replace("@app.route('/')\ndef home():", "@app.route('/home_erp')\ndef home():")

# 2. @app.route('/login', methods=['POST']) -> let's handle it inside app.py's login route instead to prevent conflict.
# Let's remove the JSON login route from erp_logic.
login_route_start = erp_logic.find("@app.route('/login'")
if login_route_start != -1:
    login_route_end = erp_logic.find("@app.route('/logout'", login_route_start)
    if login_route_end != -1:
        erp_logic = erp_logic[:login_route_start] + erp_logic[login_route_end:]

# 3. @app.route('/logout') -> let's remove it because app.py already has a robust /logout route.
logout_route_start = erp_logic.find("@app.route('/logout'")
if logout_route_start != -1:
    logout_route_end = erp_logic.find("# ==========================================", logout_route_start)
    if logout_route_end != -1:
        erp_logic = erp_logic[:logout_route_start] + erp_logic[logout_route_end:]

# 4. @app.route('/dashboard') -> let's remove it because app.py has /dashboard as the main retail/unified redirect page.
# If a user visits /dashboard in the merged app, it will redirect to pos/spa/karaoke/dashboard based on their mode.
dashboard_route_start = erp_logic.find("@app.route('/dashboard'")
if dashboard_route_start != -1:
    dashboard_route_end = erp_logic.find("@app.route('/nhanvien'", dashboard_route_start)
    if dashboard_route_end != -1:
        erp_logic = erp_logic[:dashboard_route_start] + erp_logic[dashboard_route_end:]

# Add init_db() call in erp_logic
erp_logic = "\n# ========== INTEGRATED CORE ERP LOGIC ==========\n" + erp_logic

# Find where "if __name__ == '__main__':" starts in app_content and insert erp_logic right before it
main_idx = app_content.find("if __name__ == '__main__':")
app_content = app_content[:main_idx] + erp_logic + "\n" + app_content[main_idx:]

# Replace "app.run(port=5001, debug=True)" at the end with "socketio.run(app, port=5001, debug=True)"
app_content = app_content.replace("app.run(port=5001, debug=True)", "init_db()\n    socketio.run(app, port=5001, debug=True)")

# Let's update the login route in app_content to handle both forms and JSON API login
# Let's search for "def login():" inside app_content and view its content
# In our login route:
# @app.route('/login', methods=['GET', 'POST'])
# def login():
#     if request.method == 'POST':
#         email = request.form['email']
#         password = request.form['password']

# Let's replace the POST form handling to check for JSON:
login_handler_start = """@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']"""

login_handler_replacement = """@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        # Handle JSON API login from the employee/client apps
        if request.is_json:
            data = request.get_json()
            email = data.get('email', '').strip()
            password = data.get('password', '')
            if not email or not password:
                return jsonify({'success': False, 'message': 'Vui lòng nhập đủ thông tin.'})
            try:
                res = supabase.auth.sign_in_with_password({"email": email, "password": password})
                session['user_id'] = res.user.id
                session['user_email'] = email
                session['access_token'] = res.session.access_token
                
                # Fetch business type for redirect
                mode_res = supabase.table('system_settings').select('value').eq('key', 'business_mode').execute()
                mode = mode_res.data[0]['value'] if mode_res.data else 'none'
                
                redirect_url = url_for('setup')
                if mode == 'retail':
                    redirect_url = url_for('index')
                elif mode == 'fnb':
                    redirect_url = url_for('pos')
                elif mode == 'spa':
                    redirect_url = url_for('spa')
                elif mode == 'karaoke':
                    redirect_url = url_for('karaoke')
                    
                return jsonify({'success': True, 'message': 'Đăng nhập thành công!', 'redirect_url': redirect_url})
            except Exception as e:
                return jsonify({'success': False, 'message': 'Sai email hoặc mật khẩu!'})
                
        email = request.form['email']
        password = request.form['password']"""

app_content = app_content.replace(login_handler_start, login_handler_replacement)

# Save the merged file
with open(app_path, 'w', encoding='utf-8') as f:
    f.write(app_content)

print("App merge completed successfully!")
