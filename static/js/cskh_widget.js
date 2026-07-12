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
            
            .btn-zalo { background: #0068FF; }
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
                padding: 10px 14px;
                background: rgba(0, 0, 0, 0.35);
                border-top: 1px solid rgba(255, 255, 255, 0.06);
                scrollbar-width: none;
            }
            .quick-replies-container::-webkit-scrollbar {
                display: none;
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
    contactWidget.innerHTML = `
        <div class="relative group cursor-pointer mb-1" id="mascot-toggle-btn">
            <div class="absolute right-14 top-2 bg-[#08061a] border border-cyan-500/40 text-[#22d3ee] text-[11px] font-bold py-1.5 px-3 rounded-lg rounded-tr-none w-max shadow-lg opacity-0 group-hover:opacity-100 transition-all duration-300 transform translate-x-2 group-hover:translate-x-0 pointer-events-none z-50">
                Sếp cần hỗ trợ?<br>Gọi em ngay!
            </div>
            <div class="w-14 h-14 bg-[#08061a] border-2 border-cyan-400 rounded-full flex items-center justify-center shadow-[0_0_12px_rgba(6,182,212,0.5)] group-hover:scale-110 transition-transform overflow-hidden mascot-glow">
                <img src="/static/cho1.jpg" onerror="this.onerror=null; this.src='https://cdn-icons-png.flaticon.com/512/6182/6182181.png';" class="w-full h-full object-cover">
            </div>
        </div>

        <button id="backToTop" class="contact-btn bg-gray-800 border border-gray-600 text-xs" data-tooltip="Lên đầu">
            <i class="fas fa-chevron-up"></i>
        </button>
        <a href="mailto:hodinhsang30052003@gmail.com" class="contact-btn btn-mail" data-tooltip="Email">
            <i class="fas fa-envelope"></i>
        </a>
        <a href="https://zalo.me/0794678904" target="_blank" class="contact-btn btn-zalo" data-tooltip="Zalo Kỹ Thuật">
            <span class="font-black text-[9px] tracking-tighter">Zalo</span>
        </a>
        <a href="https://www.facebook.com/chuyhieuhong" target="_blank" class="contact-btn btn-mess" data-tooltip="Messenger">
            <i class="fab fa-facebook-messenger"></i>
        </a>
        <a href="tel:0794678904" class="contact-btn btn-call" data-tooltip="Hotline 24/7">
            <i class="fas fa-phone-alt"></i>
        </a>
    `;
    document.body.appendChild(contactWidget);

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
            <div class="p-4 flex-1 overflow-y-auto flex flex-col gap-3 modal-scroll" id="chat-messages-container">
                </div>
            
            <div class="quick-replies-container" id="quick-replies-container">
                <button type="button" onclick="handleQuickReply('Tôi làm tiệm nail')" class="quick-reply-chip">Tôi làm tiệm nail</button>
                <button type="button" onclick="handleQuickReply('Tôi mở quán cafe')" class="quick-reply-chip">Tôi mở quán cafe</button>
                <button type="button" onclick="handleQuickReply('Tôi cần QR Order')" class="quick-reply-chip">Tôi cần QR Order</button>
                <button type="button" onclick="handleQuickReply('Tôi cần tính lương')" class="quick-reply-chip">Tôi cần tính lương</button>
                <button type="button" onclick="handleQuickReply('Tôi muốn báo giá')" class="quick-reply-chip">Tôi muốn báo giá</button>
            </div>
            
            <div class="p-3 border-t border-white/10 bg-black/40">
                <form id="mascot-chat-form" class="flex flex-col gap-2">
                    <div id="phone-container">
                        <input type="text" id="chatPhone" placeholder="SĐT / Zalo của Sếp (Không bắt buộc)..." class="w-full bg-black/60 border border-white/10 rounded-xl px-4 py-2.5 text-xs text-white focus:outline-none focus:border-cyan-400 placeholder-gray-500">
                    </div>
                    <div class="flex items-center gap-2 bg-black/60 border border-white/10 rounded-xl pr-2 focus-within:border-cyan-400 transition">
                        <input type="text" id="chatMsg" placeholder="Nhập nhu cầu tư vấn..." required class="w-full bg-transparent px-4 py-2.5 text-xs text-white focus:outline-none placeholder-gray-500">
                        <button type="submit" class="bg-cyan-500 hover:bg-cyan-400 text-black w-8 h-8 rounded-lg font-bold transition flex items-center justify-center shrink-0"><i class="fas fa-paper-plane text-xs"></i></button>
                    </div>
                </form>
            </div>
        </div>
    `;
    document.body.appendChild(chatWidget);

    // 4. Industry Config and Prompts (DNA/Scenario matching)
    const industryData = {
        nail: {
            title: "Nails & Salon",
            greeting: "Chào anh/chị! Em là trợ lý BitPaw OS. Em giúp tiệm Nail quản lý xếp tua thợ tự động công bằng, chia hoa hồng kép rõ ràng và chốt bill cực nhanh. Tiệm mình hiện tại có bao nhiêu thợ và đang tính hoa hồng theo % hay lương cứng ạ?",
            prompt: "Bạn là BitPaw AI Tư Vấn, một nhân viên tư vấn phần mềm thật, không phải chatbot văn mẫu. Nói tiếng Việt tự nhiên, ngắn, có cảm xúc vừa phải. Không lặp “Chào bạn”, “Tuyệt vời”, “Dạ” ở mọi câu. Không tự hứa đã gửi link/bảng giá nếu hệ thống chưa thực hiện hành động đó. Không tự báo giá cụ thể nếu chưa có bảng giá chính thức trong dữ liệu. Nếu khách hỏi giá, hãy nói: “Chi phí sẽ tùy module và quy mô. Em cần chốt nhu cầu chính trước để báo gói phù hợp.” Luôn nhớ ngữ cảnh trong cuộc trò chuyện hiện tại. Khi khách đã cung cấp ngành/quy mô, hãy tóm tắt lại bằng 1 câu rồi đề xuất bước tiếp theo. Trả lời tối đa 2–4 câu, dưới 350 ký tự. Hỏi lại chỉ 1 câu ngắn, đúng trọng tâm. Không spam hotline."
        },
        spa: {
            title: "Spa & Beauty",
            greeting: "Dạ chào Sếp! BitPaw giúp số hóa liệu trình Spa, đặt lịch online tự động, sơ đồ giường trống realtime và hoa hồng KTV minh bạch. Cơ sở mình đang có mấy giường và KTV rồi ạ?",
            prompt: "Bạn là BitPaw AI Tư Vấn chuyên Spa & Beauty. Nói tiếng Việt tự nhiên như người thật, ngắn, có cảm xúc vừa phải. Không lặp “Chào bạn”, “Tuyệt vời”, “Dạ”. Không tự hứa đã gửi link/bảng giá. Không tự báo giá cụ thể. Nếu hỏi giá, nói: “Chi phí sẽ tùy module và quy mô. Em cần chốt nhu cầu chính trước để báo gói phù hợp.” Trả lời tối đa 2–4 câu, dưới 350 ký tự. Hỏi lại chỉ 1 câu ngắn, đúng trọng tâm. Không spam hotline."
        },
        fnb: {
            title: "Nhà hàng & Cafe",
            greeting: "Dạ chào anh/chị! Giải pháp F&B bên em hỗ trợ khách quét QR Order tại bàn gọi món trực tiếp, màn hình bếp KDS realtime và POS VietQR động. Quán mình khoảng bao nhiêu bàn và có cần in bếp tự động không ạ?",
            prompt: "Bạn là BitPaw AI Tư Vấn chuyên F&B. Nói tiếng Việt tự nhiên như người thật, ngắn, có cảm xúc vừa phải. Không lặp “Chào bạn”, “Tuyệt vời”, “Dạ”. Không tự hứa đã gửi link/bảng giá. Không tự báo giá cụ thể. Nếu hỏi giá, nói: “Chi phí sẽ tùy module và quy mô. Em cần chốt nhu cầu chính trước để báo gói phù hợp.” Trả lời tối đa 2–4 câu, dưới 350 ký tự. Hỏi lại chỉ 1 câu ngắn, đúng trọng tâm. Không spam hotline."
        },
        hotel: {
            title: "Khách Sạn & Homestay",
            greeting: "Dạ chào Sếp! BitPaw Hotel giúp sếp có ngay sơ đồ buồng phòng trống/bận realtime, liên kết khóa thẻ từ và tính bill phụ cực nhanh. Khách sạn mình hiện có bao nhiêu phòng và có dùng khóa thẻ từ không ạ?",
            prompt: "Bạn là BitPaw AI Tư Vấn chuyên Khách sạn/Homestay. Nói tiếng Việt tự nhiên, ngắn, có cảm xúc vừa phải. Không lặp “Chào bạn”, “Tuyệt vời”, “Dạ”. Không tự hứa đã gửi link/bảng giá. Không tự báo giá cụ thể. Nếu hỏi giá, nói: “Chi phí sẽ tùy module và quy mô. Em cần chốt nhu cầu chính trước để báo gói phù hợp.” Trả lời tối đa 2–4 câu, dưới 350 ký tự. Hỏi lại chỉ 1 câu ngắn, đúng trọng tâm. Không spam hotline."
        },
        karaoke: {
            title: "Karaoke & Bida",
            greeting: "Chào anh/chị! BitPaw giúp tự động tính tiền giờ bida/karaoke chính xác theo block phút lẻ, sơ đồ bàn bận/trống realtime và order đồ uống tại phòng. Quán mình đang có bao nhiêu bàn hoặc phòng hát ạ?",
            prompt: "Bạn là BitPaw AI Tư Vấn chuyên Karaoke & Bida. Nói tiếng Việt tự nhiên, ngắn, có cảm xúc vừa phải. Không lặp “Chào bạn”, “Tuyệt vời”, “Dạ”. Không tự hứa đã gửi link/bảng giá. Không tự báo giá cụ thể. Nếu hỏi giá, nói: “Chi phí sẽ tùy module và quy mô. Em cần chốt nhu cầu chính trước để báo gói phù hợp.” Trả lời tối đa 2–4 câu, dưới 350 ký tự. Hỏi lại chỉ 1 câu ngắn, đúng trọng tâm. Không spam hotline."
        },
        office: {
            title: "Văn Phòng / HRM",
            greeting: "Chào Sếp! BitPaw Office giúp nhân viên chấm công FaceID/GPS chống fake, duyệt đơn online và tính bảng lương tự động 1-click. Doanh nghiệp mình đang có khoảng bao nhiêu nhân sự rồi ạ?",
            prompt: "Bạn là BitPaw AI Tư Vấn chuyên Văn phòng số/HRM. Nói tiếng Việt tự nhiên, ngắn, có cảm xúc vừa phải. Không lặp “Chào bạn”, “Tuyệt vời”, “Dạ”. Không tự hứa đã gửi link/bảng giá. Không tự báo giá cụ thể. Nếu hỏi giá, nói: “Chi phí sẽ tùy module và quy mô. Em cần chốt nhu cầu chính trước để báo gói phù hợp.” Trả lời tối đa 2–4 câu, dưới 350 ký tự. Hỏi lại chỉ 1 câu ngắn, đúng trọng tâm. Không spam hotline."
        },
        retail: {
            title: "Cửa Hàng Bán Lẻ",
            greeting: "Dạ chào Sếp! BitPaw giúp quét mã vạch bán hàng siêu tốc, trừ kho realtime và đồng bộ tồn kho đa sàn Shopee/Tiktok. Shop mình đang kinh doanh mặt hàng gì và có bán online không ạ?",
            prompt: "Bạn là BitPaw AI Tư Vấn chuyên Bán lẻ. Nói tiếng Việt tự nhiên, ngắn, có cảm xúc vừa phải. Không lặp “Chào bạn”, “Tuyệt vời”, “Dạ”. Không tự hứa đã gửi link/bảng giá. Không tự báo giá cụ thể. Nếu hỏi giá, nói: “Chi phí sẽ tùy module và quy mô. Em cần chốt nhu cầu chính trước để báo gói phù hợp.” Trả lời tối đa 2–4 câu, dưới 350 ký tự. Hỏi lại chỉ 1 câu ngắn, đúng trọng tâm. Không spam hotline."
        },
        production: {
            title: "Sản Xuất & Nhà Xưởng",
            greeting: "Dạ chào anh/chị! BitPaw MES giúp công nhân báo cáo sản lượng di động, định mức vật tư (BOM) và chấm công ca kíp nhà xưởng trực quan. Xưởng mình chuyên may mặc, cơ khí hay ngành nào ạ?",
            prompt: "Bạn là BitPaw AI Tư Vấn chuyên MES/Sản xuất. Nói tiếng Việt tự nhiên, ngắn, có cảm xúc vừa phải. Không lặp “Chào bạn”, “Tuyệt vời”, “Dạ”. Không tự hứa đã gửi link/bảng giá. Không tự báo giá cụ thể. Nếu hỏi giá, nói: “Chi phí sẽ tùy module và quy mô. Em cần chốt nhu cầu chính trước để báo gói phù hợp.” Trả lời tối đa 2–4 câu, dưới 350 ký tự. Hỏi lại chỉ 1 câu ngắn, đúng trọng tâm. Không spam hotline."
        },
        technical: {
            title: "Dịch Vụ Kỹ Thuật",
            greeting: "Dạ chào Sếp! BitPaw giúp gán ticket sửa chữa tự động, giám sát định vị thợ hiện trường qua GPS và ký nghiệm thu số không giấy. Đội mình hiện có bao nhiêu thợ đang chạy ngoài hiện trường ạ?",
            prompt: "Bạn là BitPaw AI Tư Vấn chuyên thợ kỹ thuật di động. Nói tiếng Việt tự nhiên, ngắn, có cảm xúc vừa phải. Không lặp “Chào bạn”, “Tuyệt vời”, “Dạ”. Không tự hứa đã gửi link/bảng giá. Không tự báo giá cụ thể. Nếu hỏi giá, nói: “Chi phí sẽ tùy module và quy mô. Em cần chốt nhu cầu chính trước để báo gói phù hợp.” Trả lời tối đa 2–4 câu, dưới 350 ký tự. Hỏi lại chỉ 1 câu ngắn, đúng trọng tâm. Không spam hotline."
        },
        hr: {
            title: "Quản Trị Nhân Sự",
            greeting: "Chào anh/chị! Trục HRM BitPaw giúp sếp quản lý ca kíp phức tạp, chấm công FaceID và tính lương đa biến số 1-click. Doanh nghiệp mình đang gặp vướng mắc nhất ở khâu chấm công hay tính lương ạ?",
            prompt: "Bạn là chuyên viên tư vấn HRM của BitPaw OS. Trò chuyện tự nhiên, ngắn (2-5 câu, dưới 450 ký tự). Tư vấn: FaceID chấm công, OT phép online, ma trận tính lương đa biến số 1-click. Kết thúc bằng 1 câu hỏi ngắn tự nhiên về chấm công/lương. Tuyệt đối không tự lặp hotline."
        },
        general: {
            title: "BitPaw OS",
            greeting: "Chào sếp! Em là BitPaw AI Tư Vấn. Hệ sinh thái BitPaw OS giúp sếp số hóa vận hành từ POS bán hàng, nhân sự chấm công FaceID, tính lương 1-click đến AI CSKH đa kênh. Sếp đang cần tối ưu khâu nào nhất cho doanh nghiệp mình ạ?",
            prompt: "Bạn là trợ lý tư vấn thân thiện, thông minh của BitPaw OS. Trò chuyện tiếng Việt vô cùng tự nhiên như người thật, ngắn gọn (2-5 câu, dưới 450 ký tự). Giới thiệu hệ sinh thái B2B SaaS BitPaw (POS đa ngành, Order QR, HRM chấm công, lương, CRM, CSKH). Luôn hỏi lại một câu ngắn tự nhiên để hiểu ngành/quy mô của khách. Tuyệt đối không nhồi nhét hotline ở mọi câu trả lời."
        }
    };

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
    const dna = industryData[safeIndustry] || industryData.general;

    // 5. Initialize State Variables and DOM References
    const chatForm = document.getElementById("mascot-chat-form");
    const chatMsgInput = document.getElementById("chatMsg");
    const chatPhoneInput = document.getElementById("chatPhone");
    const msgContainer = document.getElementById("chat-messages-container");
    const pageContext = document.title || "BitPaw OS";

    let isLeadSubmitted = false;
    let userPhone = "";
    let chatHistory = [];

    // Sync state globally for quick reply handlers
    window.isLeadSubmittedGlobal = false;

    // 6. Global Quick Reply Chip Click Handler
    window.handleQuickReply = function (text) {
        const chatMsgInput = document.getElementById("chatMsg");
        if (chatMsgInput) {
            chatMsgInput.value = text;
        }
        const chatForm = document.getElementById("mascot-chat-form");
        if (chatForm) {
            chatForm.dispatchEvent(new Event('submit'));
        }
    };

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
            reply = 'Dạ anh / chị ơi, phần mềm BitPaw OS có nhiều gói linh hoạt tùy ngành nghề và quy mô của mình.' + phoneLine + ' Anh / chị chia sẻ thêm quy mô hiện tại (khoảng bao nhiêu nhân sự / bàn / thợ) để em tư vấn gói phù hợp nhé ạ!';
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
                reply = `Dạ BitPaw OS giúp sếp gom mọi hoạt động từ bán hàng POS, chấm công FaceID nhân sự, quản lý kho bãi cho đến CRM chăm sóc khách tự động về 1 lõi duy nhất.${phoneLine} Sếp đang quan tâm sâu nhất đến khâu nào ạ ? `;
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
                reply = `Dạ BitPaw OS giúp sếp số hóa POS bán hàng, chấm công FaceID / GPS, tính lương tự động và CRM gửi tin nhắn Zalo chăm sóc khách.${phoneLine} Anh / chị cho em biết mình đang kinh doanh ngành nào để em tư vấn sâu hơn nhé!`;
            }
        }

        // Tối ưu hóa việc chèn Hotline: không lặp hotline mỗi câu
        const hasMentionedHotline = history.some(h => h.content && h.content.includes("0794.678.904"));
        if (!hasMentionedHotline && (asksPrice || asksDemo || asksSetup || history.length <= 2)) {
            reply += ` Hoặc sếp liên hệ Hotline / Zalo **0794.678.904 ** để em gửi kịch bản flow chi tiết ạ!`;
        }

        return reply;
    }

    // 8. Append Message Markup & Auto Scroll
    function appendMessage(sender, text) {
        if (!msgContainer) return;
        const msgDiv = document.createElement("div");
        if (sender === "user") {
            msgDiv.className = "flex gap-2.5 items-start justify-end mt-2";
            msgDiv.innerHTML = `
        <div class="chat-user text-white p-3 rounded-2xl rounded-tr-sm text-xs sm:text-sm font-semibold leading-relaxed max-w-[82%] shadow-sm">
            ${text}
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
                    ${text}
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
        <span class="text-[9px] text-cyan-400 font-black ml-8 flex items-center gap-1"> <i class="fas fa-spinner fa-spin"></i> AI đang phân tích dữ liệu...</span>
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
            const cleanedPhone = phoneVal.replace(/[\s.-]/g, '');
            const hasValidPhone = /^(0|84)[3|5|7|8|9][0-9]{8}$/.test(cleanedPhone);

            const startTime = Date.now();

            // Disable input and button to prevent double submits / spam
            chatMsgInput.disabled = true;
            const sendBtn = chatForm.querySelector("button[type='submit']");
            if (sendBtn) {
                sendBtn.disabled = true;
                sendBtn.classList.add("opacity-50", "pointer-events-none");
            }

            if (hasValidPhone && !isLeadSubmitted) {
                appendMessage("user", `SĐT Zalo: <strong>${phoneVal}</strong><br>Yêu cầu: ${msgVal}`);
            } else {
                appendMessage("user", msgVal);
            }

            chatMsgInput.value = "";

            const finishSubmit = (reply) => {
                let finalReply = reply;
                if (finalReply.length > 350) {
                    finalReply = finalReply.substring(0, 347) + "...";
                }

                removeTypingIndicator();
                appendMessage("ai", finalReply);
                chatHistory.push({ role: "assistant", content: finalReply });

                // Re-enable inputs
                chatMsgInput.disabled = false;
                if (sendBtn) {
                    sendBtn.disabled = false;
                    sendBtn.classList.remove("opacity-50", "pointer-events-none");
                }
                chatMsgInput.focus();
            };

            if (hasValidPhone && !isLeadSubmitted) {
                userPhone = phoneVal;
                const phoneDiv = document.getElementById("phone-container");
                if (phoneDiv) phoneDiv.style.display = "none";

                isLeadSubmitted = true;
                window.isLeadSubmittedGlobal = true; // sync globally

                chatHistory.push({ role: "user", content: `SĐT Zalo: ${userPhone}, Yêu cầu: ${msgVal}` });

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
                if (msgVal.toLowerCase().includes("tôi làm tiệm nail")) {
                    aiReply = "Dạ tiệm nail thì BitPaw hỗ trợ chia tua, ghi dịch vụ từng thợ và tính hoa hồng cuối ngày cho rõ ràng hơn. Tiệm mình đang có bao nhiêu thợ ạ?";
                } else {
                    try {
                        const response = await fetch("/api/ai/studio/generate", {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({
                                systemPrompt: dna.prompt,
                                userPrompt: `Khách hàng sử dụng SĐT Zalo ${userPhone} vừa yêu cầu tư vấn: "${msgVal}". Bạn hãy trả lời tư vấn ngắn gọn, chốt sale nhẹ nhàng và hỏi lại 1 câu. (Chú ý: trả lời tiếng Việt tự nhiên, dưới 350 ký tự, KHÔNG lặp lại hotline nếu không cần thiết).`,
                                max_tokens: 220,
                                temperature: 0.7
                            })
                        });

                        const resData = await response.json();
                        if (resData.choices && resData.choices[0] && resData.choices[0].message && !resData.fallback) {
                            aiReply = resData.choices[0].message.content;
                        } else {
                            aiReply = generateBitPawSalesReply(msgVal, userPhone, industryCode, chatHistory);
                        }
                    } catch (error) {
                        console.log("AI generation deferred: ", error);
                        aiReply = "Em đang hơi chậm chút, nhưng em vẫn ghi nhận nhu cầu của anh/chị. Mình đang ưu tiên setup phần nào trước ạ?";
                    }
                }

                // Tối ưu hóa chèn hotline ở câu chào đầu chốt lead nếu chưa có
                if (!aiReply.includes("0794") && !aiReply.includes("chậm chút")) {
                    aiReply += ` Sếp kết nối nhanh Hotline/Zalo **0794.678.904** để em gửi kịch bản flow chi tiết nhé!`;
                }

                if (userPhone && !aiReply.includes(userPhone) && !aiReply.includes("chậm chút")) {
                    aiReply += `<br><br><span class="text-[11px] text-cyan-400 font-bold"><i class="fas fa-check-circle mr-1"></i> Đã ghi nhận SĐT/Zalo của Sếp: ${userPhone}</span>`;
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
                if (msgVal.toLowerCase().includes("tôi làm tiệm nail")) {
                    aiReply = "Dạ tiệm nail thì BitPaw hỗ trợ chia tua, ghi dịch vụ từng thợ và tính hoa hồng cuối ngày cho rõ ràng hơn. Tiệm mình đang có bao nhiêu thợ ạ?";
                } else {
                    // Build rich rolling chat history context (last 6 messages)
                    const rollingContext = `Ngữ cảnh trang: ${pageContext}

Thông tin khách:
- SĐT/Zalo: ${userPhone || "Chưa cung cấp"}

Lịch sử hội thoại gần nhất:
${chatHistory.slice(-6).map(item => `${item.role === "user" ? "Khách" : "BitPaw AI"}: ${item.content}`).join("\n")}

Tin nhắn mới nhất của khách:
${msgVal}

Hãy trả lời như một chuyên viên tư vấn BitPaw thật:
- Không lặp lại một câu cố định.
- Trả lời tiếng Việt vô cùng tự nhiên như người thật, ngắn gọn (2-5 câu, dưới 350 ký tự).
- Kết thúc bằng một câu hỏi tiếp tự nhiên.
- Chỉ chèn hotline 0794.678.904 khi thực sự cần thiết và chưa xuất hiện trong lịch sử chat.
- Tuyệt đối không tự ý thêm câu "Đã ghi nhận SĐT/Zalo..." nếu khách chưa nhập SĐT hợp lệ.`;

                    try {
                        const response = await fetch("/api/ai/studio/generate", {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({
                                systemPrompt: dna.prompt,
                                userPrompt: rollingContext,
                                max_tokens: 220,
                                temperature: 0.7
                            })
                        });

                        const resData = await response.json();
                        if (resData.choices && resData.choices[0] && resData.choices[0].message && !resData.fallback) {
                            aiReply = resData.choices[0].message.content;
                        } else {
                            aiReply = generateBitPawSalesReply(msgVal, userPhone, industryCode, chatHistory);
                        }
                    } catch (error) {
                        console.log("AI generation deferred: ", error);
                        aiReply = "Em đang hơi chậm chút, nhưng em vẫn ghi nhận nhu cầu của anh/chị. Mình đang ưu tiên setup phần nào trước ạ?";
                    }
                }

                // Chỉ append dòng "Đã ghi nhận..." nếu SĐT hợp lệ và chưa từng thông báo
                const hasMentionedSuccess = chatHistory.some(h => h.content && h.content.includes("Đã ghi nhận SĐT"));
                if (hasValidPhone && !hasMentionedSuccess && !aiReply.includes("chậm chút")) {
                    aiReply += `<br><br><span class="text-[11px] text-cyan-400 font-bold"><i class="fas fa-check-circle mr-1"></i> Đã ghi nhận SĐT/Zalo của Sếp: ${phoneVal}</span>`;
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

    if (mascotToggle) {
        mascotToggle.addEventListener("click", () => {
            if (chatBox) chatBox.classList.toggle("hidden-chat");
        });
    }

    if (closeChatBtn) {
        closeChatBtn.addEventListener("click", () => {
            if (chatBox) chatBox.classList.add("hidden-chat");
        });
    }

    window.toggleChat = function () {
        console.log('[CSKH] toggleChat called');
        const box = document.getElementById("chatWidget");
        if (box) {
            box.classList.toggle("hidden-chat");
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