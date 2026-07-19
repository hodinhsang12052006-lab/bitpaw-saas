
        // Flask session (see @login_required on the /add_expense route in app.py) already
        // gates this whole page server-side, so there is no client-side "logged out" state
        // to handle here. Data now comes from the internal /api/expenses Flask/MongoDB API
        // instead of a second, disconnected third-party auth identity.
        async function hrApi(path, options) {
            const res = await fetch(path, {
                ...options,
                headers: { 'Content-Type': 'application/json', ...(options && options.headers) },
            });
            const body = await res.json().catch(() => ({}));
            if (!res.ok || body.success === false) {
                throw new Error(body.error || `Lỗi máy chủ (${res.status})`);
            }
            return body;
        }

        // DOM elements
        const amountRaw = document.getElementById('amountRaw');
        const amountHidden = document.getElementById('amountHidden');
        const form = document.getElementById('expenseForm');
        const submitBtn = document.getElementById('submitBtn');
        const toast = document.getElementById('toast');
        let expenseChart = null;
        let categoryChart = null;

        // ========== I18N ==========
        let currentLang = localStorage.getItem('bitpaw_lang') || """";
        const translations = {
            vi: {
                addexpense_tagline: 'Quản lý chi tiêu thông minh',
                addexpense_form_title: 'Nhập Khoản Chi',
                addexpense_form_subtitle: 'Ghi lại dòng tiền chi ra để AI phân tích chính xác',
                addexpense_category_label: 'Danh mục',
                addexpense_opt_personnel: '🧑‍💼 Nhân sự (Lương, thưởng)',
                addexpense_opt_supplies: '📦 Vật tư, nguyên liệu',
                addexpense_opt_marketing: '📢 Marketing, quảng cáo',
                addexpense_opt_operations: '⚙️ Vận hành (điện, nước, internet)',
                addexpense_opt_rent: '🏢 Thuê mặt bằng',
                addexpense_opt_other: '🔄 Khác',
                addexpense_reason_label: 'Lý do chi tiêu',
                addexpense_reason_placeholder: 'VD: Tiền điện, Mua vật tư...',
                addexpense_amount_label: 'Số tiền (VNĐ)',
                addexpense_date_label: 'Ngày chi',
                addexpense_quickadd_label: 'Thêm nhanh',
                addexpense_chip_electricity: '⚡ Điện 500k',
                addexpense_chip_electricity_desc: 'Tiền điện',
                addexpense_chip_water: '💧 Nước 300k',
                addexpense_chip_water_desc: 'Tiền nước',
                addexpense_chip_rent: '🏢 Thuê mặt bằng 5tr',
                addexpense_chip_rent_desc: 'Thuê mặt bằng',
                addexpense_chip_salary: '👥 Lương NV 20tr',
                addexpense_chip_salary_desc: 'Lương nhân viên',
                addexpense_submit_btn: 'Lưu Khoản Chi',
                addexpense_back_btn: 'Về Trang Chủ',
                addexpense_chart30_title: 'Chi tiêu 30 ngày qua',
                addexpense_chart_category_title: 'Phân loại chi tiêu (7 ngày)',
                addexpense_recent_title: '5 Khoản Chi Gần Nhất',
                addexpense_export_pdf_btn: 'Xuất PDF',
                addexpense_view_all_link: '📋 Xem toàn bộ lịch sử chi tiêu →',
                addexpense_support_title: 'Gửi yêu cầu hỗ trợ',
                addexpense_support_name_placeholder: 'Tên của bạn',
                addexpense_support_phone_placeholder: 'Số điện thoại / Zalo',
                addexpense_support_message_placeholder: 'Mô tả vấn đề cần hỗ trợ...',
                addexpense_support_submit_btn: 'Gửi yêu cầu',
                addexpense_toast_default: 'Thông báo',
                addexpense_msg_no_expenses: 'Chưa có chi tiêu nào',
                addexpense_chart_dataset_label: 'Chi tiêu (VNĐ)',
                addexpense_confirm_delete: 'Xóa khoản chi này?',
                addexpense_toast_delete_error: 'Lỗi xóa',
                addexpense_toast_deleted: 'Đã xóa',
                addexpense_toast_load_error: 'Lỗi tải dữ liệu chi tiêu',
                addexpense_toast_invalid_amount: 'Vui lòng nhập số tiền hợp lệ!',
                addexpense_toast_large_amount: '⚠️ Khoản chi lớn hơn 10 triệu! Hãy kiểm tra lại.',
                addexpense_processing: 'Đang xử lý...',
                addexpense_toast_add_success: '✅ Đã thêm khoản chi thành công!',
                addexpense_toast_save_error_prefix: '❌ Lỗi khi lưu chi tiêu: ',
                addexpense_toast_fill_all: 'Vui lòng nhập đầy đủ',
                addexpense_toast_support_sent: '✅ Yêu cầu đã gửi! Chúng tôi sẽ liên hệ lại trong 15 phút.',
                addexpense_toast_generic_error_prefix: 'Lỗi: '
            },
            en: {
                addexpense_tagline: 'Smart expense management',
                addexpense_form_title: 'Enter Expense',
                addexpense_form_subtitle: 'Log outgoing cash flow so the AI can analyze it accurately',
                addexpense_category_label: 'Category',
                addexpense_opt_personnel: '🧑‍💼 Personnel (Salary, bonuses)',
                addexpense_opt_supplies: '📦 Supplies, materials',
                addexpense_opt_marketing: '📢 Marketing, advertising',
                addexpense_opt_operations: '⚙️ Operations (electricity, water, internet)',
                addexpense_opt_rent: '🏢 Rent',
                addexpense_opt_other: '🔄 Other',
                addexpense_reason_label: 'Reason for expense',
                addexpense_reason_placeholder: 'E.g.: Electricity bill, Supply purchase...',
                addexpense_amount_label: 'Amount (VND)',
                addexpense_date_label: 'Expense date',
                addexpense_quickadd_label: 'Quick add',
                addexpense_chip_electricity: '⚡ Electricity 500k',
                addexpense_chip_electricity_desc: 'Electricity bill',
                addexpense_chip_water: '💧 Water 300k',
                addexpense_chip_water_desc: 'Water bill',
                addexpense_chip_rent: '🏢 Rent 5M',
                addexpense_chip_rent_desc: 'Rent',
                addexpense_chip_salary: '👥 Staff salary 20M',
                addexpense_chip_salary_desc: 'Staff salary',
                addexpense_submit_btn: 'Save Expense',
                addexpense_back_btn: 'Back to Dashboard',
                addexpense_chart30_title: 'Expenses over the last 30 days',
                addexpense_chart_category_title: 'Category breakdown (7 days)',
                addexpense_recent_title: '5 Most Recent Expenses',
                addexpense_export_pdf_btn: 'Export PDF',
                addexpense_view_all_link: '📋 View all expense history →',
                addexpense_support_title: 'Send a support request',
                addexpense_support_name_placeholder: 'Your name',
                addexpense_support_phone_placeholder: 'Phone number / Zalo',
                addexpense_support_message_placeholder: 'Describe what you need help with...',
                addexpense_support_submit_btn: 'Send request',
                addexpense_toast_default: 'Notification',
                addexpense_msg_no_expenses: 'No expenses yet',
                addexpense_chart_dataset_label: 'Expenses (VND)',
                addexpense_confirm_delete: 'Delete this expense?',
                addexpense_toast_delete_error: 'Delete error',
                addexpense_toast_deleted: 'Deleted',
                addexpense_toast_load_error: 'Error loading expense data',
                addexpense_toast_invalid_amount: 'Please enter a valid amount!',
                addexpense_toast_large_amount: '⚠️ This expense is over 10 million! Please double-check.',
                addexpense_processing: 'Processing...',
                addexpense_toast_add_success: '✅ Expense added successfully!',
                addexpense_toast_save_error_prefix: '❌ Error saving expense: ',
                addexpense_toast_fill_all: 'Please fill in all fields',
                addexpense_toast_support_sent: '✅ Request sent! We will contact you within 15 minutes.',
                addexpense_toast_generic_error_prefix: 'Error: '
            }
        };
        function t(key) {
            return (translations[currentLang] && translations[currentLang][key]) || translations.vi[key] || key;
        }
        function applyStaticTranslations() {
            document.querySelectorAll('[data-i18n]').forEach(el => { el.innerHTML = t(el.getAttribute('data-i18n')); });
            document.querySelectorAll('[data-i18n-placeholder]').forEach(el => { el.placeholder = t(el.getAttribute('data-i18n-placeholder')); });
            document.querySelectorAll('[data-i18n-title]').forEach(el => { el.title = t(el.getAttribute('data-i18n-title')); });
            const langBtn = document.getElementById('langToggleBtn');
            if (langBtn) langBtn.innerText = currentLang === 'vi' ? 'EN' : 'VI';
        }
        function changeLanguage(lang) {
            currentLang = lang;
            localStorage.setItem('bitpaw_lang', lang);
            applyStaticTranslations();
            // Refresh JS-rendered parts (recent list, chart labels) so they pick up the new language.
            try { loadExpenseData(); } catch(e) {}
        }
        applyStaticTranslations();
        document.getElementById('langToggleBtn')?.addEventListener('click', () => changeLanguage(currentLang === 'vi' ? 'en' : 'vi'));

        // Helper: toast
        function showToast(message, isError = false) {
            toast.textContent = message;
            toast.style.borderColor = isError ? '#ef4444' : '#10b981';
            toast.classList.add('show');
            setTimeout(() => toast.classList.remove('show'), 3000);
        }

        // Format số tiền
        function formatNumberInput(e) {
            let value = e.target.value.replace(/[^0-9]/g, '');
            if (value === '') value = '0';
            let intValue = parseInt(value, 10);
            e.target.value = intValue.toLocaleString('vi-VN');
            amountHidden.value = intValue;
        }
        amountRaw.addEventListener('input', formatNumberInput);

        // Ngày mặc định
        const today = new Date().toISOString().slice(0,10);
        document.getElementById('expenseDate').value = today;

        // Chip nhanh
        document.querySelectorAll('.expense-chip').forEach(chip => {
            chip.addEventListener('click', () => {
                const descKey = chip.getAttribute('data-desc-key');
                const amt = chip.getAttribute('data-amount');
                document.querySelector('input[name="description"]').value = t(descKey);
                amountRaw.value = parseInt(amt).toLocaleString('vi-VN');
                amountHidden.value = amt;
                amountRaw.focus();
            });
        });

        // ========== LOAD EXPENSE DATA (bar + pie + recent) ==========
        async function loadExpenseData() {
            try {
                const body = await hrApi('/api/expenses');
                const data = body.data || [];

                // 1. Bar chart 30 ngày
                const dateMap = new Map();
                for (let i = 0; i < 30; i++) {
                    const d = new Date();
                    d.setDate(d.getDate() - (29 - i));
                    const key = d.toISOString().slice(0,10);
                    dateMap.set(key, 0);
                }
                if (data) {
                    data.forEach(item => {
                        if (dateMap.has(item.expense_date)) dateMap.set(item.expense_date, dateMap.get(item.expense_date) + item.amount);
                    });
                }
                const labels = Array.from(dateMap.keys()).map(d => d.slice(5));
                const barData = Array.from(dateMap.values());
                const ctxBar = document.getElementById('expenseChart').getContext('2d');
                if (expenseChart) expenseChart.destroy();
                expenseChart = new Chart(ctxBar, {
                    type: 'bar',
                    data: { labels, datasets: [{ label: t('addexpense_chart_dataset_label'), data: barData, backgroundColor: '#f43f5e', borderRadius: 6 }] },
                    options: { responsive: true, maintainAspectRatio: true, plugins: { legend: { labels: { color: '#ccc' } } }, scales: { y: { ticks: { callback: v => v.toLocaleString() } } } }
                });

                // 2. Pie chart 7 ngày theo category
                const sevenDaysAgo = new Date(); sevenDaysAgo.setDate(sevenDaysAgo.getDate() - 7);
                const recent7 = data?.filter(i => i.expense_date >= sevenDaysAgo.toISOString().slice(0,10)) || [];
                const catMap = new Map();
                recent7.forEach(i => catMap.set(i.category, (catMap.get(i.category) || 0) + i.amount));
                const ctxPie = document.getElementById('categoryChart').getContext('2d');
                if (categoryChart) categoryChart.destroy();
                categoryChart = new Chart(ctxPie, {
                    type: 'pie',
                    data: { labels: Array.from(catMap.keys()), datasets: [{ data: Array.from(catMap.values()), backgroundColor: ['#f43f5e','#a855f7','#3b82f6','#10b981','#f97316','#eab308'] }] },
                    options: { responsive: true, plugins: { legend: { labels: { color: '#ccc' } } } }
                });

                // 3. Danh sách 5 gần nhất + xóa
                const recentList = data.slice(0,5);
                const listDiv = document.getElementById('recentList');
                if (recentList.length === 0) {
                    listDiv.innerHTML = `<div class="text-center text-gray-500 text-sm p-4">${t('addexpense_msg_no_expenses')}</div>`;
                } else {
                    listDiv.innerHTML = recentList.map(item => `
                        <div class="recent-item">
                            <div><span class="text-rose-300 font-bold">${item.amount.toLocaleString()}₫</span> - ${item.description} <span class="text-gray-500 text-xs">(${item.expense_date})</span></div>
                            <button class="delete-expense text-red-400 hover:text-red-200 text-xs" data-id="${item.id}"><i class="fas fa-trash-alt"></i></button>
                        </div>
                    `).join('');
                    document.querySelectorAll('.delete-expense').forEach(btn => {
                        btn.addEventListener('click', async (e) => {
                            if(confirm(t('addexpense_confirm_delete'))) {
                                try {
                                    await hrApi(`/api/expenses/${btn.dataset.id}`, { method: 'DELETE' });
                                    showToast(t('addexpense_toast_deleted'));
                                    loadExpenseData();
                                } catch (err) {
                                    showToast(t('addexpense_toast_delete_error'), true);
                                }
                            }
                        });
                    });
                }
            } catch(err) {
                console.error(err);
                showToast(t('addexpense_toast_load_error'), true);
            }
        }

        // ========== SUBMIT FORM ==========
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const amountVal = amountHidden.value;
            if (!amountVal || parseInt(amountVal) <= 0) {
                showToast(t('addexpense_toast_invalid_amount'), true);
                return;
            }
            const amount = parseInt(amountVal);
            if (amount > 10000000) showToast(t('addexpense_toast_large_amount'), false);
            const formData = new FormData(form);
            const category = formData.get('category');
            const description = formData.get('description');
            const expenseDate = formData.get('expense_date') || today;

            submitBtn.disabled = true;
            submitBtn.innerHTML = `<i class="fas fa-spinner fa-spin"></i> ${t('addexpense_processing')}`;
            try {
                await hrApi('/api/expenses', {
                    method: 'POST',
                    body: JSON.stringify({ category, description, amount, expense_date: expenseDate }),
                });
                showToast(t('addexpense_toast_add_success'));
                document.querySelector('input[name="description"]').value = '';
                amountRaw.value = '';
                amountHidden.value = '';
                await loadExpenseData();
                setTimeout(() => { window.location.href = """"; }, 1500);
            } catch (err) {
                console.error(err);
                showToast(t('addexpense_toast_save_error_prefix') + err.message, true);
            } finally {
                submitBtn.disabled = false;
                submitBtn.innerHTML = `<i class="fas fa-save"></i> ${t('addexpense_submit_btn')}`;
            }
        });

        // CSKH track click + form hỗ trợ: gom về static/js/cskh_track.js (dùng chung,
        // gọi /api/cskh/click + /api/cskh/request qua Flask/MongoDB) — xem <script> nạp cuối trang.

        // ========== XUẤT PDF ==========
        document.getElementById('exportPdfBtn').addEventListener('click', () => {
            window.print();
        });

        // ========== KHỞI TẠO ==========
        // @login_required on the /add_expense Flask route already guarantees a valid
        // session before this page renders, so we load data directly — no client-side
        // login/register/logout gate needed.
        await loadExpenseData();

        // ========== 3D BACKGROUND GIỮ NGUYÊN ==========
        (function init3D() {
            const canvas = document.getElementById('bg-canvas');
            if (!canvas) return;
            const scene = new THREE.Scene();
            const camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);
            camera.position.z = 30;
            const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
            renderer.setSize(window.innerWidth, window.innerHeight);
            renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

            const isMobile = window.innerWidth < 768;
            const particlesCount = isMobile ? 500 : 1000;
            const geometry = new THREE.BufferGeometry();
            const positions = new Float32Array(particlesCount * 3);
            for (let i = 0; i < particlesCount * 3; i++) positions[i] = (Math.random() - 0.5) * 140;
            geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));

            const material = new THREE.PointsMaterial({ size: isMobile ? 0.14 : 0.2, color: 0xf43f5e, transparent: true, opacity: 0.5, blending: THREE.AdditiveBlending });
            const particles = new THREE.Points(geometry, material);
            scene.add(particles);

            const starCount = 80;
            const starPositions = new Float32Array(starCount * 3);
            const starVelocities = [];
            for (let i = 0; i < starCount; i++) {
                starPositions[i*3] = (Math.random() - 0.5) * 120;
                starPositions[i*3+1] = (Math.random() - 0.5) * 70;
                starPositions[i*3+2] = (Math.random() - 0.5) * 60 - 30;
                starVelocities.push({ x: (Math.random() - 0.5) * 0.07, y: (Math.random() - 0.5) * 0.1 - 0.04, z: (Math.random() - 0.5) * 0.03 });
            }
            const starGeometry = new THREE.BufferGeometry();
            starGeometry.setAttribute('position', new THREE.BufferAttribute(starPositions, 3));
            const starMaterial = new THREE.PointsMaterial({ size: 0.09, color: 0xffaa88, transparent: true, opacity: 0.6, blending: THREE.AdditiveBlending });
            const stars = new THREE.Points(starGeometry, starMaterial);
            scene.add(stars);

            scene.fog = new THREE.FogExp2(0x08061a, 0.008);

            let mouseX = 0, mouseY = 0, targetX = 0, targetY = 0;
            const halfX = window.innerWidth / 2, halfY = window.innerHeight / 2;
            document.addEventListener('mousemove', (e) => {
                mouseX = (e.clientX - halfX) * 0.0005;
                mouseY = (e.clientY - halfY) * 0.0005;
            });

            const clock = new THREE.Clock();
            function animate() {
                requestAnimationFrame(animate);
                const t = clock.getElapsedTime();
                material.color.setHSL((t * 0.02) % 0.1 + 0.9, 0.8, 0.6);
                particles.rotation.y = t * 0.03;
                particles.rotation.x = t * 0.01;
                targetX = mouseX * 0.5;
                targetY = mouseY * 0.5;
                particles.rotation.y += 0.5 * (targetX - particles.rotation.y);
                particles.rotation.x += 0.5 * (targetY - particles.rotation.x);

                const posArr = stars.geometry.attributes.position.array;
                for (let i = 0; i < starCount; i++) {
                    posArr[i*3] += starVelocities[i].x;
                    posArr[i*3+1] += starVelocities[i].y;
                    posArr[i*3+2] += starVelocities[i].z;
                    if (Math.abs(posArr[i*3]) > 70 || Math.abs(posArr[i*3+1]) > 45) {
                        posArr[i*3] = (Math.random() - 0.5) * 120;
                        posArr[i*3+1] = 40;
                        posArr[i*3+2] = (Math.random() - 0.5) * 50 - 25;
                    }
                }
                stars.geometry.attributes.position.needsUpdate = true;
                renderer.render(scene, camera);
            }
            animate();
            window.addEventListener('resize', () => {
                camera.aspect = window.innerWidth / window.innerHeight;
                camera.updateProjectionMatrix();
                renderer.setSize(window.innerWidth, window.innerHeight);
            });
        })();
    