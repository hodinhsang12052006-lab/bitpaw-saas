// Reusable Premium CSKH Floating Widget & Mascot AI Chat Component
// Integrated with DeepSeek AI Engine and Supabase CRM Fallback

document.addEventListener("DOMContentLoaded", () => {
    // 1. Inject Premium CSS Styles (Futuristic Dark Neon & Responsive Layout)
    if (!document.getElementById("cskh-widget-styles")) {
        const style = document.createElement("style");
        style.id = "cskh-widget-styles";
        style.innerHTML = `
            .bitpaw-cskh-floating,
            #bitpawCskhFloating,
            .contact-widget {
                position: fixed;
                right: 24px;
                bottom: 28px;
                top: auto !important;
                transform: none !important;
                z-index: 99999 !important;
                display: flex;
                flex-direction: column;
                gap: 12px;
                align-items: center;
                transition: all 0.3s ease;
                opacity: 1 !important;
                visibility: visible !important;
                pointer-events: auto !important;
            }
            .contact-btn {
                width: 48px;
                height: 48px;
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 18px;
                color: white;
                cursor: pointer;
                transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
                box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
                text-decoration: none;
                border: none;
                outline: none;
                position: relative;
            }
            .contact-btn:hover {
                transform: scale(1.15) translateY(-2px);
                box-shadow: 0 10px 25px rgba(6, 182, 212, 0.45);
            }
            
            /* High-Contrast Cyber Tooltips */
            .contact-btn::after {
                content: attr(data-tooltip);
                position: absolute;
                right: 60px;
                top: 50%;
                transform: translateY(-50%) scale(0.8);
                background: rgba(8, 6, 26, 0.96);
                border: 1px solid rgba(6, 182, 212, 0.5);
                color: #22d3ee;
                padding: 6px 12px;
                border-radius: 8px;
                font-size: 11px;
                font-weight: 800;
                white-space: nowrap;
                opacity: 0;
                pointer-events: none;
                transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
                box-shadow: 0 4px 15px rgba(6, 182, 212, 0.25);
            }
            .contact-btn:hover::after {
                opacity: 1;
                transform: translateY(-50%) scale(1);
            }
            
            .btn-whatsapp { background: #25D366; }
            .btn-mess { background: linear-gradient(45deg, #00B2FF, #006AFF); }
            .btn-call { background: #10b981; animation: ring-widget 2s infinite, pulse-call 1.5s infinite alternate; }
            .btn-mail { background: #ea4335; }
            
            @keyframes ring-widget { 
                0% { transform: scale(1); } 
                10% { transform: scale(1.1) rotate(8deg); } 
                20% { transform: scale(1.1) rotate(-8deg); } 
                30% { transform: scale(1.1) rotate(8deg); } 
                40% { transform: scale(1.1) rotate(-8deg); } 
                50% { transform: scale(1); } 
                100% { transform: scale(1); } 
            }
            
            @keyframes pulse-call {
                0% { box-shadow: 0 0 5px rgba(16, 185, 129, 0.4); }
                100% { box-shadow: 0 0 25px rgba(16, 185, 129, 0.85); }
            }
            
            #backToTop { transition: all 0.3s ease; opacity: 0; pointer-events: none; transform: scale(0.7); }
            #backToTop.show { opacity: 1; pointer-events: auto; transform: scale(1); }
            
            #chatWidget { 
                position: fixed;
                right: 92px;
                bottom: 28px;
                width: 390px;
                height: 540px;
                max-height: 75vh;
                transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1); 
                transform-origin: bottom right; 
                display: flex !important;
                flex-direction: column !important;
                overflow: hidden !important;
                user-select: none;
                -webkit-user-select: none;
                -moz-user-select: none;
                -ms-user-select: none;
            }
            #chatWidget.hidden-chat { transform: scale(0) translateY(50px); opacity: 0; pointer-events: none; }
            .glass-chat { background: rgba(8, 6, 26, 0.98); backdrop-filter: blur(25px); border: 1px solid rgba(6, 182, 212, 0.4); }
            
            @keyframes mascot-float {
                0% { transform: translateY(0px); }
                50% { transform: translateY(-6px); }
                100% { transform: translateY(0px); }
            }
            .mascot-glow { 
                box-shadow: 0 0 15px rgba(6, 182, 212, 0.4); 
                border-color: #22d3ee; 
                transition: all 0.3s;
                animation: mascot-float 3s ease-in-out infinite;
            }
            .mascot-glow:hover { box-shadow: 0 0 25px rgba(6, 182, 212, 0.8); }
            
            .modal-scroll::-webkit-scrollbar { width: 6px; }
            .modal-scroll::-webkit-scrollbar-track { background: rgba(255, 255, 255, 0.02); }
            .modal-scroll::-webkit-scrollbar-thumb { background: rgba(6, 182, 212, 0.45); border-radius: 10px; }
            
            /* Chat message bubbles select-text enabled to allow easy copy */
            .chat-ai { 
                background: linear-gradient(135deg, rgba(8, 12, 32, 0.9), rgba(15, 23, 42, 0.9)); 
                border: 1px solid rgba(6, 182, 212, 0.25); 
                border-radius: 4px 18px 18px 18px; 
                box-shadow: 0 4px 15px rgba(6, 182, 212, 0.08); 
                user-select: text !important;
                -webkit-user-select: text !important;
                -moz-user-select: text !important;
                -ms-user-select: text !important;
            }
            .chat-user { 
                background: linear-gradient(135deg, rgba(6, 182, 212, 0.8), rgba(59, 130, 246, 0.8)); 
                border: 1px solid rgba(255, 255, 255, 0.15); 
                border-radius: 18px 4px 18px 18px; 
                box-shadow: 0 4px 15px rgba(6, 182, 212, 0.25); 
                user-select: text !important;
                -webkit-user-select: text !important;
                -moz-user-select: text !important;
                -ms-user-select: text !important;
            }
            
            /* Typing Indicator Dots */
            .typing-bubble { display: flex; gap: 4px; align-items: center; padding: 10px 14px; border-radius: 16px; border-top-left-radius: 2px; width: max-content; }
            .typing-dot { width: 6px; height: 6px; background: #22d3ee; border-radius: 50%; animation: typing-bounce 1s infinite ease-in-out; }
            .typing-dot:nth-child(2) { animation-delay: 0.2s; }
            .typing-dot:nth-child(3) { animation-delay: 0.4s; }
            @keyframes typing-bounce {
                0%, 100% { transform: translateY(0); }
                50% { transform: translateY(-5px); }
            }
            
            /* Quick replies horizontal container styling */
            .quick-replies-container {
                display: flex;
                gap: 8px;
                overflow-x: auto;
                white-space: nowrap;
                padding: 10px 14px;
                padding-bottom: 5px;
                background: rgba(0, 0, 0, 0.35);
                border-top: 1px solid rgba(255, 255, 255, 0.06);
                scrollbar-width: none;
                -webkit-overflow-scrolling: touch;
                cursor: grab;
            }
            .quick-replies-container::-webkit-scrollbar {
                display: none;
            }
            .quick-replies-container.grabbing {
                cursor: grabbing;
                user-select: none;
            }
            .quick-reply-chip {
                background: rgba(34, 211, 238, 0.08);
                border: 1px solid rgba(34, 211, 238, 0.25);
                color: #22d3ee;
                border-radius: 9999px;
                padding: 6px 12px;
                font-size: 11px;
                font-weight: 700;
                cursor: pointer;
                transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
                white-space: nowrap;
                user-select: none;
                flex-shrink: 0;
            }
            .quick-reply-chip:hover {
                background: rgba(34, 211, 238, 0.2);
                border-color: #22d3ee;
                color: white;
                transform: translateY(-1.5px);
                box-shadow: 0 4px 12px rgba(34, 211, 238, 0.25);
            }
            
            .premium-support-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 20px; width: 100%; margin-top: 30px; }
            .premium-support-card { background: rgba(15, 25, 45, 0.65); backdrop-filter: blur(16px); border: 1px solid rgba(6, 182, 212, 0.25); border-radius: 1.5rem; padding: 25px; transition: all 0.3s; }
            .premium-support-card:hover { border-color: #06b6d4; box-shadow: 0 8px 30px rgba(6, 182, 212, 0.2); }
            .cskh-static-item { display: flex; align-items: center; gap: 15px; padding: 12px; border-radius: 1rem; transition: 0.2s; text-decoration: none; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.03); }
            .cskh-static-item:hover { background: rgba(6,182,212,0.15); border-color: rgba(6,182,212,0.3); }

            @media (max-width: 768px) {
                .bitpaw-cskh-floating,
                #bitpawCskhFloating,
                .contact-widget {
                    right: 12px !important;
                    top: auto !important;
                    bottom: 18px !important;
                    transform: none !important;
                    gap: 8px;
                }
                .contact-btn {
                    width: 40px;
                    height: 40px;
                    font-size: 16px;
                }
                #mascot-toggle-btn .w-14 {
                    width: 44px !important;
                    height: 44px !important;
                }
                .contact-btn::after {
                    display: none;
                }
            }
            @media (max-width: 640px) {
                .bitpaw-cskh-floating,
                #bitpawCskhFloating,
                .contact-widget {
                    right: 12px !important;
                    bottom: 18px !important;
                    gap: 10px !important;
                }
                #chatWidget {
                    left: 12px;
                    right: 12px;
                    bottom: 84px;
                    width: auto !important;
                    height: 480px;
                    max-height: 65vh;
                }
            }
        `;
        document.head.appendChild(style);
    }

    // 2. Clear out any existing duplicate static elements inside the DOM
    const oldWidgets = document.querySelectorAll("body > .contact-widget, #bitpawCskhFloating");
    oldWidgets.forEach(w => w.remove());
    const oldChatboxes = document.querySelectorAll("#chatWidget");
    oldChatboxes.forEach(c => c.remove());

    // 3. Inject Fresh Premium DOM Elements
    const contactWidget = document.createElement("div");
    contactWidget.id = "bitpawCskhFloating";
    contactWidget.className = "bitpaw-cskh-floating contact-widget z-[99999]";
    // Nhóm nút liên hệ nhanh (mail/WhatsApp/Messenger/hotline) trỏ THẲNG tới kênh liên hệ của
    // chính BitPaw (nhà cung cấp phần mềm) — đúng cho khách đang tham khảo mua phần mềm trên
    // landing page, nhưng SAI hoàn toàn khi hiện trên trang đặt lịch công khai của 1 tiệm: khách
    // hàng cuối bấm "Hotline 24/7" tưởng gọi cho tiệm lại vô tình gọi cho BitPaw. Ẩn hẳn nhóm này
    // ở ngữ cảnh customer_booking, chỉ giữ lại avatar mở chat (đã đổi đúng vai trợ lý đặt lịch).
    const isBookingContext = window.BITPAW_CHAT_CONTEXT === 'customer_booking';
    const mascotTooltip = isBookingContext ? 'Cần giúp đặt lịch?<br>Nhắn em ngay!' : 'Cần tư vấn?<br>Chat với BitPaw!';
    contactWidget.innerHTML = `
        <div class="relative group cursor-pointer mb-1" id="mascot-toggle-btn">
            <div class="absolute right-14 top-2 bg-[#08061a] border border-cyan-500/40 text-[#22d3ee] text-[11px] font-bold py-1.5 px-3 rounded-lg rounded-tr-none w-max shadow-lg opacity-0 group-hover:opacity-100 transition-all duration-300 transform translate-x-2 group-hover:translate-x-0 pointer-events-none z-50">
                ${mascotTooltip}
            </div>
            <div class="w-14 h-14 bg-[#08061a] border-2 border-cyan-400 rounded-full flex items-center justify-center shadow-[0_0_12px_rgba(6,182,212,0.5)] group-hover:scale-110 transition-transform overflow-hidden mascot-glow">
                <img src="/static/cho1.jpg" onerror="this.onerror=null; this.src='https://cdn-icons-png.flaticon.com/512/6182/6182181.png';" class="w-full h-full object-cover">
            </div>
        </div>
        ${isBookingContext ? '' : `
        <button id="backToTop" class="contact-btn bg-gray-800 border border-gray-600 text-xs" data-tooltip="Lên đầu">
            <i class="fas fa-chevron-up"></i>
        </button>
        <a href="mailto:bitpawsoftware@gmail.com" class="contact-btn btn-mail" data-tooltip="Email">
            <i class="fas fa-envelope"></i>
        </a>
        <a href="https://wa.me/84794678904" target="_blank" class="contact-btn btn-whatsapp" data-tooltip="WhatsApp">
            <i class="fab fa-whatsapp"></i>
        </a>
        <a href="https://www.facebook.com/profile.php?id=61591611704371" target="_blank" class="contact-btn btn-mess" data-tooltip="Messenger">
            <i class="fab fa-facebook-messenger"></i>
        </a>
        <a href="tel:+61385937410" class="contact-btn btn-call" data-tooltip="Hotline 24/7">
            <i class="fas fa-phone-alt"></i>
        </a>
        `}
    `;
    document.body.appendChild(contactWidget);

    // BUG THẬT đã phát hiện (Playwright elementFromPoint tại đúng góc nút bấm ra ảnh mascot, không
    // phải nút): widget position:fixed bottom-phải luôn đứng CỐ ĐỊNH theo viewport bất kể trang
    // cuộn tới đâu — trên booking.html, nút "CONFIRM BOOKING" nằm cuối 1 form dài, khách cuộn tới
    // đâu để thấy nút là nút xuất hiện ở ĐÚNG vùng đó của màn hình, luôn trùng vùng widget đang
    // đứng. Thêm margin dưới form không giải quyết được (scrollIntoView/hành vi cuộn thật của
    // khách vẫn có thể dừng đúng lúc nút chạm đáy màn hình). Cách chắc chắn duy nhất: dịch hẳn vị
    // trí CỐ ĐỊNH của widget lên cao hơn hẳn vùng nút bấm cuối form, chỉ áp dụng ở ngữ cảnh đặt
    // lịch (không đụng vị trí widget ở mọi trang marketing khác).
    if (isBookingContext) {
        // setProperty(..., 'important') bắt buộc — CSS injected ở trên có
        // "@media (max-width: 768px) { #bitpawCskhFloating { bottom: 18px !important; } }"
        // (khách quét QR trên ĐIỆN THOẠI luôn rơi vào đúng media query mobile này), 1 style.bottom
        // gán thường KHÔNG thắng nổi !important của rule trong <style>, verify bằng
        // getComputedStyle() vẫn ra 18px dù style="bottom:104px" đã có mặt thật trên element.
        contactWidget.style.setProperty('bottom', '104px', 'important');
    }

    const chatWidget = document.createElement("div");
    chatWidget.id = "chatWidget";
    chatWidget.className = "hidden-chat fixed glass-chat rounded-2xl shadow-[0_15px_50px_rgba(0,0,0,0.8)] z-[10000] flex flex-col overflow-hidden text-white";
    chatWidget.innerHTML = `
        <div class="bg-gradient-to-r from-cyan-600 to-blue-700 p-4 flex justify-between items-center text-white border-b border-white/15">
            <div class="flex items-center gap-3">
                <div class="relative">
                    <img src="/static/cho1.jpg" onerror="this.onerror=null; this.src='https://cdn-icons-png.flaticon.com/512/6182/6182181.png';" class="w-10 h-10 rounded-full border border-white/40 object-cover">
                    <div class="absolute bottom-0 right-0 w-2.5 h-2.5 bg-green-400 border border-blue-700 rounded-full animate-pulse"></div>
                </div>
                <div>
                    <h4 class="font-bold text-sm">BitPaw AI Tư Vấn</h4>
                    <p class="text-[10px] text-cyan-200 flex items-center gap-1"><i class="fas fa-bolt"></i> Trực tuyến 24/7</p>
                </div>
            </div>
            <button id="close-chat-btn" class="text-white/60 hover:text-white transition text-lg"><i class="fas fa-times"></i></button>
        </div>
        
        <div class="flex flex-col flex-1 min-h-0" id="cskh-tab-mascot">
            <div class="flex gap-2 p-3 pb-0" id="chat-mode-selector">
                <button type="button" id="chatModeAiBtn" class="flex-1 text-[11px] font-bold px-3 py-2 rounded-xl border border-cyan-400/60 bg-cyan-500/20 text-cyan-300 transition flex items-center justify-center gap-1.5"><i class="fas fa-robot"></i> Chat with AI</button>
                <button type="button" id="chatModeHumanBtn" class="flex-1 text-[11px] font-bold px-3 py-2 rounded-xl border border-white/10 bg-black/30 text-gray-400 hover:text-white hover:border-white/30 transition flex items-center justify-center gap-1.5"><i class="fas fa-headset"></i> Talk to Human Agent</button>
            </div>
            <div class="p-4 flex-1 overflow-y-auto flex flex-col gap-3 modal-scroll" id="chat-messages-container">
                </div>

            <div class="quick-replies-container" id="quick-replies-container">
                <button type="button" onclick="handleQuickReply('Tôi làm tiệm nail')" class="quick-reply-chip">Nail Salon</button>
                <button type="button" onclick="handleQuickReply('Tôi mở quán cafe')" class="quick-reply-chip">Restaurant / Cafe</button>
                <button type="button" onclick="handleQuickReply('Tôi cần QR Order')" class="quick-reply-chip">Marketing & Website</button>
                <button type="button" onclick="handleQuickReply('Tôi cần tính lương')" class="quick-reply-chip">Payroll Setup</button>
                <button type="button" onclick="handleQuickReply('Tôi muốn báo giá')" class="quick-reply-chip">Get a Quote</button>
            </div>

            <div class="p-3 border-t border-white/10 bg-black/40">
                <form id="mascot-chat-form" class="flex flex-col gap-2">
                    <div id="phone-container">
                        <input type="text" id="chatPhone" placeholder="Your Phone Number" required class="w-full bg-black/60 border border-white/10 rounded-xl px-4 py-2.5 text-xs text-white focus:outline-none focus:border-cyan-400 placeholder-gray-500">
                    </div>
                    <div class="flex items-center gap-2 bg-black/60 border border-white/10 rounded-xl pr-2 focus-within:border-cyan-400 transition">
                        <input type="text" id="chatMsg" placeholder="Enter your phone number to start chatting..." required disabled class="w-full bg-transparent px-4 py-2.5 text-xs text-white focus:outline-none placeholder-gray-500 disabled:opacity-50">
                        <button type="submit" id="chatSendBtn" disabled class="bg-cyan-500 hover:bg-cyan-400 text-black w-8 h-8 rounded-lg font-bold transition flex items-center justify-center shrink-0 disabled:opacity-40 disabled:pointer-events-none"><i class="fas fa-paper-plane text-xs"></i></button>
                    </div>
                </form>
            </div>
        </div>
    `;
    document.body.appendChild(chatWidget);

    // Drag to scroll for Quick Replies on PC
    const qrContainer = document.getElementById("quick-replies-container");
    if (qrContainer) {
        let isDown = false;
        let startX;
        let scrollLeft;

        qrContainer.addEventListener("mousedown", (e) => {
            isDown = true;
            qrContainer.classList.add("grabbing");
            startX = e.pageX - qrContainer.offsetLeft;
            scrollLeft = qrContainer.scrollLeft;
        });

        qrContainer.addEventListener("mouseleave", () => {
            isDown = false;
            qrContainer.classList.remove("grabbing");
        });

        qrContainer.addEventListener("mouseup", () => {
            isDown = false;
            qrContainer.classList.remove("grabbing");
        });

        qrContainer.addEventListener("mousemove", (e) => {
            if (!isDown) return;
            e.preventDefault();
            const x = e.pageX - qrContainer.offsetLeft;
            const walk = (x - startX) * 1.5;
            qrContainer.scrollLeft = scrollLeft - walk;
        });
    }

    // 4. Lời chào + tên ngành của bot tư vấn trên landing — THEO NGÔN NGỮ trang (VI/EN). Persona thật dựng hoàn
    // toàn ở server (ai_sales_prompts.compose_system_prompt — trung thực là trợ lý AI, trả lời đúng ngôn ngữ khách).
    // Trước đây file này còn chứa prompt cũ (server đã bỏ qua) dặn bot "TUYỆT ĐỐI không nhận là AI", và lời chào
    // trộn Anh-Việt trong cùng 1 câu ("Hi anh/chị! Em là trợ lý... The system helps...").
    const industryData = {
        nail: { vi: ["Nails & Salon", "Chào anh/chị! BitPaw giúp tiệm nail xếp tua thợ tự động, chia hoa hồng + tips rõ ràng và tính bill trong vài giây. Tiệm mình đang có bao nhiêu thợ ạ?"],
                en: ["Nails & Salon", "Hi! BitPaw helps nail salons rotate technician turns automatically, split commission and tips clearly, and close bills in seconds. How many technicians does your salon have?"] },
        spa: { vi: ["Spa & Beauty", "Chào anh/chị! BitPaw giúp spa quản lý liệu trình còn lại của khách, đặt lịch online và tính hoa hồng kỹ thuật viên minh bạch. Cơ sở mình có bao nhiêu giường và kỹ thuật viên ạ?"],
               en: ["Spa & Beauty", "Hi! BitPaw helps spas track each client's remaining treatment sessions, take online bookings and pay therapist commission transparently. How many beds and therapists do you have?"] },
        fnb: { vi: ["Nhà hàng & Cafe", "Chào anh/chị! BitPaw giúp quán gọi món bằng QR tại bàn, đẩy món thẳng xuống màn hình bếp và thanh toán nhanh. Quán mình có khoảng bao nhiêu bàn ạ?"],
               en: ["Restaurant & Cafe", "Hi! BitPaw gives restaurants QR table ordering, a live kitchen display and fast checkout. Roughly how many tables do you run?"] },
        hotel: { vi: ["Khách sạn & Homestay", "Chào anh/chị! BitPaw cho khách sạn sơ đồ phòng trống/đang ở theo thời gian thực, check-in/check-out và tính tiền phụ thu nhanh. Bên mình có bao nhiêu phòng ạ?"],
                 en: ["Hotel & Homestay", "Hi! BitPaw gives hotels a live room board (free / occupied), quick check-in/out and extra-charge billing. How many rooms do you have?"] },
        karaoke: { vi: ["Karaoke & Bida", "Chào anh/chị! BitPaw tự tính tiền giờ karaoke/bida theo block phút, hiện phòng/bàn trống-bận theo thời gian thực và gọi đồ uống tại phòng. Quán mình có bao nhiêu phòng hoặc bàn ạ?"],
                   en: ["Karaoke & Billiards", "Hi! BitPaw bills karaoke rooms and pool tables by the minute block, shows free/busy rooms live and takes in-room drink orders. How many rooms or tables do you have?"] },
        office: { vi: ["Văn phòng & Nhân sự", "Chào anh/chị! BitPaw giúp nhân viên chấm công bằng camera + GPS, duyệt đơn nghỉ/hoàn ứng online và tính bảng lương tự động. Công ty mình có khoảng bao nhiêu nhân sự ạ?"],
                  en: ["Office & HR", "Hi! BitPaw lets staff clock in with camera + GPS, approves leave and expense requests online and runs payroll automatically. Roughly how many employees do you have?"] },
        retail: { vi: ["Cửa hàng bán lẻ", "Chào anh/chị! BitPaw giúp bán hàng bằng quét mã vạch, trừ kho ngay khi bán và cảnh báo hàng sắp hết. Shop mình đang bán mặt hàng gì ạ?"],
                  en: ["Retail store", "Hi! BitPaw gives retail stores barcode checkout, real-time stock deduction and low-stock alerts. What kind of products do you sell?"] },
        production: { vi: ["Sản xuất & Nhà xưởng", "Chào anh/chị! BitPaw giúp xưởng ghi sản lượng theo ca, trừ nguyên vật liệu theo định mức và chấm công công nhân. Xưởng mình sản xuất mặt hàng gì ạ?"],
                      en: ["Production", "Hi! BitPaw helps workshops log output per shift, deduct materials by recipe (BOM) and track worker attendance. What do you manufacture?"] },
        technical: { vi: ["Dịch vụ kỹ thuật", "Chào anh/chị! BitPaw giúp giao việc sửa chữa cho thợ, thợ báo cáo kèm ảnh + chữ ký khách ngay tại chỗ và tính công tự động. Đội mình có bao nhiêu thợ đi hiện trường ạ?"],
                     en: ["Technical services", "Hi! BitPaw dispatches repair jobs to technicians, who report on-site with photos and the customer's signature, and pays them automatically. How many field technicians do you have?"] },
        hr: { vi: ["Quản trị nhân sự", "Chào anh/chị! BitPaw giúp quản lý ca làm, chấm công camera + GPS và tính lương nhiều thành phần chỉ với 1 lần bấm. Bên mình đang vướng nhất ở chấm công hay tính lương ạ?"],
              en: ["HR management", "Hi! BitPaw manages shifts, camera + GPS clock-in and multi-part payroll in one click. Is attendance or payroll your biggest headache right now?"] },
        general: { vi: ["BitPaw Software", "Chào anh/chị! BitPaw là phần mềm quản lý cho tiệm nail, spa, nhà hàng, bán lẻ, khách sạn... gồm bán hàng (POS), nhân sự, tính lương và chăm sóc khách. Anh/chị đang kinh doanh ngành nào ạ?"],
                   en: ["BitPaw Software", "Hi! BitPaw is business software for nail salons, spas, restaurants, retail, hotels and more — POS, staff, payroll and customer care in one place. What kind of business do you run?"] },
    };
    function pageLangIsVi() {
        let l = "";
        try { l = localStorage.getItem("bitpaw_lang") || ""; } catch (e) { /* bị chặn */ }
        if (!l) { const m = document.cookie.match(/bitpaw_lang=(vi|en)/); l = m ? m[1] : ""; }
        return (l || document.documentElement.lang || "en").slice(0, 2) === "vi";
    }

    function getPageIndustry() {
        const path = window.location.pathname.toLowerCase();
        if (path.includes("nail")) return "nail";
        if (path.includes("spa")) return "spa";
        if (path.includes("fnb") || path.includes("restaurant") || path.includes("cafe")) return "fnb";
        if (path.includes("hotel")) return "hotel";
        if (path.includes("karaoke")) return "karaoke";
        if (path.includes("office")) return "office";
        if (path.includes("retail")) return "retail";
        if (path.includes("production")) return "production";
        if (path.includes("technical")) return "technical";
        if (path.includes("hr") || path.includes("staff")) return "hr";
        return "general";
    }

    const industryCode = getPageIndustry();
    const safeIndustry = industryData[industryCode] ? industryCode : 'general';
    // CHAT_CONTEXT: 'customer_booking' khi widget đang chạy trên chính trang đặt lịch công khai
    // của 1 tiệm (booking.html) — đối tượng đang chat là KHÁCH HÀNG CUỐI của tiệm, không phải
    // chủ tiệm tiềm năng đang được BitPaw chào bán phần mềm. BUG THẬT đã phát hiện: trước đây
    // dùng chung industryData[...] ở trên cho mọi trang, nên khách quét QR đặt lịch nail lại bị
    // chào bằng câu "BitPaw giúp Nail salon chia tua, tính hoa hồng..." — đúng nội dung bán phần
    // mềm cho CHỦ tiệm, hoàn toàn sai người nghe. Override toàn bộ dna cho đúng vai lễ tân của
    // chính tiệm khi ở ngữ cảnh này (server cũng branch riêng persona, xem app.py::secure_ai_generate
    // + ai_sales_prompts.compose_booking_assistant_prompt()).
    const CHAT_CONTEXT = window.BITPAW_CHAT_CONTEXT || null;
    // Trang đặt lịch hiện theo ngôn ngữ mặc định của tiệm (<html lang>) — tiệm ở Úc/Mỹ là tiếng Anh;
    // trước đây widget luôn chào tiếng Việt + nhãn "SĐT Zalo" với khách Úc.
    const BOOKING_VI = (document.documentElement.lang || '').toLowerCase().startsWith('vi');
    const BT = BOOKING_VI ? {
        title: "Trợ Lý Đặt Lịch",
        greeting: "Chào bạn! Mình là trợ lý đặt lịch của tiệm 💅 Bạn muốn đặt dịch vụ gì và vào lúc nào ạ? Mình sẽ xếp lịch giúp bạn ngay.",
        phone: "Số điện thoại của bạn", phoneLabel: "SĐT", request: "Yêu cầu",
        typeMsg: "Nhập tin nhắn...", needPhone: "Nhập số điện thoại để bắt đầu chat...",
        shop: "Nhân viên tiệm", typing: "Đang trả lời...",
        handoff: "Nhân viên tiệm đã nhận tin của bạn và sẽ trả lời ngay trong khung chat này 💅",
        slow: "Dạ tiệm đang xử lý hơi chậm, bạn nhắn lại giúp em dịch vụ và giờ bạn muốn đặt nhé!",
        slow2: "Dạ tiệm đang xử lý hơi chậm, bạn nhắn lại giúp em nhé!",
    } : {
        title: "Booking Assistant",
        greeting: "Hi! I'm the salon's booking assistant 💅 Which service would you like, and when? I'll book it for you right away.",
        phone: "Your phone number", phoneLabel: "Phone", request: "Request",
        typeMsg: "Type your message...", needPhone: "Enter your phone number to start chatting...",
        shop: "Salon staff", typing: "Typing...",
        handoff: "A staff member has your message and will reply right here in this chat 💅",
        slow: "Sorry, we're a little slow right now — please send the service and time you'd like again!",
        slow2: "Sorry, we're a little slow right now — please send that again!",
    };
    const dna = CHAT_CONTEXT === 'customer_booking'
        ? { title: BT.title, greeting: BT.greeting, prompt: "" }
        : (() => { const d = (industryData[safeIndustry] || industryData.general)[pageLangIsVi() ? 'vi' : 'en'];
                   return { title: d[0], greeting: d[1] }; })();

    // Đa doanh nghiệp (multi-tenant): nếu trang hiện tại là widget nhúng thật của 1 doanh
    // nghiệp đã đăng nhập (session có business_id, xem templates/components/cskh_global.html),
    // BUSINESS_ID sẽ có giá trị thật và backend sẽ tự động tư vấn đúng tên cửa hàng + bảng giá
    // thật của tenant đó. Trên các trang landing marketing chung (không đăng nhập), giá trị này
    // là null và backend tự dùng persona chung theo ngành như cũ.
    const BUSINESS_ID = window.BITPAW_BUSINESS_ID || null;

    // Dọn lại phần UI tĩnh (không thuộc dna) cho đúng ngữ cảnh đặt lịch: đổi tiêu đề header,
    // ẩn hàng quick-reply "Nail Salon/Restaurant/Payroll..." (chọn ngành phần mềm — vô nghĩa
    // với khách đang đặt lịch), ẩn tab "Talk to Human Agent" (dành cho agent Sales của BitPaw,
    // không phải lễ tân của tiệm), và đổi placeholder ô số điện thoại cho đúng mục đích thật
    // (để tiệm liên hệ xác nhận lịch, không phải "chuyên viên tư vấn gọi lại").
    if (CHAT_CONTEXT === 'customer_booking') {
        const headerTitleEl = chatWidget.querySelector(".font-bold.text-sm");
        if (headerTitleEl) headerTitleEl.textContent = BT.title;
        const headerSubEl = headerTitleEl && headerTitleEl.nextElementSibling;
        if (headerSubEl && !BOOKING_VI) headerSubEl.innerHTML = '<i class="fas fa-bolt"></i> Online 24/7';
        const quickRepliesEl = document.getElementById("quick-replies-container");
        if (quickRepliesEl) quickRepliesEl.style.display = "none";
        // Chỉ còn 1 chế độ (AI) -> cả hàng chọn chế độ chỉ chiếm chỗ trên màn hình điện thoại.
        const modeSelectorEl = document.getElementById("chat-mode-selector");
        if (modeSelectorEl) modeSelectorEl.style.display = "none";
        const phoneInputEl = document.getElementById("chatPhone");
        if (phoneInputEl) { phoneInputEl.placeholder = BT.phone; phoneInputEl.type = "tel"; phoneInputEl.autocomplete = "tel"; }
    }

    // Giờ địa phương của khách (cùng múi giờ với tiệm) — để trợ lý đặt lịch hiểu "mai 3h chiều".
    function localNowIso() {
        const d = new Date();
        const p = (n) => String(n).padStart(2, "0");
        return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
    }

    // 5. Initialize State Variables and DOM References
    const chatForm = document.getElementById("mascot-chat-form");
    const chatMsgInput = document.getElementById("chatMsg");
    const chatPhoneInput = document.getElementById("chatPhone");
    const chatSendBtn = document.getElementById("chatSendBtn");
    const msgContainer = document.getElementById("chat-messages-container");

    let isLeadSubmitted = false;
    let userPhone = "";
    let chatHistory = [];
    let chatMode = "ai"; // "ai" | "human"
    let humanChatStream = null; // EventSource — chỉ mở 1 lần cho mỗi SĐT, xem startHumanAgentStream()
    let renderedStaffMessageCount = 0; // đếm số tin nhắn staff đã render, tránh lặp khi poll lại

    // Sync state globally for quick reply handlers
    window.isLeadSubmittedGlobal = false;

    // Bắt buộc nhập SĐT trước khi được gõ/gửi tin nhắn — khoá ô nhắn tin + nút gửi cho tới khi
    // chatPhone có giá trị (không validate định dạng ở đây, chỉ chặn rỗng; validate số hợp lệ
    // vẫn là việc riêng của hasValidPhone bên dưới khi lưu lead).
    function updatePhoneGateState() {
        const hasPhoneValue = !!(chatPhoneInput && chatPhoneInput.value.trim().length > 0);
        if (chatMsgInput) {
            chatMsgInput.disabled = !hasPhoneValue;
            chatMsgInput.placeholder = CHAT_CONTEXT === 'customer_booking'
                ? (hasPhoneValue ? BT.typeMsg : BT.needPhone)
                : (hasPhoneValue ? "Type your message here..." : "Enter your phone number to start chatting...");
        }
        if (chatSendBtn) chatSendBtn.disabled = !hasPhoneValue;
        return hasPhoneValue;
    }
    if (chatPhoneInput) {
        chatPhoneInput.addEventListener("input", updatePhoneGateState);
        updatePhoneGateState();
    }

    // 6. Global Quick Reply Chip Click Handler
    window.handleQuickReply = function (text) {
        const chatPhoneInput = document.getElementById("chatPhone");
        if (chatPhoneInput && !chatPhoneInput.value.trim()) {
            chatPhoneInput.focus();
            return;
        }
        const chatMsgInput = document.getElementById("chatMsg");
        if (chatMsgInput) {
            chatMsgInput.value = text;
        }
        const chatForm = document.getElementById("mascot-chat-form");
        if (chatForm) {
            chatForm.dispatchEvent(new Event('submit'));
        }
    };

    // 6b. AI / Human Agent Mode Selector — chuyển sang chat thật với Admin qua bot_customers/
    // bot_messages (route /api/cskh/chat/*), Admin trả lời từ /super_admin "Tất Cả Hội Thoại".
    const chatModeAiBtn = document.getElementById("chatModeAiBtn");
    const chatModeHumanBtn = document.getElementById("chatModeHumanBtn");
    function setChatMode(mode) {
        chatMode = mode;
        const activeCls = ["border-cyan-400/60", "bg-cyan-500/20", "text-cyan-300"];
        const inactiveCls = ["border-white/10", "bg-black/30", "text-gray-400"];
        if (chatModeAiBtn && chatModeHumanBtn) {
            const aiActive = mode === "ai";
            chatModeAiBtn.classList.toggle("border-cyan-400/60", aiActive);
            chatModeAiBtn.classList.toggle("bg-cyan-500/20", aiActive);
            chatModeAiBtn.classList.toggle("text-cyan-300", aiActive);
            chatModeAiBtn.classList.toggle("border-white/10", !aiActive);
            chatModeAiBtn.classList.toggle("bg-black/30", !aiActive);
            chatModeAiBtn.classList.toggle("text-gray-400", !aiActive);

            chatModeHumanBtn.classList.toggle("border-cyan-400/60", !aiActive);
            chatModeHumanBtn.classList.toggle("bg-cyan-500/20", !aiActive);
            chatModeHumanBtn.classList.toggle("text-cyan-300", !aiActive);
            chatModeHumanBtn.classList.toggle("border-white/10", aiActive);
            chatModeHumanBtn.classList.toggle("bg-black/30", aiActive);
            chatModeHumanBtn.classList.toggle("text-gray-400", aiActive);
        }
    }
    if (chatModeAiBtn) {
        chatModeAiBtn.addEventListener("click", () => {
            if (chatMode === "ai") return;
            setChatMode("ai");
            appendMessage("ai", "You're back with the AI Assistant. How can I help?");
        });
    }
    if (chatModeHumanBtn) {
        chatModeHumanBtn.addEventListener("click", () => {
            if (chatMode === "human") return;
            setChatMode("human");
            const phoneVal = chatPhoneInput ? chatPhoneInput.value.trim() : "";
            if (phoneVal) {
                appendMessage("ai", "You're now connected with our Human Agent team. Type your message below and a real team member will reply here shortly.");
                startHumanAgentStream(phoneVal);
            } else {
                appendMessage("ai", "You've requested a Human Agent — please enter your phone number below so our team can reply to you here.");
            }
        });
    }

    // 6c. Human Agent messaging — gửi/nhận tin nhắn thật với Admin, thay AI Copilot generate
    // reply. Poll lại /api/cskh/chat/messages mỗi khi nhận tín hiệu "có gì mới" từ SSE
    // /api/stream/cskh_chat (đúng pattern _sse_change_signal + EventSource đã dùng ở
    // super_admin.html/loadCskhLeads, chỉ khác đây là phía khách, không có session).
    async function fetchHumanAgentReplies(phone) {
        try {
            const res = await fetch("/api/cskh/chat/messages?phone=" + encodeURIComponent(phone));
            const json = await res.json();
            if (!json.success) return;
            const staffMessages = (json.messages || []).filter(m => m.sender_type !== "customer");
            if (staffMessages.length > renderedStaffMessageCount) {
                staffMessages.slice(renderedStaffMessageCount).forEach(m => appendMessage("ai", m.content));
                renderedStaffMessageCount = staffMessages.length;
            }
        } catch (err) {
            console.log("Fetching human agent replies deferred: ", err);
        }
    }

    function startHumanAgentStream(phone) {
        if (!phone || humanChatStream) return;
        fetchHumanAgentReplies(phone); // lấy ngay lịch sử/reply đã có trước khi mở kênh SSE
        humanChatStream = new EventSource("/api/stream/cskh_chat?phone=" + encodeURIComponent(phone));
        humanChatStream.onmessage = () => fetchHumanAgentReplies(phone);
        humanChatStream.onerror = () => { /* EventSource tự reconnect, không cần xử lý thêm */ };
    }

    // 6d. Nhân viên tiệm trả lời khách NGAY trong widget đặt lịch. BUG THẬT đã vá (đo thật 10/2026): chủ
    // tiệm trả lời trong /ai_bot (sender_type='staff') nhưng widget trên trang đặt lịch không hề nghe kênh
    // nào cho hội thoại "business_id:SĐT" -> khách đang chờ KHÔNG BAO GIỜ thấy câu trả lời. Dùng lại kênh
    // public của /portal (/api/portal/stream + /api/portal/messages, cùng khoá customer_id).
    let handoffNoticeShown = false;
    let shopReplyStream = null;
    let shopReplySeen = null; // số tin staff đã có lúc bắt đầu nghe — chỉ hiện tin MỚI
    async function fetchShopReplies(customerId) {
        try {
            const res = await fetch("/api/portal/messages?customer_id=" + encodeURIComponent(customerId));
            const json = await res.json();
            if (!json.success) return false;
            const staff = (json.data || []).filter(m => m.sender_type === "staff");
            if (shopReplySeen === null) { shopReplySeen = staff.length; return true; }
            staff.slice(shopReplySeen).forEach(m => appendMessage("shop", m.content));
            shopReplySeen = Math.max(shopReplySeen, staff.length);
            return true;
        } catch (err) {
            return false;
        }
    }

    async function startShopReplyStream(phone) {
        if (CHAT_CONTEXT !== 'customer_booking' || !BUSINESS_ID || !phone || shopReplyStream) return;
        const customerId = BUSINESS_ID + ":" + phone;
        shopReplyStream = "pending";
        if (!(await fetchShopReplies(customerId))) { shopReplyStream = null; return; } // hội thoại chưa lưu
        shopReplyStream = new EventSource("/api/portal/stream?customer_id=" + encodeURIComponent(customerId));
        shopReplyStream.onmessage = () => fetchShopReplies(customerId);
    }

    async function handleHumanAgentSubmit(msgVal, phoneVal) {
        appendMessage("user", msgVal);
        chatHistory.push({ role: "user", content: msgVal });
        chatMsgInput.value = "";
        chatMsgInput.disabled = true;
        if (chatSendBtn) chatSendBtn.disabled = true;

        try {
            await fetch("/api/cskh/chat/send", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ phone: phoneVal, content: msgVal }),
            });
        } catch (err) {
            console.log("Human agent message send deferred: ", err);
        }

        startHumanAgentStream(phoneVal);

        chatMsgInput.disabled = false;
        if (chatSendBtn) chatSendBtn.disabled = false;
        chatMsgInput.focus();
    }

    // 7. Offline/Fallback Logic Engine (Vietnamese Natural Response)
    function generateBitPawSalesReply(message, phone, industryCode, history = []) {
        const raw = message || '';
        const asksPrice = /giá|bao nhiêu|chi phí|phí|gói|bảng giá|mua/i.test(raw);
        const asksDemo = /demo|xem thử|dùng thử|trải nghiệm|test/i.test(raw);
        const asksFeature = /tính năng|làm được gì|có gì|quản lý gì|chức năng/i.test(raw);
        const asksSetup = /cài|triển khai|setup|bao lâu|hướng dẫn|đào tạo/i.test(raw);
        const asksQR = /qr|thanh toán|chuyển khoản|banking|auto/i.test(raw);

        let industry = getPageIndustry();
        const hasPhone = phone && /^(0|84)[3|5|7|8|9][0-9]{8}$/.test(phone.replace(/[\s.-]/g, ''));
        const phoneLine = hasPhone ? ' (Em đã ghi nhận Zalo ' + phone + ' của mình rồi ạ).' : '';

        let reply = "";

        if (asksPrice) {
            reply = 'Dạ anh / chị ơi, phần mềm BitPaw Software có nhiều gói linh hoạt tùy ngành nghề và quy mô của mình.' + phoneLine + ' Anh / chị chia sẻ thêm quy mô hiện tại (khoảng bao nhiêu nhân sự / bàn / thợ) để em tư vấn gói phù hợp nhé ạ!';
        } else if (asksDemo) {
            reply = `Dạ được sếp ơi! Em gửi sếp link demo thực tế ngay hoặc xếp lịch chuyên viên hướng dẫn sếp dùng thử 1 - 1 trên điện thoại / iPad.${phoneLine} Mình đang dùng thiết bị gì và muốn xem luồng quản lý POS hay chấm công nhân sự trước ạ ? `;
        } else if (asksQR) {
            reply = `Dạ, về thanh toán VietQR động, bản demo hiện tại của chúng ta là xác nhận thủ công để an toàn kiểm thử.Khi sếp triển khai thật, hệ thống sẽ kết nối API ngân hàng hoặc cổng thanh toán để tự động webhook khớp lệnh khớp hóa đơn và chốt đơn tự động ngay lập tức.${phoneLine} Sếp có muốn tích hợp QR tự động cho cửa hàng của mình không ạ ? `;
        } else if (asksFeature) {
            if (industry === 'nail') {
                reply = `Dạ với tiệm Nail, BitPaw giúp chia tua thợ công bằng, tính bill / tip nhanh gọn và tự nhắc lịch hẹn qua Zalo kéo khách cũ cực đỉnh.${phoneLine} Tiệm mình đang chia hoa hồng theo tỷ lệ % hay theo ca cố định ạ ? `;
            } else if (industry === 'spa') {
                reply = `Dạ Spa sẽ có quản lý buổi liệu trình còn lại của khách, phân phòng giường trống realtime và chấm công thợ hiện trường.${phoneLine} Cơ sở mình hiện có khoảng bao nhiêu giường ngủ và KTV ạ ? `;
            } else if (industry === 'fnb') {
                reply = `Dạ quán ăn / cafe sẽ dùng POS order, menu quét mã QR tại bàn gọi món, bếp KDS nhận món realtime và quản lý kho định lượng tránh hao hụt.${phoneLine} Quán mình đang có bao nhiêu bàn ăn ạ ? `;
            } else {
                reply = `Dạ BitPaw Software giúp sếp gom mọi hoạt động từ bán hàng POS, chấm công FaceID nhân sự, quản lý kho bãi cho đến CRM chăm sóc khách tự động về 1 lõi duy nhất.${phoneLine} Sếp đang quan tâm sâu nhất đến khâu nào ạ ? `;
            }
        } else if (asksSetup) {
            reply = `Dạ BitPaw hỗ trợ sếp setup trọn gói từ A - Z cực nhanh trong 1 - 3 ngày, có hướng dẫn thợ / nhân viên dùng di động cực kỳ trực quan.${phoneLine} Anh / chị để lại Zalo, bên em sẽ gửi kịch bản triển khai mẫu cho ngành của mình nhé!`;
        } else if (/chào|hello|hi|alo/i.test(raw)) {
            reply = `Dạ BitPaw AI xin chào Sếp! Em hỗ trợ tư vấn các module quản lý POS bán hàng, chấm công HRM và AI CSKH tự động.${phoneLine} Sếp đang kinh doanh ngành nghề gì để em tư vấn đúng kịch bản nhất ạ ? `;
        } else {
            if (industry === 'nail') {
                reply = `Dạ sếp ơi, BitPaw giúp tiệm Nail quản lý chia tua thợ tự động, tính bill thợ / hoa hồng rõ ràng và CRM tự nhắn Zalo kéo khách.${phoneLine} Tiệm mình hiện có bao nhiêu thợ ạ ? `;
            } else if (industry === 'spa') {
                reply = `Dạ với Spa, phần mềm giúp số hóa hồ sơ liệu trình khách, đặt lịch online và chia tua KTV tự động.${phoneLine} Spa mình hiện đang có khoảng bao nhiêu giường ạ ? `;
            } else if (industry === 'fnb') {
                reply = `Dạ với F & B, quán dùng menu QR gọi món tại bàn, màn hình bếp KDS tránh sót đơn và POS thanh toán VietQR động.${phoneLine} Quán mình đang có bao nhiêu bàn ăn ạ ? `;
            } else {
                reply = `Dạ BitPaw Software giúp sếp số hóa POS bán hàng, chấm công FaceID / GPS, tính lương tự động và CRM gửi tin nhắn Zalo chăm sóc khách.${phoneLine} Anh / chị cho em biết mình đang kinh doanh ngành nào để em tư vấn sâu hơn nhé!`;
            }
        }

        // Tối ưu hóa việc chèn Hotline: không lặp hotline mỗi câu
        const hasMentionedHotline = history.some(h => h.content && h.content.includes("8593 7410"));
        if (!hasMentionedHotline && (asksPrice || asksDemo || asksSetup || history.length <= 2)) {
            reply += ` Hoặc sếp liên hệ Hotline **🇦🇺 +61 3 8593 7410** / Zalo **0794.678.904** để em gửi kịch bản flow chi tiết ạ!`;
        }

        return reply;
    }

    // BUG THẬT NGHIÊM TRỌNG đã vá (audit bảo mật — Stored XSS, PoC thật xác nhận thực thi
    // được qua chuỗi tấn công /api/portal/messages -> appendMessage): text hiển thị (tin
    // khách tự gõ VÀ tin trả lời của staff/AI đọc lại từ server) trước đây chèn thẳng vào
    // innerHTML không escape. Mặc định escape MỌI text; chỉ 1 chỗ gọi cần giữ HTML thật
    // (dòng "SĐT Zalo: <strong>...</strong>") truyền isHtml=true SAU KHI đã tự escape riêng
    // từng phần dữ liệu động — xem lời gọi appendMessage("user", ..., true) bên dưới.
    function escapeHtml(str) {
        return String(str ?? "").replace(/[&<>]/g, function (m) {
            if (m === "&") return "&amp;";
            if (m === "<") return "&lt;";
            if (m === ">") return "&gt;";
            return m;
        });
    }

    // 8. Append Message Markup & Auto Scroll
    function appendMessage(sender, text, isHtml = false) {
        if (!msgContainer) return;
        let safeText = isHtml ? text : escapeHtml(text);
        // AI hay trả **chữ đậm** kiểu Markdown — trước đây khách thấy nguyên dấu ** trong khung chat.
        if (!isHtml && sender !== "user") safeText = safeText.replace(/\*\*([^*\n]+?)\*\*/g, "<strong>$1</strong>").replace(/\n/g, "<br>");
        if (sender === "shop") {
            const shopDiv = document.createElement("div");
            shopDiv.className = "flex gap-2.5 items-start mt-2";
            shopDiv.innerHTML = `
        <div class="w-6 h-6 rounded-full bg-pink-500/20 border border-pink-400/60 flex items-center justify-center shrink-0 text-[11px]">💅</div>
        <div class="chat-shop text-pink-100 p-3 rounded-2xl rounded-tl-sm text-xs sm:text-sm font-semibold leading-relaxed max-w-[82%] shadow-sm bg-pink-500/15 border border-pink-400/40">
            <div class="text-[10px] font-black uppercase tracking-wider text-pink-300 mb-1">${escapeHtml(BT.shop)}</div>
            ${safeText}
        </div>`;
            msgContainer.appendChild(shopDiv);
            msgContainer.scrollTop = msgContainer.scrollHeight;
            return;
        }
        const msgDiv = document.createElement("div");
        if (sender === "user") {
            msgDiv.className = "flex gap-2.5 items-start justify-end mt-2";
            msgDiv.innerHTML = `
        <div class="chat-user text-white p-3 rounded-2xl rounded-tr-sm text-xs sm:text-sm font-semibold leading-relaxed max-w-[82%] shadow-sm">
            ${safeText}
        </div>
        <div class="w-6 h-6 rounded-full bg-cyan-500/20 text-cyan-400 flex items-center justify-center shrink-0 text-[10px] font-bold border border-cyan-500/30">👤</div>
    `;
        } else {
            msgDiv.className = "flex gap-2.5 items-start mt-2";
            msgDiv.innerHTML = `
        <div class="w-6 h-6 rounded-full bg-[#08061a] border border-cyan-500/50 flex items-center justify-center shrink-0 mascot-glow overflow-hidden">
                    <img src="/static/cho1.jpg" class="w-full h-full object-cover">
                </div>
                <div class="chat-ai text-cyan-200 p-3 rounded-2xl rounded-tl-sm text-xs sm:text-sm font-semibold leading-relaxed max-w-[82%] shadow-sm">
                    ${safeText}
                </div>
    `;
        }
        msgContainer.appendChild(msgDiv);
        msgContainer.scrollTop = msgContainer.scrollHeight;
    }

    function showTypingIndicator() {
        if (!msgContainer) return;
        const indicator = document.createElement("div");
        indicator.id = "aiTypingBubble";
        indicator.className = "flex flex-col gap-1 items-start mt-2";
        indicator.innerHTML = `
        <span class="text-[9px] text-cyan-400 font-black ml-8 flex items-center gap-1"> <i class="fas fa-spinner fa-spin"></i> ${CHAT_CONTEXT === 'customer_booking' ? escapeHtml(BT.typing) : 'AI đang phân tích dữ liệu...'}</span>
<div class="flex gap-2.5 items-start">
    <div class="w-6 h-6 rounded-full bg-[#08061a] border border-cyan-500/50 flex items-center justify-center shrink-0 overflow-hidden"><img src="/static/cho1.jpg" class="w-full h-full object-cover"></div>
    <div class="typing-bubble bg-cyan-500/10 border border-cyan-500/20">
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
    </div>
</div>
        `;
        msgContainer.appendChild(indicator);
        msgContainer.scrollTop = msgContainer.scrollHeight;
    }

    function removeTypingIndicator() {
        const indicator = document.getElementById("aiTypingBubble");
        if (indicator) indicator.remove();
    }

    // Initialize Greeting
    appendMessage("ai", dna.greeting);

    // 9. Mascot Form Chat Submit Handler (DeepSeek V3 proxy & Supabase CRM lead capture)
    if (chatForm) {
        chatForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const msgVal = chatMsgInput.value.trim();
            if (!msgVal) return;

            const phoneVal = chatPhoneInput ? chatPhoneInput.value.trim() : "";

            if (chatMode === "human") {
                await handleHumanAgentSubmit(msgVal, phoneVal);
                return;
            }

            // BUG THẬT đã vá: trước đây chỉ nhận SĐT Việt Nam (0[35789]xxxxxxxx) — khách Úc 04xx / Mỹ
            // bị coi là "chưa có SĐT": hội thoại không lưu (tiệm không thấy khách nhắn trong /ai_bot) và AI
            // không đặt lịch được vì thiếu SĐT. Nhận mọi số 8-15 chữ số (có thể có + ở đầu).
            const cleanedPhone = phoneVal.replace(/[\s.()-]/g, '');
            const hasValidPhone = /^(0|84)[3|5|7|8|9][0-9]{8}$/.test(cleanedPhone) || /^\+?[0-9]{8,15}$/.test(cleanedPhone);

            const startTime = Date.now();

            // Disable input and button to prevent double submits / spam
            chatMsgInput.disabled = true;
            const sendBtn = chatForm.querySelector("button[type='submit']");
            if (sendBtn) {
                sendBtn.disabled = true;
                sendBtn.classList.add("opacity-50", "pointer-events-none");
            }

            if (hasValidPhone && !isLeadSubmitted) {
                appendMessage("user", CHAT_CONTEXT === 'customer_booking'
                    ? `${BT.phoneLabel}: <strong>${escapeHtml(phoneVal)}</strong><br>${BT.request}: ${escapeHtml(msgVal)}`
                    : `SĐT Zalo: <strong>${escapeHtml(phoneVal)}</strong><br>Yêu cầu: ${escapeHtml(msgVal)}`, true);
            } else {
                appendMessage("user", msgVal);
            }

            chatMsgInput.value = "";

            const finishSubmit = (reply) => {
                let finalReply = reply || "";
                // Trợ lý đặt lịch: KHÔNG cắt cụt (từng cắt ngang câu xác nhận lịch "...add the Signature Sp");
                // độ dài đã được giới hạn bằng max_tokens phía server.
                if (CHAT_CONTEXT !== 'customer_booking' && finalReply.length > 350) {
                    finalReply = finalReply.substring(0, 347) + "...";
                }

                removeTypingIndicator();
                if (finalReply) {
                    appendMessage("ai", finalReply);
                    chatHistory.push({ role: "assistant", content: finalReply });
                }
                if (userPhone) startShopReplyStream(userPhone);

                // Re-enable inputs
                chatMsgInput.disabled = false;
                if (sendBtn) {
                    sendBtn.disabled = false;
                    sendBtn.classList.remove("opacity-50", "pointer-events-none");
                }
                chatMsgInput.focus();
            };

            if (hasValidPhone && !isLeadSubmitted) {
                userPhone = cleanedPhone;
                const phoneDiv = document.getElementById("phone-container");
                if (phoneDiv) phoneDiv.style.display = "none";

                isLeadSubmitted = true;
                window.isLeadSubmittedGlobal = true; // sync globally

                chatHistory.push({ role: "user", content: msgVal }); // chỉ chữ khách gõ (trước đây "SĐT Zalo: ..., Yêu cầu: ..." kéo AI sang tiếng Việt)

                showTypingIndicator();

                // Send lead details to Supabase/SQLite CRM outbox asynchronously
                fetch("/api/cskh/request", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        name: `Khách hàng Vãng Lai (${dna.title})`,
                        phone: userPhone,
                        message: `[Mascot AI Chat Lead] ${msgVal}`
                    })
                }).catch(err => console.log("CRM Capture deferred: " + err));

                let aiReply = "";
                if (CHAT_CONTEXT !== 'customer_booking' && msgVal.toLowerCase().includes("tôi làm tiệm nail")) {
                    aiReply = "Dạ tiệm nail thì BitPaw hỗ trợ chia tua, ghi dịch vụ từng thợ và tính hoa hồng cuối ngày cho rõ ràng hơn. Tiệm mình đang có bao nhiêu thợ ạ?";
                } else {
                    try {
                        const response = await fetch("/api/ai/studio/generate", {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({
                                business_id: BUSINESS_ID,
                                industry: industryCode,
                                context: CHAT_CONTEXT,
                                customer_phone: userPhone,
                                client_now: localNowIso(),
                                customer_message: msgVal,
                                history: chatHistory.slice(-10),
                                userPrompt: CHAT_CONTEXT === 'customer_booking'
                                    ? `Khách hàng (SĐT ${userPhone}) vừa nhắn: "${msgVal}". Giúp khách chọn dịch vụ + thời gian rồi đặt lịch thật qua book_appointment. (Trả lời bằng ĐÚNG ngôn ngữ khách dùng trong tin nhắn, tự nhiên, dưới 350 ký tự).`
                                    // Gửi NGUYÊN câu khách gõ: trước đây bọc trong câu chỉ dẫn tiếng Việt ép "trả lời
                                    // tiếng Việt" -> khách hỏi tiếng Anh trên landing EN nhận câu trả lời tiếng Việt.
                                    // Persona server tự trả lời đúng ngôn ngữ khách (ai_sales_prompts.MASTER_CLOSER_PERSONA).
                                    : msgVal,
                                max_tokens: CHAT_CONTEXT === 'customer_booking' ? 320 : 220,
                                temperature: 0.75
                            })
                        });

                        const resData = await response.json();
                        if (resData.paused) {
                            // Tiệm đã nhận chat (AI tắt cho khách này): báo 1 lần là nhân viên sẽ trả lời ngay tại đây
                            aiReply = handoffNoticeShown ? "" : BT.handoff;
                            handoffNoticeShown = true;
                        } else if (resData.choices && resData.choices[0] && resData.choices[0].message) {
                            aiReply = resData.choices[0].message.content;
                        } else if (CHAT_CONTEXT === 'customer_booking') {
                            aiReply = BT.slow;
                        } else {
                            aiReply = generateBitPawSalesReply(msgVal, userPhone, industryCode, chatHistory);
                        }
                    } catch (error) {
                        console.log("AI generation deferred: ", error);
                        aiReply = CHAT_CONTEXT === 'customer_booking'
                            ? BT.slow
                            : (pageLangIsVi() ? `Dạ hệ thống đang hơi chậm. Anh/chị để lại số điện thoại, chuyên viên BitPaw sẽ gọi lại tư vấn ${dna.title} ngay ạ.` : `Sorry, we're a little slow right now. Leave your phone number and a BitPaw specialist will call you about ${dna.title} shortly.`);
                    }
                }

                if (CHAT_CONTEXT !== 'customer_booking') {
                    // Lượt đầu: xác nhận đã nhận SĐT + kênh liên hệ trực tiếp, 1 LẦN, đúng ngôn ngữ trang. Trước đây chèn
                    // "<br><br><span ...>Đã ghi nhận SĐT/Zalo của Sếp" — sau bản vá XSS (escape mọi chữ) khách thấy
                    // nguyên mã HTML thô; và câu hotline "Sếp kết nối nhanh..." trộn Việt-Anh dán vào mọi trang EN.
                    aiReply += pageLangIsVi()
                        ? `\n\n✓ Đã nhận số ${userPhone} — chuyên viên BitPaw sẽ liên hệ anh/chị. Gọi ngay: +61 3 8593 7410 · Zalo 0794 678 904`
                        : `\n\n✓ Got your number ${userPhone} — a BitPaw specialist will reach out. Call now: +61 3 8593 7410`;
                }

                const elapsed = Date.now() - startTime;
                const delay = Math.max(0, 800 - elapsed);

                setTimeout(() => {
                    finishSubmit(aiReply);
                }, delay);

            } else {
                // Secondary Chat turns or Chat without Phone
                chatHistory.push({ role: "user", content: msgVal });

                showTypingIndicator();

                // Đặc biệt: Nếu khách hỏi "Tôi làm tiệm nail" (hoặc quick reply tương ứng)
                let aiReply = "";
                if (CHAT_CONTEXT !== 'customer_booking' && msgVal.toLowerCase().includes("tôi làm tiệm nail")) {
                    aiReply = "Dạ tiệm nail thì BitPaw hỗ trợ chia tua, ghi dịch vụ từng thợ và tính hoa hồng cuối ngày cho rõ ràng hơn. Tiệm mình đang có bao nhiêu thợ ạ?";
                } else {
                    // Lịch sử hội thoại được gửi nguyên vẹn dưới dạng messages array thật (không
                    // còn ghép chuỗi văn bản thủ công) — backend tự nối vào prompt gọi LLM, nên
                    // AI luôn đọc được câu hỏi trước đó của chính nó, kể cả khi khách trả lời cụt
                    // lủn (vd: "10" sau câu hỏi "Bên mình có mấy thợ?").
                    try {
                        const response = await fetch("/api/ai/studio/generate", {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({
                                business_id: BUSINESS_ID,
                                industry: industryCode,
                                context: CHAT_CONTEXT,
                                customer_phone: userPhone,
                                client_now: localNowIso(),
                                customer_message: msgVal,
                                history: chatHistory.slice(-10),
                                userPrompt: msgVal,
                                max_tokens: CHAT_CONTEXT === 'customer_booking' ? 320 : 220,
                                temperature: 0.75
                            })
                        });

                        const resData = await response.json();
                        if (resData.paused) {
                            // Tiệm đã nhận chat (AI tắt cho khách này): báo 1 lần là nhân viên sẽ trả lời ngay tại đây
                            aiReply = handoffNoticeShown ? "" : BT.handoff;
                            handoffNoticeShown = true;
                        } else if (resData.choices && resData.choices[0] && resData.choices[0].message) {
                            aiReply = resData.choices[0].message.content;
                        } else if (CHAT_CONTEXT === 'customer_booking') {
                            aiReply = BT.slow2;
                        } else {
                            aiReply = generateBitPawSalesReply(msgVal, userPhone, industryCode, chatHistory);
                        }
                    } catch (error) {
                        console.log("AI generation deferred: ", error);
                        aiReply = CHAT_CONTEXT === 'customer_booking'
                            ? BT.slow2
                            : (pageLangIsVi() ? `Dạ hệ thống đang hơi chậm. Anh/chị để lại số điện thoại, chuyên viên BitPaw sẽ gọi lại tư vấn ${dna.title} ngay ạ.` : `Sorry, we're a little slow right now. Leave your phone number and a BitPaw specialist will call you about ${dna.title} shortly.`);
                    }
                }

                const elapsed = Date.now() - startTime;
                const delay = Math.max(0, 800 - elapsed);

                setTimeout(() => {
                    finishSubmit(aiReply);
                }, delay);
            }
        });
    }

    // 10. General Interactive Handlers
    const chatBox = document.getElementById("chatWidget");
    const mascotToggle = document.getElementById("mascot-toggle-btn");
    const closeChatBtn = document.getElementById("close-chat-btn");
    const backToTopBtn = document.getElementById("backToTop");

    // BUG THẬT đã phát hiện (test Playwright thật, đóng vai khách quét QR trên màn hình điện
    // thoại): nút mascot nổi (#bitpawCskhFloating) vẫn đứng NGUYÊN vị trí fixed bottom-right
    // ngay cả sau khi bảng chat đã mở — trên màn hình hẹp, nút đó đè thẳng lên nút "Gửi" của
    // khung chat, khách thật không cách nào bấm gửi tin nhắn được (chạm vào là bấm trúng nút
    // mascot, không phải nút gửi). Ẩn hẳn cụm nút nổi trong lúc bảng chat đang mở, hiện lại khi
    // đóng — không đổi vị trí/kích thước gì khác của bảng chat.
    if (mascotToggle) {
        mascotToggle.addEventListener("click", () => {
            if (chatBox) chatBox.classList.toggle("hidden-chat");
            if (contactWidget) contactWidget.style.display = chatBox && !chatBox.classList.contains("hidden-chat") ? "none" : "";
        });
    }

    if (closeChatBtn) {
        closeChatBtn.addEventListener("click", () => {
            if (chatBox) chatBox.classList.add("hidden-chat");
            if (contactWidget) contactWidget.style.display = "";
        });
    }

    window.toggleChat = function () {
        console.log('[CSKH] toggleChat called');
        const box = document.getElementById("chatWidget");
        if (box) {
            box.classList.toggle("hidden-chat");
            const floating = document.getElementById("bitpawCskhFloating");
            if (floating) floating.style.display = !box.classList.contains("hidden-chat") ? "none" : "";
        }
    };

    // Scroll to Top and Scroll tracking
    window.addEventListener("scroll", () => {
        if (backToTopBtn) {
            if (window.scrollY > 300) {
                backToTopBtn.classList.add("show");
            } else {
                backToTopBtn.classList.remove("show");
            }
        }
    });

    if (backToTopBtn) {
        backToTopBtn.addEventListener("click", () => {
            window.scrollTo({ top: 0, behavior: "smooth" });
        });
    }
});