
        // ========================================================
        // 3D THREE.JS PARTICLE BACKGROUND (BLUE ACCENTS)
        // ========================================================
        (function initThreeJS() {
            if (typeof THREE === 'undefined') return;
            
            const canvas = document.getElementById('bg-canvas');
            if (!canvas) return;

            const scene = new THREE.Scene();
            const camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);
            camera.position.z = 30;

            const renderer = new THREE.WebGLRenderer({ canvas: canvas, alpha: true, antialias: true });
            renderer.setSize(window.innerWidth, window.innerHeight);
            renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

            const particlesGeometry = new THREE.BufferGeometry();
            const isMobile = window.innerWidth < 768;
            const particlesCount = isMobile ? 350 : 1200;
            const posArray = new Float32Array(particlesCount * 3);

            for (let i = 0; i < particlesCount * 3; i++) {
                posArray[i] = (Math.random() - 0.5) * 110;
            }
            particlesGeometry.setAttribute('position', new THREE.BufferAttribute(posArray, 3));

            const material = new THREE.PointsMaterial({
                size: isMobile ? 0.18 : 0.16,
                color: 0x3b82f6, // Blue Accent
                transparent: true,
                opacity: 0.75,
                blending: THREE.AdditiveBlending
            });
            const particlesMesh = new THREE.Points(particlesGeometry, material);
            scene.add(particlesMesh);

            let mouseX = 0, mouseY = 0;
            if (!isMobile) {
                document.addEventListener('mousemove', (e) => {
                    mouseX = (e.clientX - window.innerWidth/2) * 0.0005;
                    mouseY = (e.clientY - window.innerHeight/2) * 0.0005;
                });
            }

            const clock = new THREE.Clock();
            function animate() {
                requestAnimationFrame(animate);
                const elapsed = clock.getElapsedTime();
                particlesMesh.rotation.y = elapsed * 0.04;
                particlesMesh.rotation.x = elapsed * 0.015;
                
                if (!isMobile) {
                    particlesMesh.rotation.y += 0.5 * (mouseX * 0.5 - particlesMesh.rotation.y);
                    particlesMesh.rotation.x += 0.5 * (mouseY * 0.5 - particlesMesh.rotation.x);
                }
                
                renderer.render(scene, camera);
            }
            animate();

            window.addEventListener('resize', () => {
                camera.aspect = window.innerWidth / window.innerHeight;
                camera.updateProjectionMatrix();
                renderer.setSize(window.innerWidth, window.innerHeight);
            });
        })();

        // Khởi tạo AOS & Vanilla Tilt
        document.addEventListener('DOMContentLoaded', () => {
            if (typeof AOS !== 'undefined') {
                AOS.init({ once: true, offset: 50, duration: 800 });
            }

            // FAQ Accordion
            const faqItems = document.querySelectorAll('.faq-item');
            faqItems.forEach(item => {
                const header = item.querySelector('.faq-header');
                if (header) {
                    header.addEventListener('click', () => {
                        const isActive = item.classList.contains('active');
                        faqItems.forEach(el => el.classList.remove('active'));
                        if (!isActive) {
                            item.classList.add('active');
                        }
                    });
                }
            });

            // Interactive Hotel Calculator
            const selectService = document.getElementById('quick_service');
            const inputTotal = document.getElementById('calc_total');
            const inputDays = document.getElementById('calc_days');
            const inputSupply = document.getElementById('calc_supply');
            const inputCheckoutLate = document.getElementById('calc_checkout_late');
            const inputPrepaid = document.getElementById('calc_prepaid');
            const inputDiscount = document.getElementById('calc_discount');
            
            const rSubtotal = document.getElementById('rc_subtotal');
            const rDiscountRate = document.getElementById('rc_discount_rate');
            const rDiscountVal = document.getElementById('rc_discount_val');
            const rSupplyVal = document.getElementById('rc_supply_val');
            const rCheckoutLateVal = document.getElementById('rc_checkout_late_val');
            const rPrepaidVal = document.getElementById('rc_prepaid_val');
            const rTotalBill = document.getElementById('rc_total_bill');

            const roomConfig = {
                room_vip: { total: 1200000, days: 2, supply: 150000, checkout_late: 100000, prepaid: 500000, discount: 10 },
                room_deluxe: { total: 800000, days: 2, supply: 80000, checkout_late: 0, prepaid: 300000, discount: 5 },
                room_standard: { total: 500000, days: 1, supply: 40000, checkout_late: 0, prepaid: 200000, discount: 0 }
            };

            function calculateRealtime() {
                if (!inputTotal || !inputDays || !inputSupply || !inputCheckoutLate || !inputPrepaid || !inputDiscount) return;
                
                const roomPrice = Math.max(0, parseFloat(inputTotal.value) || 0);
                const days = Math.max(1, parseFloat(inputDays.value) || 1);
                const supply = Math.max(0, parseFloat(inputSupply.value) || 0);
                const checkoutLate = Math.max(0, parseFloat(inputCheckoutLate.value) || 0);
                const prepaid = Math.max(0, parseFloat(inputPrepaid.value) || 0);
                const discount = Math.max(0, parseFloat(inputDiscount.value) || 0);

                // 1. Tiền phòng cơ bản = Giá phòng * Số ngày
                const roomSubtotal = roomPrice * days;

                // 2. Chiết khấu giảm giá
                const discountVal = roomSubtotal * (discount / 100);

                // 3. Tổng cộng hóa đơn = (Tiền phòng - Giảm giá) + Dịch vụ + Phụ thu check-out trễ - Đặt cọc
                const totalBill = Math.max(0, (roomSubtotal - discountVal) + supply + checkoutLate - prepaid);

                // Cập nhật DOM
                if (rSubtotal) rSubtotal.innerText = `${roomSubtotal.toLocaleString()} ₫`;
                if (rDiscountRate) rDiscountRate.innerText = discount;
                if (rDiscountVal) rDiscountVal.innerText = `-${discountVal.toLocaleString()} ₫`;
                if (rSupplyVal) rSupplyVal.innerText = `+${supply.toLocaleString()} ₫`;
                if (rCheckoutLateVal) rCheckoutLateVal.innerText = `+${checkoutLate.toLocaleString()} ₫`;
                if (rPrepaidVal) rPrepaidVal.innerText = `-${prepaid.toLocaleString()} ₫`;
                if (rTotalBill) rTotalBill.innerText = `${Math.ceil(totalBill).toLocaleString()} ₫`;
            }

            if (selectService) {
                selectService.addEventListener('change', (e) => {
                    const val = e.target.value;
                    if (roomConfig[val]) {
                        const cfg = roomConfig[val];
                        if (inputTotal) inputTotal.value = cfg.total;
                        if (inputDays) inputDays.value = cfg.days;
                        if (inputSupply) inputSupply.value = cfg.supply;
                        if (inputCheckoutLate) inputCheckoutLate.value = cfg.checkout_late;
                        if (inputPrepaid) inputPrepaid.value = cfg.prepaid;
                        if (inputDiscount) inputDiscount.value = cfg.discount;
                        calculateRealtime();
                    }
                });
            }

            const inputs = [inputTotal, inputDays, inputSupply, inputCheckoutLate, inputPrepaid, inputDiscount];
            inputs.forEach(input => {
                if (input) {
                    input.addEventListener('input', () => {
                        if(selectService && selectService.value !== 'custom') {
                            const currentVal = selectService.value;
                            const cfg = roomConfig[currentVal];
                            if (cfg && (parseFloat(inputTotal.value) !== cfg.total || parseFloat(inputDays.value) !== cfg.days || parseFloat(inputSupply.value) !== cfg.supply)) {
                                selectService.value = 'custom';
                            }
                        }
                        calculateRealtime();
                    });
                }
            });

            calculateRealtime();
        });

        // Policies Modal
        window.openModal = function(type) {
            const modal = document.getElementById('policyModal');
            if (!modal) return;
            const modalInner = modal.querySelector('div');
            
            const titles = {
                terms: 'Điều khoản sử dụng',
                privacy: 'Chính sách bảo mật',
                payment: 'Chính sách thanh toán'
            };
            
            document.getElementById('modalTitle').innerHTML = '<i class="fas fa-shield-alt mr-2 text-blue-400"></i> ' + (titles[type] || 'Chính sách');
            document.getElementById('modalContent').innerHTML = '<div class="space-y-4 text-gray-300"><p>Các điều khoản chính sách của BitPaw được áp dụng nhất quán trên toàn bộ hệ thống. Nội dung chính sách đang được cập nhật chi tiết cho phân hệ Khách Sạn & Homestay...</p></div>';
            
            modal.classList.remove('hidden');
            setTimeout(() => { 
                modal.classList.remove('opacity-0'); 
                if (modalInner) modalInner.classList.remove('scale-95'); 
            }, 10);
            document.body.style.overflow = 'hidden';
        };

        window.closeModal = function() {
            const modal = document.getElementById('policyModal');
            if (!modal) return;
            const modalInner = modal.querySelector('div');
            modal.classList.add('opacity-0');
            if (modalInner) modalInner.classList.add('scale-95');
            setTimeout(() => { 
                modal.classList.add('hidden'); 
                document.body.style.overflow = ''; 
            }, 300);
        };
        
        const policyModalEl = document.getElementById('policyModal');
        if (policyModalEl) {
            policyModalEl.addEventListener('click', function (e) { 
                if (e.target === this) closeModal(); 
            });
        }
    