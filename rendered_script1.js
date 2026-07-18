
            // ========== THREE.JS NÂNG CẤP (MƯA SAO BĂNG, FOG, PARTICLES MÀU) ==========
            (function initEnhancedThree() {
                const canvas = document.getElementById('bg-canvas');
                if (!canvas) return;
                const scene = new THREE.Scene();
                const camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);
                camera.position.z = 30;
                const renderer = new THREE.WebGLRenderer({ canvas: canvas, alpha: true, antialias: true });
                renderer.setSize(window.innerWidth, window.innerHeight);
                renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

                // 1. Particle chính
                const isMobile = window.innerWidth < 768;
                const particlesCount = isMobile ? 500 : 1000;
                const particlesGeometry = new THREE.BufferGeometry();
                const posArray = new Float32Array(particlesCount * 3);
                for (let i = 0; i < particlesCount * 3; i++) { posArray[i] = (Math.random() - 0.5) * 120; }
                particlesGeometry.setAttribute('position', new THREE.BufferAttribute(posArray, 3));
                const material = new THREE.PointsMaterial({ size: isMobile ? 0.12 : 0.18, color: 0x06b6d4, transparent: true, opacity: 0.6, blending: THREE.AdditiveBlending });
                const particlesMesh = new THREE.Points(particlesGeometry, material);
                scene.add(particlesMesh);

                // 2. Stars
                const starCount = 60;
                const starPositions = new Float32Array(starCount * 3);
                const starVelocities = [];
                for (let i = 0; i < starCount; i++) {
                    starPositions[i * 3] = (Math.random() - 0.5) * 120;
                    starPositions[i * 3 + 1] = (Math.random() - 0.5) * 70;
                    starPositions[i * 3 + 2] = (Math.random() - 0.5) * 60 - 30;
                    starVelocities.push({ x: (Math.random() - 0.5) * 0.02, y: (Math.random() - 0.5) * 0.04 - 0.02, z: (Math.random() - 0.5) * 0.01 });
                }
                const starGeometry = new THREE.BufferGeometry();
                starGeometry.setAttribute('position', new THREE.BufferAttribute(starPositions, 3));
                const starMaterial = new THREE.PointsMaterial({ size: 0.08, color: 0x8b5cf6, transparent: true, opacity: 0.55, blending: THREE.AdditiveBlending });
                const starsMesh = new THREE.Points(starGeometry, starMaterial);
                scene.add(starsMesh);

                scene.fog = new THREE.FogExp2(0x05030f, 0.015);

                let mouseX = 0, mouseY = 0, targetX = 0, targetY = 0;
                const windowHalfX = window.innerWidth / 2;
                const windowHalfY = window.innerHeight / 2;
                document.addEventListener('mousemove', (event) => {
                    mouseX = (event.clientX - windowHalfX) * 0.0004;
                    mouseY = (event.clientY - windowHalfY) * 0.0004;
                });

                const clock = new THREE.Clock();
                function animate() {
                    requestAnimationFrame(animate);
                    if (document.hidden) return; // GPU/CPU throttle when hidden
                    const elapsedTime = clock.getElapsedTime();
                    const hue = (elapsedTime * 0.035) % 1;
                    material.color.setHSL(hue, 0.8, 0.6);

                    particlesMesh.rotation.y = elapsedTime * 0.015;
                    particlesMesh.rotation.x = elapsedTime * 0.008;
                    targetX = mouseX * 0.4;
                    targetY = mouseY * 0.4;
                    particlesMesh.rotation.y += 0.5 * (targetX - particlesMesh.rotation.y);
                    particlesMesh.rotation.x += 0.5 * (targetY - particlesMesh.rotation.x);

                    const positions = starsMesh.geometry.attributes.position.array;
                    for (let i = 0; i < starCount; i++) {
                        positions[i * 3] += starVelocities[i].x;
                        positions[i * 3 + 1] += starVelocities[i].y;
                        positions[i * 3 + 2] += starVelocities[i].z;
                        if (Math.abs(positions[i * 3]) > 65 || Math.abs(positions[i * 3 + 1]) > 40) {
                            positions[i * 3] = (Math.random() - 0.5) * 120;
                            positions[i * 3 + 1] = 35;
                            positions[i * 3 + 2] = (Math.random() - 0.5) * 40 - 20;
                        }
                    }
                    starsMesh.geometry.attributes.position.needsUpdate = true;

                    renderer.render(scene, camera);
                }
                animate();

                window.addEventListener('resize', () => {
                    camera.aspect = window.innerWidth / window.innerHeight;
                    camera.updateProjectionMatrix();
                    renderer.setSize(window.innerWidth, window.innerHeight);
                });
            })();

            // ========== 3D HOLOGRAM ROTATING CORE ENGINE IN SHOWCASE (NEW!) ==========
            (function init3DHologramCore() {
                const canvas = document.getElementById('hologram-canvas');
                if (!canvas) return;
                const scene = new THREE.Scene();
                const camera = new THREE.PerspectiveCamera(45, canvas.clientWidth / canvas.clientHeight, 0.1, 100);
                camera.position.z = 8;

                const renderer = new THREE.WebGLRenderer({ canvas: canvas, alpha: true, antialias: true });
                renderer.setSize(canvas.clientWidth, canvas.clientHeight);
                renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

                // Wireframe wire globe
                const geometry = new THREE.IcosahedronGeometry(2.5, 2);
                const material = new THREE.MeshBasicMaterial({
                    color: 0x06b6d4,
                    wireframe: true,
                    transparent: true,
                    opacity: 0.35,
                    blending: THREE.AdditiveBlending
                });
                const hologramMesh = new THREE.Mesh(geometry, material);
                scene.add(hologramMesh);

                // Glowing core particle inside
                const coreGeometry = new THREE.IcosahedronGeometry(1.2, 1);
                const coreMaterial = new THREE.MeshBasicMaterial({
                    color: 0x8b5cf6,
                    wireframe: true,
                    transparent: true,
                    opacity: 0.65,
                    blending: THREE.AdditiveBlending
                });
                const coreMesh = new THREE.Mesh(coreGeometry, coreMaterial);
                scene.add(coreMesh);

                // Floating vertex points
                const pointsGeometry = new THREE.IcosahedronGeometry(2.5, 2);
                const pointsMaterial = new THREE.PointsMaterial({
                    size: 0.08,
                    color: 0xffffff,
                    transparent: true,
                    opacity: 0.8
                });
                const vertexPoints = new THREE.Points(pointsGeometry, pointsMaterial);
                scene.add(vertexPoints);

                const clock = new THREE.Clock();
                function animateHologram() {
                    requestAnimationFrame(animateHologram);
                    if (document.hidden) return; // Throttling
                    const time = clock.getElapsedTime();

                    hologramMesh.rotation.y = time * 0.15;
                    hologramMesh.rotation.x = time * 0.08;

                    coreMesh.rotation.y = -time * 0.25;
                    coreMesh.rotation.z = time * 0.12;

                    vertexPoints.rotation.y = time * 0.15;
                    vertexPoints.rotation.x = time * 0.08;

                    // Pulsing size animation
                    const pulse = 1 + Math.sin(time * 2) * 0.08;
                    hologramMesh.scale.set(pulse, pulse, pulse);
                    vertexPoints.scale.set(pulse, pulse, pulse);

                    renderer.render(scene, camera);
                }
                animateHologram();

                window.addEventListener('resize', () => {
                    const width = canvas.clientWidth;
                    const height = canvas.clientHeight;
                    camera.aspect = width / height;
                    camera.updateProjectionMatrix();
                    renderer.setSize(width, height);
                });
            })();

            // ========== REALTIME AI DIALOGUE TYPEWRITER SIMULATION (NEW!) ==========
            (function initAISimulation() {
                const chatBox = document.getElementById('simulationChatBox');
                if (!chatBox) return;

                const dialogs = [
                    { sender: 'Khách hàng', text: 'Chào shop, tư vấn gói làm Nails & chăm sóc da mụn chiều nay.' },
                    { sender: 'BitPaw AI', text: 'Dạ chào chị! Trợ lý BitPaw AI xin gợi ý gói chăm sóc da thải độc thải chì cùng combo làm móng đắp bột hoa hồng Pháp. Chị muốn chọn làm lúc 15:30 chiều nay nhé?' },
                    { sender: 'Khách hàng', text: 'Ok đặt lịch giúp mình, số điện thoại mình là 090xxxxxxx' },
                    { sender: 'BitPaw AI', text: 'Tuyệt vời! BitPaw AI đã tự động đăng ký thông tin của chị vào hệ thống CRM. Thông báo lịch hẹn đã gửi trực tiếp tới Zalo của chị. Hẹn gặp chị chiều nay nhé! ✨' }
                ];

                let dialogIndex = 0;

                function showNextMessage() {
                    if (dialogIndex >= dialogs.length) {
                        dialogIndex = 0;
                        chatBox.innerHTML = '';
                    }

                    const msg = dialogs[dialogIndex];
                    const msgEl = document.createElement('div');
                    msgEl.className = `p-2 rounded-xl text-xs transition-all duration-300 transform translate-y-2 opacity-0 ${msg.sender === 'Khách hàng'
                        ? 'bg-white/5 text-gray-300 ml-4 border-l-2 border-gray-400'
                        : 'bg-cyan-500/10 text-cyan-300 mr-4 border-l-2 border-cyan-400'
                        }`;

                    msgEl.innerHTML = `<span class="font-bold block uppercase text-[9px] mb-0.5 text-gray-400">${msg.sender}</span> <span class="typewriter-text"></span>`;
                    chatBox.appendChild(msgEl);

                    // Typewriter effect
                    let textIndex = 0;
                    const textSpan = msgEl.querySelector('.typewriter-text');

                    function typeText() {
                        if (textIndex < msg.text.length) {
                            textSpan.textContent += msg.text.charAt(textIndex);
                            textIndex++;
                            setTimeout(typeText, 35);
                        } else {
                            // Done typing this message, transition in
                            msgEl.classList.remove('translate-y-2', 'opacity-0');
                            dialogIndex++;
                            // Delay before the next dialogue message starts typing
                            setTimeout(showNextMessage, 3200);
                        }
                    }
                    typeText();
                }

                // Start dialogue loop
                setTimeout(() => {
                    chatBox.innerHTML = '';
                    showNextMessage();
                }, 1000);
            })();

            // ========== SUPABASE DATABASE REGISTRY CONNECT ==========
            const supabaseUrl = 'https://iojtglaxgdwsxxalhubx.supabase.co';
            const supabaseKey = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImlvanRnbGF4Z2R3c3h4YWxodWJ4Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzc1NjgzNTIsImV4cCI6MjA5MzE0NDM1Mn0.KA7wdsZsK3oA6ybi5Gl_KnkzAKZM-ESI3Eyzx-mipwM';
            const supabase = window.supabase.createClient(supabaseUrl, supabaseKey);

            async function fetchDashboardData() {
                try {
                    const { data: activities, error: actErr } = await supabase
                        .from('user_logs')
                        .select('action, description, created_at')
                        .order('created_at', { ascending: false })
                        .limit(5);

                    let activityHtml = `<div class="text-center text-gray-500 py-2">${currentLang === 'en' ? 'No activity yet' : 'Chưa có hoạt động nào'}</div>`;
                    if (!actErr && activities && activities.length) {
                        activityHtml = activities.map(act => {
                            const time = new Date(act.created_at).toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' });
                            let icon = 'fas fa-info-circle text-cyan-400';
                            if (act.action.includes('checkout') || act.action.includes('payment')) icon = 'fas fa-wallet text-emerald-400';
                            else if (act.action.includes('call_staff')) icon = 'fas fa-bell text-rose-400 animate-pulse';
                            else if (act.action.includes('login') || act.action.includes('register')) icon = 'fas fa-fingerprint text-purple-400';

                            return `<div class="flex items-center gap-3 text-gray-400 py-1.5 border-b border-white/5">
                                    <i class="${icon} w-4 text-center"></i>
                                    <span class="truncate flex-1">${time} - ${act.description}</span>
                                </div>`;
                        }).join('');
                    }

                    if (document.getElementById('launcherActivityList')) document.getElementById('launcherActivityList').innerHTML = activityHtml;
                } catch (err) {
                    console.error("Lỗi fetch log:", err);
                    const errHtml = `<div class="text-center text-rose-400 py-2">${currentLang === 'en' ? 'Unable to connect to the Cloud server' : 'Không thể kết nối máy chủ Cloud'}</div>`;
                    if (document.getElementById('launcherActivityList')) document.getElementById('launcherActivityList').innerHTML = errHtml;
                }
            }

            function updateClock() {
                const now = new Date();
                const clockStr = String(now.getHours()).padStart(2, '0') + ':' +
                    String(now.getMinutes()).padStart(2, '0') + ':' +
                    String(now.getSeconds()).padStart(2, '0');
                if (document.getElementById('realtimeClock')) document.getElementById('realtimeClock').innerText = clockStr;
                if (document.getElementById('launcherClock')) document.getElementById('launcherClock').innerText = clockStr;
            }
            setInterval(updateClock, 1000);
            updateClock();

            function showMessage(msg, isError = false) {
                const toast = document.getElementById('toast');
                if (!toast) return;
                toast.textContent = msg;
                toast.style.borderColor = isError ? '#ef4444' : '#06b6d4';
                toast.classList.add('show');
                setTimeout(() => { toast.classList.remove('show'); }, 3000);
            }

            function openFastCheckin() {
                document.getElementById('fastCheckinModal').classList.remove('hidden');
                document.getElementById('fastCheckinModal').classList.add('flex');
                document.getElementById('fc_empCode').focus();
            }
            function closeFastCheckin() {
                document.getElementById('fastCheckinModal').classList.add('hidden');
                document.getElementById('fastCheckinModal').classList.remove('flex');
                document.getElementById('fc_empCode').value = '';
            }

            async function proceedToCamera() {
                const code = document.getElementById('fc_empCode').value.trim().toUpperCase();
                if (!code) return showMessage(currentLang === 'en' ? "Please enter your Employee Code!" : "Vui lòng nhập Mã Nhân Viên!", true);
                const btn = document.getElementById('btnProceedCheckin');
                const originalText = btn.innerHTML;
                btn.innerHTML = `<i class="fas fa-spinner fa-spin"></i> ${currentLang === 'en' ? 'CONNECTING...' : 'KẾT NỐI...'}`; btn.disabled = true;
                try {
                    const { data, error } = await supabase.from('employees').select('ho_ten').eq('ma_nv', code).maybeSingle();
                    if (error) throw error;
                    if (!data) {
                        showMessage((currentLang === 'en' ? "No employee found with code: " : "Không tìm thấy Nhân viên mang mã: ") + code, true);
                        btn.innerHTML = originalText; btn.disabled = false;
                        return;
                    }
                    sessionStorage.setItem('bp_emp_code', code);
                    sessionStorage.setItem('bp_emp_name', data.ho_ten);
                    window.location.href = 'diemdanh.html';
                } catch (err) {
                    showMessage(currentLang === 'en' ? "Server connection error!" : "Lỗi kết nối máy chủ!", true);
                    btn.innerHTML = originalText; btn.disabled = false;
                }
            }

            const i18n = {
                vi: {
                    welcome: "Cổng Kích Hoạt Hệ Thống", subwelcome: "Đăng nhập tài khoản quản trị để vận hành Doanh nghiệp.",
                    login_email: "Email đăng nhập", login_pass: "Mật khẩu", forgot: "Quên mật khẩu?", btn_login: "ĐĂNG NHẬP VẬN HÀNH",
                    newbiz: "Chưa có bản quyền?", createnow: "Khởi tạo ngay",
                    reg_name: "Họ và tên Sếp (Tên đăng nhập)", reg_email: "Email quản trị",
                    license_label: "<i class='fas fa-key mr-1'></i> Nhập License Key Bản Quyền",
                    reg_pass: "Mật khẩu (tối thiểu 6 ký tự)", reg_confirm: "Xác nhận mật khẩu",
                    btn_reg: "KHỞI TẠO BITPAW OS", have_account: "Đã có tài khoản?", login_now: "Đăng nhập",
                    reset_title: "Khôi Phục Mật Khẩu", reset_desc: "Nhập Email, hệ thống sẽ gửi liên kết đổi mật khẩu."
                },
                en: {
                    welcome: "System Activation Hub", subwelcome: "Log in with your administrator account to run your enterprise.",
                    login_email: "Login Email", login_pass: "Password", forgot: "Forgot password?", btn_login: "LOG IN TO OPERATE",
                    newbiz: "No active license?", createnow: "Initialize Now",
                    reg_name: "Full Name (Username)", reg_email: "Admin Email",
                    license_label: "<i class='fas fa-key mr-1'></i> Enter Software License Key",
                    reg_pass: "Password (min 6 characters)", reg_confirm: "Confirm Password",
                    btn_reg: "INITIALIZE BITPAW OS", have_account: "Already have an account?", login_now: "Login",
                    reset_title: "Reset Password", reset_desc: "Enter your Email to receive a password reset link."
                },
                zh: {
                    welcome: "系统激活中心", subwelcome: "登录您的管理员账户以运营您的企业。",
                    login_email: "登录邮箱", login_pass: "密码", forgot: "忘记密码？", btn_login: "登录系统以运行",
                    newbiz: "没有激活的许可证？", createnow: "立即初始化",
                    reg_name: "全名（用户名）", reg_email: "管理员邮箱",
                    license_label: "<i class='fas fa-key mr-1'></i> 输入软件激活码",
                    reg_pass: "密码（最少6个字符）", reg_confirm: "确认密码",
                    btn_reg: "初始化 BITPAW OS", have_account: "已有账号？", login_now: "登录",
                    reset_title: "重置密码", reset_desc: "输入您的邮箱以获取密码重置链接。"
                }
            };

            // Generic data-i18n / data-i18n-placeholder dictionary for elements not covered
            // by the legacy id-based `i18n` map above (dashboard launcher, modals, telemetry).
            const dataI18n = {
                index_business_label: { vi: 'Doanh nghiệp:', en: 'Business:' },
                index_uptime_label: { vi: 'Thời gian vận hành', en: 'Operating Uptime' },
                index_license_active: { vi: 'License: Hoạt động', en: 'License: Active' },
                index_logout_btn: { vi: 'Đăng xuất', en: 'Logout' },
                index_operating_info_title: { vi: 'Thông Tin Vận Hành', en: 'Operating Information' },
                index_industry_zone_label: { vi: 'Môi trường phân vùng / Industry:', en: 'Industry Zone:' },
                index_industry_fnb: { vi: 'Nhà hàng & Cafe (F&B)', en: 'Restaurant & Cafe (F&B)' },
                index_industry_nail: { vi: 'Nails & Salon', en: 'Nails & Salon' },
                index_industry_spa: { vi: 'Spa & Wellness', en: 'Spa & Wellness' },
                index_industry_retail: { vi: 'Bán lẻ & ERP (Retail)', en: 'Retail & ERP' },
                index_industry_active_prefix: { vi: 'Ngành đang hoạt động:', en: 'Industry Active:' },
                index_ai_core_status_title: { vi: 'Trạng Thái BitPaw AI Core', en: 'BitPaw AI Core Status' },
                index_ai_status_label: { vi: 'Trạng thái AI:', en: 'AI Status:' },
                index_ai_status_online: { vi: 'Online', en: 'Online' },
                index_chats_today_label: { vi: 'Chats hôm nay:', en: 'Chats today:' },
                index_leads_captured_label: { vi: 'Lead thu về:', en: 'Leads captured:' },
                index_attendance_title: { vi: 'Chấm Công Nhân Sự', en: 'Staff Attendance' },
                index_secondary_badge: { vi: 'Secondary', en: 'Secondary' },
                index_attendance_desc: { vi: 'Mở bảng chấm công và xác thực check-in nhanh cho nhân viên khi vào ca.', en: 'Open the attendance board and quickly verify staff check-ins at shift start.' },
                index_checkin_shift_btn: { vi: 'Checkin ca', en: 'Check in' },
                index_attendance_board_btn: { vi: 'Bảng biểu', en: 'Board' },
                index_activity_log_title: { vi: 'Nhật Ký Vận Hành', en: 'Operation Log' },
                index_connecting_data: { vi: 'Đang kết nối dữ liệu...', en: 'Connecting to data...' },
                index_card_pos_badge: { vi: 'Mở POS Screen', en: 'Open POS Screen' },
                index_card_pos_title: { vi: 'Hệ Thống Bán Hàng & POS', en: 'Sales & POS System' },
                index_card_pos_desc: { vi: 'Mở quầy gọi món tại chỗ, xếp lịch Nails/Spa, treo bill, in hóa đơn nhiệt và thanh toán trực tiếp cho khách hàng.', en: 'Open dine-in ordering, schedule Nails/Spa appointments, hold open tabs, print thermal receipts, and take payments directly from customers.' },
                index_card_ai_badge: { vi: 'AI Copilot', en: 'AI Copilot' },
                index_card_ai_title: { vi: 'BitPaw AI Copilot Core', en: 'BitPaw AI Copilot Core' },
                index_card_ai_desc: { vi: 'Kích hoạt trợ lý chatbot AI đàm thoại bán hàng 24/7, bám đuổi tư vấn tự động, thu thập leads chốt đơn đa nền tảng.', en: 'Activate a 24/7 conversational AI sales chatbot that follows up automatically and captures leads across multiple platforms.' },
                index_card_qr_badge: { vi: 'QR Menu View', en: 'QR Menu View' },
                index_card_qr_title: { vi: 'Thực Đơn QR Động & Đặt Lịch', en: 'Dynamic QR Menu & Booking' },
                index_card_qr_desc: { vi: 'Mã QR đặt món và thanh toán tại bàn (F&B), hoặc tự chọn ghế Nails/ Spa booking trực tuyến cực kỳ sang xịn.', en: 'QR code ordering and table-side payment for F&B, or self-service seat selection for premium online Nails/Spa booking.' },
                index_card_crm_badge: { vi: 'Dashboard', en: 'Dashboard' },
                index_card_crm_title: { vi: 'Môi Trường Doanh Nghiệp (CRM)', en: 'Business Environment (CRM)' },
                index_card_crm_desc: { vi: 'Theo dõi chi tiết dữ liệu khách hàng CRM, tỷ lệ quay lại, quản lý tồn kho sản phẩm, phân cấp phân quyền bảo mật.', en: 'Track detailed CRM customer data and return rates, manage product inventory, and set tiered security permissions.' },
                index_card_inbox_badge: { vi: 'Hộp Thư AI', en: 'AI Inbox' },
                index_card_inbox_title: { vi: 'Inbox Đa Kênh Omnichannel', en: 'Omnichannel Inbox' },
                index_card_inbox_desc: { vi: 'Kết nối tin nhắn đa kênh (Messenger, Zalo OA, Web Form) đổ dồn về một hộp thư thông minh tập trung quản trị.', en: 'Connect messages from multiple channels (Messenger, Zalo OA, Web Form) into one smart, centrally managed inbox.' },
                index_card_campaign_badge: { vi: 'Gửi Chiến Dịch', en: 'Send Campaign' },
                index_card_campaign_title: { vi: 'Chiến Dịch & Trình Gửi Tin', en: 'Campaigns & Messaging' },
                index_card_campaign_desc: { vi: 'Lên lịch kịch bản tự động chăm sóc sau mua, chúc mừng sinh nhật, gửi mã coupon ưu đãi tái kích hoạt tệp khách cũ.', en: 'Schedule automated post-purchase care, birthday greetings, and coupon codes to re-engage past customers.' },
                index_card_payment_badge: { vi: 'Cấu Hình Pay', en: 'Payment Setup' },
                index_card_payment_title: { vi: 'Cổng Nhận Tiền & Fintech', en: 'Payment Gateway & Fintech' },
                index_card_payment_desc: { vi: 'Cấu hình VietQR động chuyển tiền trực tiếp về tài khoản, Stripe thanh toán thẻ quốc tế, ví MoMo, ZaloPay nhận tiền.', en: 'Configure dynamic VietQR for direct bank transfers, Stripe for international card payments, and MoMo/ZaloPay wallets.' },
                index_card_report_badge: { vi: 'Xem Báo Cáo', en: 'View Report' },
                index_card_report_title: { vi: 'Doanh Thu & Dòng Tiền', en: 'Revenue & Cash Flow' },
                index_card_report_desc: { vi: 'Tra cứu doanh số, lợi nhuận thực tế, chi phí đầu vào, thống kê dòng tiền chênh lệch theo thời gian thực.', en: 'Look up sales, actual profit, input costs, and real-time cash flow variance statistics.' },
                index_reg_industry_label: { vi: 'Chọn Ngành Nghề', en: 'Select Industry' },
                index_telemetry_secure_session: { vi: 'Secure Session', en: 'Secure Session' },
                index_telemetry_multitenant: { vi: 'Multi-tenant OS', en: 'Multi-tenant OS' },
                index_telemetry_cloud_sync: { vi: 'Cloud Sync Ready', en: 'Cloud Sync Ready' },
                index_secure_online_badge: { vi: 'Secure / Online', en: 'Secure / Online' },
                index_live_ecosystem_map: { vi: 'Live Ecosystem Map', en: 'Live Ecosystem Map' },
                index_fastcheckin_title: { vi: 'Xác Thực Nhân Sự', en: 'Staff Verification' },
                index_fastcheckin_desc: { vi: 'Nhập Mã NV để checkin điểm danh ca làm.', en: 'Enter your Employee Code to check in for your shift.' },
                index_fastcheckin_continue_btn: { vi: 'TIẾP TỤC', en: 'CONTINUE' },
                index_forgot_cancel_btn: { vi: 'Hủy', en: 'Cancel' },
                index_forgot_send_btn: { vi: 'Gửi Link Reset', en: 'Send Reset Link' }
            };
            const dataI18nPlaceholder = {
                index_fastcheckin_placeholder: { vi: 'VD: NV001', en: 'e.g. NV001' },
                index_reset_email_placeholder: { vi: 'Nhập Email của bạn', en: 'Enter your email' },
                index_reg_license_placeholder: { vi: 'VD: BITPAW-TR8D8T5S', en: 'e.g. BITPAW-TR8D8T5S' }
            };
            function applyDataI18n(lang) {
                const useLang = (lang === 'en') ? 'en' : 'vi';
                document.querySelectorAll('[data-i18n]').forEach(el => {
                    const entry = dataI18n[el.getAttribute('data-i18n')];
                    if (entry && entry[useLang]) el.textContent = entry[useLang];
                });
                document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
                    const entry = dataI18nPlaceholder[el.getAttribute('data-i18n-placeholder')];
                    if (entry && entry[useLang]) el.placeholder = entry[useLang];
                });
            }

            let currentLang = 'vi';
            function setLang(lang) {
                const t = i18n[lang];
                currentLang = lang;
                applyDataI18n(lang);
                if (!t) return;

                const wTxt = document.getElementById('txt_welcome');
                if (wTxt) wTxt.textContent = t.welcome;

                const swTxt = document.getElementById('txt_subwelcome');
                if (swTxt) swTxt.textContent = t.subwelcome;

                const fgBtn = document.getElementById('btn_forgot');
                if (fgBtn) fgBtn.textContent = t.forgot;

                const loginBtn = document.getElementById('btnLogin');
                if (loginBtn) loginBtn.textContent = t.btn_login;

                const nbTxt = document.getElementById('txt_newbiz');
                if (nbTxt) nbTxt.textContent = t.newbiz;

                const cnTxt = document.getElementById('txt_createnow');
                if (cnTxt) cnTxt.textContent = t.createnow;

                const licLbl = document.getElementById('txt_license_label');
                if (licLbl) licLbl.innerHTML = t.license_label;

                const regBtn = document.getElementById('btnRegister');
                if (regBtn) regBtn.textContent = t.btn_reg;

                const haTxt = document.getElementById('txt_have_account');
                if (haTxt) haTxt.textContent = t.have_account;

                const lnTxt = document.getElementById('txt_login_now');
                if (lnTxt) lnTxt.textContent = t.login_now;

                const rstTtl = document.getElementById('txt_reset_title');
                if (rstTtl) rstTtl.textContent = t.reset_title;

                const rstDsc = document.getElementById('txt_reset_desc');
                if (rstDsc) rstDsc.textContent = t.reset_desc;

                const lEmail = document.getElementById('loginEmail');
                if (lEmail) lEmail.placeholder = t.login_email;

                const lPass = document.getElementById('loginPassword');
                if (lPass) lPass.placeholder = t.login_pass;

                const rName = document.getElementById('regFullname');
                if (rName) rName.placeholder = t.reg_name;

                const rEmail = document.getElementById('regEmail');
                if (rEmail) rEmail.placeholder = t.reg_email;

                const rPass = document.getElementById('regPassword');
                if (rPass) rPass.placeholder = t.reg_pass;

                const rConf = document.getElementById('regConfirm');
                if (rConf) rConf.placeholder = t.reg_confirm;

                localStorage.setItem('bitpaw_lang', lang);
            }
            const savedLang = localStorage.getItem('bitpaw_lang') || "vi";
            setLang(savedLang);

            const loginPanel = document.getElementById('loginForm');
            const registerPanel = document.getElementById('registerForm');
            function setActiveTab(tab) {
                if (!loginPanel || !registerPanel) return;
                if (tab === 'login') { registerPanel.classList.remove('active'); loginPanel.classList.add('active'); }
                else { loginPanel.classList.remove('active'); registerPanel.classList.add('active'); }
            }

            const initialTab = "login";
            setActiveTab(initialTab);

            function toggleLoading(btnId, isLoading, originalText) {
                const btn = document.getElementById(btnId);
                if (!btn) return;
                if (isLoading) { btn.disabled = true; btn.innerHTML = `<i class="fas fa-spinner fa-spin mr-2"></i> ${currentLang === 'en' ? 'Processing...' : 'Đang xử lý...'}`; btn.classList.add('opacity-70'); }
                else { btn.disabled = false; btn.innerHTML = originalText; btn.classList.remove('opacity-70'); }
            }

            const regForm = document.getElementById('registerFormElement');
            if (regForm) {
                regForm.addEventListener('submit', (e) => {
                    const password = document.getElementById('regPassword').value;
                    const confirm = document.getElementById('regConfirm').value;
                    if (password !== confirm) {
                        e.preventDefault();
                        showMessage(currentLang === 'en' ? "❌ Password confirmation does not match!" : "❌ Mật khẩu xác nhận không khớp!", true);
                        return false;
                    }
                    const strongRegex = /^(?=.*[A-Z])(?=.*\d).{6,}$/;
                    if (!strongRegex.test(password)) {
                        e.preventDefault();
                        showMessage(currentLang === 'en' ? "❌ Password must have at least 6 characters, 1 uppercase letter and 1 number!" : "❌ Mật khẩu phải có ít nhất 6 ký tự, 1 chữ hoa và 1 số!", true);
                        return false;
                    }
                    const originalText = document.getElementById('btnRegister').textContent;
                    toggleLoading('btnRegister', true, originalText);
                });
            }

            const loginFormEl = document.getElementById('loginFormElement');
            if (loginFormEl) {
                loginFormEl.addEventListener('submit', (e) => {
                    const originalText = document.getElementById('btnLogin').textContent;
                    toggleLoading('btnLogin', true, originalText);
                });
            }

            function forgotPassword() {
                document.getElementById('forgotPasswordModal').classList.replace('hidden', 'flex');
                const lEmail = document.getElementById('loginEmail');
                if (lEmail) document.getElementById('resetEmail').value = lEmail.value;
            }
            function closeForgotModal() { document.getElementById('forgotPasswordModal').classList.replace('flex', 'hidden'); }
            async function sendResetPassword() {
                const email = document.getElementById('resetEmail').value.trim();
                if (!email) return showMessage(currentLang === 'en' ? "Please enter your Email!" : "Vui lòng nhập Email!", true);
                const btn = document.getElementById('btnReset');
                btn.innerHTML = `<i class="fas fa-spinner fa-spin"></i> ${currentLang === 'en' ? 'Sending...' : 'Đang gửi...'}`; btn.disabled = true;
                try {
                    const { error } = await supabase.auth.resetPasswordForEmail(email, { redirectTo: window.location.origin + '/reset-password.html' });
                    if (error) throw error;
                    showMessage(currentLang === 'en' ? "✅ Recovery link sent to your Email." : "✅ Đã gửi link khôi phục vào Email.", false);
                    closeForgotModal();
                } catch (e) { showMessage((currentLang === 'en' ? "❌ Error: " : "❌ Lỗi: ") + e.message, true); }
                btn.innerHTML = currentLang === 'en' ? 'Send Reset Link' : 'Gửi Link Reset'; btn.disabled = false;
            }

            fetchDashboardData();
        