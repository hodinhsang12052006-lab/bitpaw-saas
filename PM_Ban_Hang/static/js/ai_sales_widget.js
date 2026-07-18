// -*- coding: utf-8 -*-
/**
 * BitPaw Futuristic AI Sales Assistant Chat Widget
 * Pure JavaScript rule-based simulation engine for high-conversion real customer tests.
 * Fully supports Vietnamese, English, and Chinese languages consistently.
 */

document.addEventListener("DOMContentLoaded", function() {
    const chatWidget = document.getElementById("chatWidget");
    if (!chatWidget) return;

    // Translation Directory for DOM Walker
    const translationDirectory = {
        // Navigation / Headers
        "hệ sinh thái": { en: "Ecosystem", zh: "生态系统" },
        "hệ sinh thái <i class=\"fas fa-chevron-down text-[10px]\"></i>": { en: "Ecosystem <i class=\"fas fa-chevron-down text-[10px]\"></i>", zh: "生态系统 <i class=\"fas fa-chevron-down text-[10px]\"></i>" },
        "nỗi đau ngành": { en: "Industry Pain Points", zh: "行业痛点" },
        "giải pháp": { en: "Solutions", zh: "解决方案" },
        "giải pháp ngành": { en: "Industry Solutions", zh: "行业解决方案" },
        "tính năng": { en: "Features", zh: "功能特性" },
        "quy trình": { en: "Workflow", zh: "业务流程" },
        "quy trình hoạt động": { en: "Operational Workflow", zh: "业务流程" },
        "trợ lý ai": { en: "AI Assistant", zh: "AI助手" },
        "bảng giá": { en: "Pricing", zh: "价目表" },
        "báo giá": { en: "Get Quote", zh: "获取报价" },
        "đăng nhập": { en: "Login", zh: "登录" },
        "đăng nhập quản trị": { en: "Admin Login", zh: "管理员登录" },
        "mua ngay": { en: "Buy Now", zh: "立即购买" },
        "công nghệ lõi": { en: "Core Tech", zh: "核心技术" },
        "ngôn ngữ:": { en: "Language:", zh: "语言:" },
        "menu": { en: "Menu", zh: "菜单" },
        "chuyên gia tư vấn": { en: "Consulting Expert", zh: "咨询专员" },
        "trực tuyến 24/7": { en: "Online 24/7", zh: "在线 24/7" },
        "lên đầu trang": { en: "Back to top", zh: "回到顶部" },
        "gửi email": { en: "Send Email", zh: "发送邮件" },
        "chat zalo": { en: "Zalo Chat", zh: "Zalo咨询" },
        "chat messenger": { en: "Messenger Chat", zh: "Messenger咨询" },
        "gọi hotline": { en: "Call Hotline", zh: "拨打热线" },

        // Tooltip
        "cần tư vấn ngay?": { en: "Need help?", zh: "需要咨询吗？" },
        "gọi hotline em nhé!": { en: "Call our Hotline!", zh: "请拨打我们的热线！" },
        "sếp cần hỗ trợ?": { en: "Need help boss?", zh: "老板需要支持？" },
        "gọi em ngay!": { en: "Call me now!", zh: "请联系我！" },

        // Hero and Headers
        "b2b saas empire v3.0": { en: "B2B SaaS Empire V3.0", zh: "B2B SaaS 帝国 V3.0" },
        "tự động hóa": { en: "Automation", zh: "业务自动化" },
        "hệ sinh thái phần mềm all-in-one: quản trị nhân sự, smart pos đa ngành, bán hàng omnichannel và agency marketing ai. chấm dứt thất thoát, giải phóng lãnh đạo.": {
            en: "ALL-IN-ONE SaaS Ecosystem: HR Management, Multi-industry Smart POS, Omnichannel Sales, and AI Marketing Agency. Stop losses, free the Leaders.",
            zh: "一体化 SaaS 生态系统：人力资源管理、多行业智能 POS、多渠道销售以及 AI 营销机构。彻底减少流失，解放管理者。"
        },
        "bắt đầu chuyển đổi số": { en: "Start Digital Transformation", zh: "开始数字化转型" },
        "khám phá hệ sinh thái": { en: "Explore Ecosystem", zh: "探索生态系统" },

        // Industry Headings and Heros
        "số hóa liệu trình": { en: "Digitalize Treatments", zh: "疗程数字化" },
        "tăng tưởng doanh thu spa thẩm mỹ": { en: "Boost Spa & Clinic Revenue", zh: "提升美容会所营收" },
        "đập tan lỗ hổng thất thoát liệu trình. giải pháp quản lý spa/clinic tối tân: số hóa 100% thẻ liệu trình bảo mật faceid/otp, chia tua ktv tự động công bằng, quản lý giường bận trống real-time.": {
            en: "Eradicate treatment leakage completely. Ultimate Spa/Clinic management solution: 100% digital treatment cards secured by FaceID/OTP, automated fair therapist rotations, and real-time room/bed tracking.",
            zh: "彻底杜绝疗程管理流失漏洞。尖端水疗美容会所管理系统：支持人脸识别/验证码数字疗程卡、技师轮班公平自动分配、实时房态及床位追踪。"
        },
        "dùng thử miễn phí": { en: "Free Trial", zh: "免费试用" },
        "dùng thử miễn phí 30 ngày": { en: "30-Day Free Trial", zh: "30天免费试用" },
        "nhận tư vấn 1-1": { en: "1-on-1 Consultation", zh: "一对一咨询" },
        "đăng ký ngay": { en: "Register Now", zh: "立即注册" },

        // Pain Points
        "thách thức ngành": { en: "Industry Challenges", zh: "行业挑战" },
        "các điểm thất thoát rò rỉ": { en: "Key Leakages and Losses", zh: "关键流失与损耗漏洞" },
        "do vận hành thủ công": { en: "From Manual Operations", zh: "由于手工传统管理模式" },
        "đừng để những lỗ hổng quản trị âm thầm bào mòn lợi nhuận và uy tín thương hiệu của sếp mỗi ngày.": {
            en: "Don't let management loopholes silently erode your profit and brand reputation every day.",
            zh: "不要让管理漏洞每天默默吞噬您的利润和品牌声誉。"
        },
        "trôi thẻ liệu trình giấy": { en: "Paper Treatment Cards Lost", zh: "纸质疗程卡丢失损坏" },
        "thẻ giấy của khách dễ bị ướt, làm rách, làm mất. hoặc nhân viên tự ý ghi khống số buổi điều trị thực tế để gian lận, cự cãi với khách hàng.": {
            en: "Paper cards get wet, torn, or lost. Staff might fraudulently record extra sessions, leading to arguments with clients.",
            zh: "客户的纸质卡片极易受潮、破损或丢失。或者员工私自虚报实际治疗次数进行作弊，引发与客户的纠纷。"
        },
        "tranh tua thợ ktv khó kiểm soát": { en: "Uncontrolled Therapist Rotations", zh: "技师排班轮值难以控制" },
        "kế toán xếp ca ktv không công bằng, ktv ưu tiên nhận các ca vip, ca làm trắng da mặt để nhận hoa hồng cao hơn dẫn đến bất hòa nội bộ.": {
            en: "Unfair shifting leads to internal conflict. Therapists prioritize high-commission VIP or premium skin treatment sessions.",
            zh: "前台排班不公，技师争抢高提成的VIP或美白面部疗程，导致内部员工不和。"
        },
        "sơ đồ giường trống lộn xộn": { en: "Messy Bed Layout Management", zh: "床位状态管理混乱" },
        "lễ tân không nắm được tình trạng giường vip bận/trống khiến khách hàng đến dồn ca vào giờ cao điểm, phải đợi lâu bực bội ra về.": {
            en: "Receptionists can't track VIP bed availability, causing customer bottlenecks at peak hours and angry walkouts due to long waits.",
            zh: "前台无法掌握VIP床位闲忙状态，导致高峰期客户扎堆、因等待时间过长而愤怒离开。"
        },

        // Workflow / Closing
        "chu trình tự động khép kín": { en: "Closed-Loop Automation", zh: "闭环自动化" },
        "vận hành trơn tru không độ trễ, kết nối trực tiếp mọi bộ phận về tay sếp.": {
            en: "Smooth operations with zero delay, connecting all departments straight to your hand.",
            zh: "高效运转无延迟，所有部门的数据和状态直接呈现给您。"
        },
        "chọn lịch & ktv": { en: "Select Schedule & Therapist", zh: "选择预约与技师" },
        "khách đặt lịch hẹn điều trị, chủ động chọn ktv và phòng dịch vụ yêu thích.": {
            en: "Clients book appointments online, selecting their preferred therapist and treatment room.",
            zh: "客户在线预约疗程，自主选择心仪的技师和专属服务房间。"
        },
        "xác thực faceid": { en: "FaceID Verification", zh: "人脸识别身份验证" },
        "khách đến quét khuôn mặt faceid/otp để kích hoạt trừ 1 buổi liệu trình số hóa.": {
            en: "Clients scan their face or verify via OTP to activate and deduct one digital treatment session.",
            zh: "客户到店进行人脸识别或手机验证，扣减一次数字化疗程次数。"
        },
        "ktv vào phòng": { en: "Therapist Enters Room", zh: "技师进入服务房" },
        "sơ đồ giường tự nhảy sang màu đỏ bận chơi, hệ thống tính hoa hồng ktv.": {
            en: "The room status automatically switches to busy red, and the system tracks therapist commissions.",
            zh: "床位图自动切换为忙碌红色，系统自动累计并计算技师提成。"
        },
        "khách check-out thanh toán, kho tự động trừ định lượng mỹ phẩm tiêu hao.": {
            en: "Client checks out, and the system automatically deducts consumed beauty product inventory.",
            zh: "客户结账离店，系统自动扣减所消耗的美容护肤品和耗材库存。"
        },

        // Differences
        "sự khác biệt": { en: "The Key Differences", zh: "核心差异对比" },
        "vượt trội": { en: "Outstanding Advantages", zh: "显著竞争优势" },
        "tại sao các thương hiệu spa & beauty lớn chọn bitpaw os thay vì cách quản lý cũ?": {
            en: "Why top Spa & Beauty brands choose BitPaw OS over outdated manual methods?",
            zh: "为什么知名美容会所品牌选择 BitPaw OS 而不是传统的管理模式？"
        },
        "cách quản lý thủ công / phần mềm cũ": { en: "Manual Methods / Legacy Software", zh: "传统手工管理 / 老旧软件" },
        "bitpaw os spa & beauty": { en: "BitPaw OS Spa & Beauty", zh: "BitPaw 智能美容美体系统" },
        "thẻ liệu trình giấy rách/mất, nhân viên tự ghi khống buổi làm.": {
            en: "Paper cards easily torn/lost, staff cheat on sessions.",
            zh: "纸质疗程卡易破损丢失，员工私自虚报服务次数。"
        },
        "liệu trình số hóa faceid/otp bảo mật, triệt tiêu chui 100%.": {
            en: "Digital treatments with FaceID/OTP security, 100% leak-proof.",
            zh: "数字化疗程加密，人脸/验证码二次验证，100%防止作弊。"
        },
        "xếp tua ktv thủ công, tị nạnh ca vip, chia tips mập mờ.": {
            en: "Manual therapist shifting, conflicts over VIP sessions, unclear tips.",
            zh: "人工排班容易引发VIP单争执，小费及提成拆分不透明。"
        },
        "vòng tua ktv công bằng tự động theo ca làm, hoa hồng minh bạch.": {
            en: "Automated fair staff rotation by shifts, transparent commission tracking.",
            zh: "轮班规则公平自动流转，每笔业绩和提成一目了然。"
        },
        "không rõ tình trạng phòng/giường trống lúc khách đến đông.": {
            en: "No clear sight of room/bed availability during peak rush.",
            zh: "高峰期来客扎堆时，前台无法实时掌握包房和床位闲忙。"
        },
        "sơ đồ giường real-time, sắp xếp ca trị liệu nhanh chóng.": {
            en: "Real-time room layout, ultra-fast appointment scheduling.",
            zh: "实时房态与床位大屏，极速排课与调配技师服务。"
        },
        "khách bỏ dở liệu trình điều trị da mặt nửa chừng.": {
            en: "Clients leave treatment plans unfinished halfway.",
            zh: "客户购买了面部疗程却半途而废，不再到店。"
        },
        "ai tự nhắc lịch tái khám, điều trị định kỳ thông minh qua zalo.": {
            en: "AI automatically reminds clients of next sessions via Zalo/SMS.",
            zh: "AI智能通过 Zalo 自动发送下一期护理及复查的暖心提醒。"
        },

        // Footer
        "đồng hành cùng 15,000+ doanh nghiệp việt nam bứt phá doanh thu": {
            en: "Empowering 15,000+ businesses to multiply their revenue",
            zh: "携手 15,000+ 家企业共同实现业务的高效与营收增长"
        },
        "điều khoản dịch vụ": { en: "Terms of Service", zh: "服务条款" },
        "chính sách bảo mật": { en: "Privacy Policy", zh: "隐私政策" },
        "hỗ trợ khách hàng": { en: "Customer Support", zh: "客户支持" },
        "về chúng tôi": { en: "About Us", zh: "关于我们" },
        "liên hệ": { en: "Contact Us", zh: "联系我们" },

        // Pricing Card items
        "bảng giá gói dịch vụ": { en: "Service Pricing Plans", zh: "服务套餐价格表" },
        "tối ưu chi phí, cam kết hiệu quả kinh doanh thực tế": {
            en: "Optimize costs, proven business results guaranteed",
            zh: "超高性价比，助力实体店实现业绩稳健上升"
        },
        "tiết kiệm 20% khi chọn gói năm": { en: "Save 20% on Annual billing", zh: "选择年度套餐可节省 20%" },
        "chọn gói năm": { en: "Annual Plan", zh: "选择年付" },
        "tháng": { en: "month", zh: "月" },
        "/ tháng": { en: "/ month", zh: "每月" },
        "/ tháng (gói năm)": { en: "/ month (Annual)", zh: "每月 (按年付)" },
        "thông dụng": { en: "Popular", zh: "最受欢迎" },
        "đăng ký dùng thử": { en: "Start Free Trial", zh: "免费试用" },
        "tính năng nổi bật": { en: "Key Features", zh: "特色功能" },
        "thanh toán siêu tốc smart pos": { en: "Ultra-fast Smart POS Billing", zh: "智能收银POS系统" },
        "quản lý thẻ liệu trình số hóa": { en: "Digital Treatment Card Management", zh: "疗程储值卡包数字化" },
        "chấm công & tính tua ktv": { en: "HR Timekeeping & Rotation Tracking", zh: "考勤打卡与技师自动排班" },
        "báo cáo tài chính & kho cơ bản": { en: "Basic Financial & Stock Reporting", zh: "基础财务与进销存报表" },
        "hạ tầng bảo mật cloud rls": { en: "Cloud RLS Secure Infrastructure", zh: "云端 RLS 高度数据安全保护" },
        "phù hợp": { en: "Best for", zh: "适用于" },
        "cơ sở spa / nail nhỏ dưới 5 nhân viên": { en: "Small spa / nail salons under 5 staff", zh: "5人以下的单店水疗/美甲店" },
        "chuỗi từ 2 chi nhánh trở lên": { en: "Chains with 2+ branches", zh: "2个分店以上的中大型连锁店" },
        "tiệm spa & clinic từ 5 - 20 nhân viên": { en: "Spa & clinics with 5 - 20 staff", zh: "5至20名技师的专业美容会所" },
        "quản lý đa chi nhánh real-time": { en: "Real-time Multi-branch Management", zh: "多店连锁实时统一管理" },
        "đồng bộ kho chéo chi nhánh": { en: "Cross-branch Inventory Sync", zh: "跨店库存实时调配与扣减" },
        "phân quyền phân vai chuyên sâu": { en: "Advanced Role-based Access Control", zh: "精细化多角色权限管控" },
        "chuyên viên hỗ trợ riêng 24/7": { en: "Dedicated 24/7 Support Specialist", zh: "7x24小时白金专属客服支持" },

        // Industry details
        "smart pos order tại bàn vietqr": { en: "Smart POS Tableside VietQR Ordering", zh: "智能桌位扫码收银系统" },
        "quản lý định lượng nguyên liệu": { en: "Ingredient Recipe Control", zh: "后厨原料配比扣减防损" },
        "tự động xuất hóa đơn kds": { en: "Automated Kitchen KDS Invoicing", zh: "后厨KDS订单自动出票" },
        "đồng bộ shoppe / tiktok shop": { en: "Shopee & TikTok Shop Sync", zh: "多渠道电商平台库存同步" },
        "cảnh báo tồn kho tự động": { en: "Automatic Low Inventory Alert", zh: "缺货低库存自动预警" },
        "smart pos thanh toán siêu tốc": { en: "Smart POS Instant Payments", zh: "智能收银极速结算" },
        "quản lý phòng & buồng phòng real-time": { en: "Real-time Room & Bed Management", zh: "实时房态与客房日常管理" },
        "tích hợp khóa thẻ từ rfid": { en: "RFID Smart Keycard Integration", zh: "对接RFID电子门锁" },
        "order tự động tại phòng & bếp": { en: "Automated Room & Kitchen Ordering", zh: "房务与餐饮POS协同系统" },
        "giám sát ca kíp dọn phòng": { en: "Housekeeping Shift Tracking", zh: "保洁打扫绩效与排班管理" },
        "tính giờ tự động theo phòng (vip / thường)": { en: "Automatic Hourly Billing (VIP/Regular)", zh: "包房自动计时计费 (普通/豪华)" },
        "đồng bộ order kds & bếp": { en: "KDS & Kitchen Order Synchronization", zh: "后厨大屏与前台POS实时同步" },
        "lập kế hoạch sản xuất (bom)": { en: "Bill of Materials (BOM) Planning", zh: "物料清单 (BOM) 与生产排程" },
        "giám sát tiến độ xưởng real-time": { en: "Real-time Workshop Progress Tracking", zh: "数字化车间进度实时看板" },
        "chấm công sản phẩm công nhân": { en: "Piece-rate Worker Payroll Tracking", zh: "车间工人计件考勤结算" }
    };

    function getTranslation(vietnameseText, targetLang) {
        if (!vietnameseText) return null;
        const normalized = vietnameseText.replace(/\s+/g, ' ').trim().toLowerCase();
        if (translationDirectory[normalized]) {
            return translationDirectory[normalized][targetLang] || null;
        }
        
        // Try fallback exact translation mapping
        for (const [key, value] of Object.entries(translationDirectory)) {
            if (key === normalized) {
                return value[targetLang] || null;
            }
        }
        return null;
    }

    // Dynamic Page Translation Walker
    window.translatePageContent = function(lang) {
        const translateNode = (node) => {
            if (node.nodeType === Node.TEXT_NODE) {
                const text = node.nodeValue.trim();
                if (text) {
                    if (node._origText === undefined) {
                        node._origText = node.nodeValue;
                    }
                    const origTextTrimmed = node._origText.trim();
                    const key = origTextTrimmed;
                    if (lang === 'vi') {
                        node.nodeValue = node._origText;
                    } else {
                        const trans = getTranslation(key, lang);
                        if (trans) {
                            node.nodeValue = node._origText.replace(origTextTrimmed, trans);
                        }
                    }
                }
            } else if (node.nodeType === Node.ELEMENT_NODE) {
                const tagName = node.tagName.toLowerCase();
                if (tagName === 'script' || tagName === 'style' || tagName === 'iframe' || tagName === 'canvas') {
                    return;
                }
                
                // Translate attributes
                ['placeholder', 'title'].forEach(attr => {
                    if (node.hasAttribute(attr)) {
                        if (!node.getAttribute('data-orig-' + attr)) {
                            node.setAttribute('data-orig-' + attr, node.getAttribute(attr));
                        }
                        const origVal = node.getAttribute('data-orig-' + attr);
                        if (lang === 'vi') {
                            node.setAttribute(attr, origVal);
                        } else {
                            const trans = getTranslation(origVal, lang);
                            if (trans) {
                                node.setAttribute(attr, trans);
                            }
                        }
                    }
                });

                // Walk children
                for (let child = node.firstChild; child; child = child.nextSibling) {
                    translateNode(child);
                }
            }
        };

        translateNode(document.body);
    };

    // Chatbot Multilingual Data
    const chatbotConfig = {
        'vi': {
            greeting: "Xin chào Sếp 👋 Em là BitPaw AI. Sếp đang kinh doanh ngành nào để em tư vấn gói phù hợp?",
            quickReplies: [
                "Spa / Nail",
                "Nhà hàng / Cafe",
                "Bán lẻ",
                "Khách sạn",
                "Karaoke",
                "Sản xuất",
                "Tôi muốn báo giá",
                "Tôi muốn demo"
            ],
            expert: "Trợ lý AI BitPaw",
            status: "Live AI Active 24/7",
            placeholderPhone: "SĐT / Zalo của sếp để kích hoạt nhanh...",
            placeholderMsg: "Nhập câu hỏi hoặc sếp chọn câu hỏi nhanh bên trên..."
        },
        'en': {
            greeting: "Hello Boss 👋 I am BitPaw AI. Which industry are you in so I can recommend the best package?",
            quickReplies: [
                "Spa / Nail",
                "Restaurant / Cafe",
                "Retail",
                "Hotel",
                "Karaoke",
                "Production",
                "Tôi muốn báo giá", // keep exact text to trigger correct rules
                "Tôi muốn demo"
            ],
            expert: "BitPaw AI Assistant",
            status: "Live AI Active 24/7",
            placeholderPhone: "Enter your Phone / Zalo...",
            placeholderMsg: "Enter questions or select quick replies above..."
        },
        'zh': {
            greeting: "老板您好 👋 我是 BitPaw AI。请问您是从事哪个行业的，以便我为您推荐最适合的方案？",
            quickReplies: [
                "水疗 / 美甲",
                "餐饮 / 咖啡",
                "零售",
                "酒店",
                "KTV量贩",
                "制造生产",
                "Tôi muốn báo giá", // keep exact text to trigger correct rules
                "Tôi muốn demo"
            ],
            expert: "BitPaw AI 销售助手",
            status: "AI助手 24/7 在线",
            placeholderPhone: "输入您的电话 / 微信 / Zalo...",
            placeholderMsg: "输入问题或选择上方快捷回复..."
        }
    };

    const responseRules = {
        'vi': {
            spa: "Dạ hoàn toàn được ạ! 🌸 Hệ sinh thái <strong>BitPaw Spa & Clinic</strong> được thiết kế chuyên biệt để tự động xếp lịch hẹn trực tuyến (online booking), sắp xếp vòng tua nhân viên công bằng và tự động tính hoa hồng thợ (commissions) theo phần trăm dịch vụ/liệu trình vô cùng chi tiết. Sếp sẽ giải phóng hoàn toàn thời gian cộng sổ tay thủ công! Sếp có muốn đăng ký dùng thử 30 ngày tính năng này không ạ?",
            nail: "Chào sếp! 💅 Gói <strong>Standard (chỉ từ 990.000đ/tháng)</strong> là sự lựa chọn tối ưu nhất cho tiệm Nails. Gói này bao gồm đầy đủ tính năng: Smart POS đặt bàn/ghế, quản lý khách hàng (CRM), chấm công nhân viên và Trợ lý AI tự động gửi tin nhắn tri ân Zalo OA. Đây là bệ phóng hoàn hảo giúp sếp vận hành tiệm chuyên nghiệp ngay từ ngày đầu!",
            fnb: "Dạ hệ thống <strong>BitPaw F&B</strong> hỗ trợ order bằng quét mã QR tại bàn, tự động xuất hóa đơn, quản lý định lượng nguyên vật liệu tránh hao hụt, và liên kết trực tiếp màn hình bếp. Giúp nhà hàng/cafe tăng tốc phục vụ gấp 2 lần!",
            retail: "Dạ giải pháp <strong>BitPaw Retail</strong> đồng bộ tồn kho đa kênh (Shopee, Lazada, TikTok Shop, Cửa hàng), cảnh báo hết hàng tự động, tích hợp Smart POS thanh toán siêu tốc và báo cáo lợi nhuận chi tiết từng mặt hàng.",
            hotel: "Dạ <strong>BitPaw Hotel</strong> giúp tối ưu quản lý buồng phòng real-time, tích hợp khóa thẻ từ, quản lý check-in/check-out tự động, chấm công nhân viên dọn phòng và báo cáo doanh thu tối ưu.",
            karaoke: "Dạ <strong>BitPaw Karaoke</strong> quản lý tính giờ tự động theo phòng (Thường, VIP), gọi đồ ăn uống tích hợp POS, tự động chuyển trạng thái phòng và quản lý thâm niên nhân viên ca kíp.",
            production: "Dạ <strong>BitPaw Production</strong> giúp lập kế hoạch sản xuất, định mức vật tư (BOM), giám sát tiến độ xưởng real-time, chấm công sản phẩm công nhân và tối ưu hóa chuỗi cung ứng.",
            retention: "Dạ xuất sắc luôn sếp ơi! 🚀 BitPaw sở hữu công nghệ <strong>AI Auto-Pilot Retention</strong> độc quyền. Trợ lý AI sẽ tự động gom toàn bộ data khách cũ từ Facebook Page, Zalo OA và Website về một mối. Sau đó, AI tự động quét chẩn đoán rủi ro rời bỏ (Churn Risk) và gửi chuỗi tin nhắn bám đuổi (3/7/14 ngày) kèm mã coupon cá nhân hóa qua Zalo/FB hoàn toàn tự động. Giúp kéo 45% khách quay lại mà sếp không tốn 1 đồng chi phí quảng cáo!",
            pricing_start: "Dạ vâng ạ! 🚀 Trợ lý AI sẽ lập tức khởi tạo bảng báo giá chi tiết và lộ trình triển khai tối ưu cho sếp. Sếp vui lòng cho em xin một vài thông tin để hoàn tất hồ sơ nhé.<br><br>👉 Đầu tiên, sếp tên gì ạ?",
            pricing_phone: "Dạ chào sếp <strong>{name}</strong>! 🌸 Tiếp theo, sếp cho em xin Số điện thoại / Zalo để gửi bảng báo giá & kết nối chuyên viên hỗ trợ sau 5 phút nhé ạ? 📞",
            pricing_email: "Tuyệt vời sếp ơi! 👍 Cuối cùng sếp cho em xin địa chỉ Email để nhận trọn bộ tài liệu giải pháp và hợp đồng mẫu của BitPaw nha sếp? ✉️",
            pricing_success: "Báo cáo sếp <strong>{name}</strong>, thông tin của sếp đã được lưu trữ thành công trên CRM của BitPaw! 🟢<br><br>Chuyên viên tư vấn giải pháp sẽ liên hệ với sếp qua Zalo (<strong>{phone}</strong>) và gửi tài liệu qua Email (<strong>{email}</strong>) sau 5 phút nữa nha sếp! Cảm ơn sếp nhiều ạ! 🤖🚀",
            demo: "Dạ sếp có muốn nhận link demo trải nghiệm trực tiếp hệ thống Cloud ERP đa phân hệ của BitPaw không ạ? Sếp vui lòng chọn \"Tôi muốn báo giá\" hoặc nhập Số điện thoại để em gửi tài khoản dùng thử ngay nhé!",
            fallback: "Dạ chào sếp! BitPaw rất vui vì sếp quan tâm. Trợ lý AI đang ghi nhận yêu cầu của sếp: <em>'{msg}'</em>. Chuyên gia giải pháp của tụi em sẽ trực tiếp gọi điện/Zalo tư vấn chi tiết cho sếp sau 5 phút nữa nha! 🚀"
        },
        'en': {
            spa: "Absolutely! 🌸 The <strong>BitPaw Spa & Clinic</strong> ecosystem is specially designed to automate online bookings, schedule fair staff rotations, and calculate commissions based on services or treatment packages in real-time. You will be completely free from manual bookkeeping! Would you like to sign up for a 30-day free trial?",
            nail: "Hello Boss! 💅 Our <strong>Standard package (from only 990,000 VND/month)</strong> is the optimal choice for Nail salons. It includes: Smart POS seat tracking, Customer CRM, employee timekeeping, and an AI assistant that auto-sends gratitude Zalo/FB messages. This is the perfect springboard for professional operations from day one!",
            fnb: "The <strong>BitPaw F&B</strong> system supports tableside QR code ordering, automatic invoicing, precise ingredient inventory control to minimize waste, and kitchen display screen (KDS) integration. Helping restaurants and cafes serve twice as fast!",
            retail: "Our <strong>BitPaw Retail</strong> solution syncs real-time inventory across multi-channels (Shopee, Lazada, TikTok Shop, Retail Store), warns of low stock automatically, integrates ultra-fast Smart POS, and reports detailed itemized profitability.",
            hotel: "<strong>BitPaw Hotel</strong> optimizes real-time room status management, integrates RFID keycards, automates check-in/check-out, tracks housekeeping task sheets, and details revenue metrics.",
            karaoke: "<strong>BitPaw Karaoke</strong> automates hourly room rate billing (Standard, VIP), links food and drink ordering to POS, auto-updates room status, and manages staff shift schedules.",
            production: "<strong>BitPaw Production</strong> helps in manufacturing planning, Bill of Materials (BOM) management, real-time workshop monitoring, piece-rate worker payroll, and supply chain optimization.",
            retention: "Excellent, Boss! 🚀 BitPaw features our exclusive <strong>AI Auto-Pilot Retention</strong> technology. The AI assistant automatically gathers all customer data from Facebook Pages, Zalo OA, and websites into a single CRM database. It then auto-scans for churn risk and triggers a personalized messaging sequence (at 3/7/14 days) with custom discount coupons via Zalo/FB. This helps bring back 45% of inactive customers without spending a dime on ads!",
            pricing_start: "Sure, Boss! 🚀 The AI Assistant will immediately generate a customized pricing quote and implementation plan for you. Please provide some quick details to complete your request.<br><br>👉 First, what is your name?",
            pricing_phone: "Hi Boss <strong>{name}</strong>! 🌸 Next, could you please provide your Phone number / Zalo so we can send the quote and have our specialist contact you in 5 minutes? 📞",
            pricing_email: "Wonderful, Boss! 👍 Lastly, what is your Email address to receive the full solution deck and sample agreement from BitPaw? ✉️",
            pricing_success: "Report to Boss <strong>{name}</strong>, your details have been successfully saved in BitPaw CRM! 🟢<br><br>Our solution specialist will contact you on Zalo (<strong>{phone}</strong>) and send documents to your Email (<strong>{email}</strong>) within 5 minutes! Thank you so much, Boss! 🤖🚀",
            demo: "Would you like a live demo link to experience BitPaw's multi-module Cloud ERP system? Please select \"Request Pricing\" or input your phone number so I can send the trial credentials right away!",
            fallback: "Hello Boss! BitPaw is glad to help. The AI Assistant has logged your request: <em>'{msg}'</em>. Our solution specialist will contact you on Zalo/Phone within 5 minutes to consult in detail! 🚀"
        },
        'zh': {
            spa: "完全可以！ 🌸 <strong>BitPaw 智能水疗与美容</strong>生态系统专为美容会所设计，支持在线预约自动排班、公平技师轮班，并自动按服务/疗程比例精确计算员工提成。您将彻底告别繁琐的手工记账！您想免费试用30天吗？",
            nail: "老板您好！💅 <strong>标准版套餐（每月仅需99万越南盾起）</strong>是美甲店的最优选择。该套餐包含完整功能：智能桌位POS、客户关系管理 (CRM)、员工考勤打卡以及AI助手自动发送感谢短信。这是您从第一天起专业化运营的完美起点！",
            fnb: "<strong>BitPaw 餐饮系统</strong>支持扫描桌码自主点餐、自动出票、原料库存精细化扣减防损，以及后厨KDS大屏联动。助您的餐厅/咖啡厅服务效率提升两倍！",
            retail: "<strong>BitPaw 零售方案</strong>支持多渠道库存实时同步（虾皮、Lazada、抖音、线下店），自动预警缺货，集成极速收银POS，并生成单品维度的精细利润报表。",
            hotel: "<strong>BitPaw 酒店系统</strong>助您优化实时房态管理，对接电子门锁，自动处理办理入住/退房，统计客房保洁绩效，并输出多维度营收报表。",
            karaoke: "<strong>BitPaw KTV系统</strong>支持包厢按时计费（普通房、VIP房）、酒水小吃POS协同点单、房态自动流转以及员工排班和业绩提成管理。",
            production: "<strong>BitPaw 生产管理系统</strong>提供排程生产、物料清单 (BOM) 管理、车间进度实时追踪、工人计件工资统计以及供应链优化方案。",
            retention: "太棒了，老板！🚀 BitPaw 拥有独家的 <strong>AI 自动客户流失挽回</strong>技术。AI助手会自动从 Facebook 页面、Zalo OA 和网站收集所有历史客户数据，汇入统一 CRM。随后，AI 会自动扫描评估流失风险，并自动通过 Zalo/FB 发送个性化折扣卡券的跟进短信（第3/7/14天），帮您挽回45%的老客户，完全无需额外广告费！",
            pricing_start: "好的，老板！🚀 AI 助手将立即为您制定详细的报价表和最佳实施方案。请提供以下信息以完善您的申请。<br><br>👉 首先，请问您怎么称呼？",
            pricing_phone: "您好，<strong>{name}</strong> 老板！🌸 接下来，请问您的电话号码或 Zalo 账号是多少，以便我们在5分钟内发送报价表并指派专员联络您？ 📞",
            pricing_email: "太棒了，老板！👍 最后，请问您的电子邮箱地址是多少，以便接收 BitPaw 的全套解决方案文档和合同范本？ ✉️",
            pricing_success: "报告 <strong>{name}</strong> 老板，您的信息已成功存入 BitPaw CRM 系统！ 🟢<br><br>我们的解决方案专员将在5分钟内通过 Zalo (<strong>{phone}</strong>) 与您联系，并将文档发送至您的邮箱 (<strong>{email}</strong>)！非常感谢老板！🤖🚀",
            demo: "老板，您想获得在线演示链接，亲自体验 BitPaw 的多模块云 ERP 系统吗？请选择“我想获取报价”或输入您的手机号，我将立即为您发送试用账号！",
            fallback: "老板您好！BitPaw 很高兴为您服务。AI 助手已记录您的需求：<em>'{msg}'</em>。我们的解决方案专家将在5分钟内直接通过 Zalo/电话与您联系，为您提供详细咨询！ 🚀"
        }
    };

    // Auto Inject Language Switcher
    function injectLanguageSwitcher() {
        if (document.getElementById('current-lang-text')) return;

        // Desktop
        const desktopTarget = document.querySelector('header .flex.items-center.gap-4');
        if (desktopTarget) {
            const wrapper = document.createElement('div');
            wrapper.className = 'relative lang-wrapper hidden md:block z-50 py-2';
            wrapper.style.marginRight = '8px';
            wrapper.innerHTML = `
                <button class="flex items-center gap-2 text-sm font-bold text-gray-300 hover:text-white transition bg-white/5 px-3 py-1.5 rounded-lg border border-white/10">
                    <span id="current-lang-icon">🇻🇳</span> <span id="current-lang-text">VN</span> <i class="fas fa-chevron-down text-[10px]"></i>
                </button>
                <div class="lang-dropdown" style="position: absolute; right: 0; top: 100%; background: #0a0f25; border: 1px solid rgba(255,255,255,0.1); border-radius: 8px; box-shadow: 0 10px 30px rgba(0,0,0,0.5); display: none; min-width: 120px; flex-direction: column; overflow: hidden; z-index: 9999;">
                    <a href="#" onclick="changeLanguage('vi'); return false;" class="flex items-center gap-2 px-4 py-2.5 text-sm text-gray-300 hover:bg-cyan-500/20 hover:text-cyan-400 transition"><span style="font-size:16px;">🇻🇳</span> Tiếng Việt</a>
                    <a href="#" onclick="changeLanguage('en'); return false;" class="flex items-center gap-2 px-4 py-2.5 text-sm text-gray-300 hover:bg-cyan-500/20 hover:text-cyan-400 transition"><span style="font-size:16px;">🇬🇧</span> English</a>
                    <a href="#" onclick="changeLanguage('zh'); return false;" class="flex items-center gap-2 px-4 py-2.5 text-sm text-gray-300 hover:bg-cyan-500/20 hover:text-cyan-400 transition"><span style="font-size:16px;">🇨🇳</span> 中文</a>
                </div>
            `;
            
            const btn = wrapper.querySelector('button');
            const dropdown = wrapper.querySelector('.lang-dropdown');
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                dropdown.style.display = dropdown.style.display === 'flex' ? 'none' : 'flex';
            });
            document.addEventListener('click', () => {
                dropdown.style.display = 'none';
            });
            
            desktopTarget.insertBefore(wrapper, desktopTarget.firstChild);
        }

        // Mobile
        const mobileTarget = document.querySelector('#mobile-menu nav');
        if (mobileTarget) {
            const div = document.createElement('div');
            div.className = 'flex items-center gap-4 border-y border-white/10 py-3';
            div.innerHTML = `
                <span class="text-sm data-i18n-lang-label">Ngôn ngữ:</span>
                <button onclick="changeLanguage('vi'); toggleMobileMenu()" class="text-2xl hover:scale-110 transition">🇻🇳</button>
                <button onclick="changeLanguage('en'); toggleMobileMenu()" class="text-2xl hover:scale-110 transition">🇬🇧</button>
                <button onclick="changeLanguage('zh'); toggleMobileMenu()" class="text-2xl hover:scale-110 transition">🇨🇳</button>
            `;
            
            const loginBtn = mobileTarget.querySelector('a[href="/login"]');
            if (loginBtn) {
                mobileTarget.insertBefore(div, loginBtn);
            } else {
                mobileTarget.appendChild(div);
            }
        }
    }

    // Redefine changeLanguage globally
    const existingChangeLanguage = window.changeLanguage;
    window.changeLanguage = function(lang) {
        localStorage.setItem('selected_language', lang);
        
        const icon = lang === 'vi' ? '🇻🇳' : (lang === 'en' ? '🇬🇧' : '🇨🇳');
        const text = lang === 'vi' ? 'VN' : (lang === 'en' ? 'EN' : '中文');
        
        const currentIconEl = document.getElementById('current-lang-icon');
        const currentTextEl = document.getElementById('current-lang-text');
        if (currentIconEl) currentIconEl.innerText = icon;
        if (currentTextEl) currentTextEl.innerText = text;
        
        const langLabel = document.querySelector('.data-i18n-lang-label');
        if (langLabel) {
            langLabel.innerText = lang === 'vi' ? 'Ngôn ngữ:' : (lang === 'en' ? 'Language:' : '语言:');
        }

        if (typeof existingChangeLanguage === 'function') {
            existingChangeLanguage(lang);
        }

        window.translatePageContent(lang);
        window.updateChatbotLanguage(lang);
    };

    // State Variables
    let currentLanguage = localStorage.getItem('selected_language') || 'vi';
    let chatState = "idle";
    let leadData = { name: "", phone: "", email: "", message: "" };

    // Update Chatbot Language
    window.updateChatbotLanguage = function(lang) {
        currentLanguage = lang;
        const config = chatbotConfig[lang] || chatbotConfig['vi'];
        
        // Update headers & placeholders
        const expertEl = chatWidget.querySelector('h4');
        if (expertEl) expertEl.innerHTML = `${config.expert} <i class="fas fa-robot text-xs animate-bounce text-cyan-300"></i>`;
        
        const statusEl = chatWidget.querySelector('p.text-\\[9px\\] span');
        if (statusEl) statusEl.innerText = config.status;

        const phoneInput = document.getElementById("aiChatPhone");
        if (phoneInput) phoneInput.setAttribute('placeholder', config.placeholderPhone);

        const msgInput = document.getElementById("aiChatMsg");
        if (msgInput) msgInput.setAttribute('placeholder', config.placeholderMsg);

        // Update Quick Replies buttons
        const repliesContainer = chatWidget.querySelector('.no-scrollbar');
        if (repliesContainer) {
            repliesContainer.innerHTML = config.quickReplies.map((q, idx) => `
                <button onclick="triggerQuickQuestion(${idx})" class="shrink-0 bg-cyan-500/10 hover:bg-cyan-500/25 border border-cyan-500/30 text-cyan-300 text-[9px] font-bold px-3 py-1.5 rounded-full transition-all duration-300 whitespace-nowrap">
                    ${q}
                </button>
            `).join('');
        }

        // Re-inject the greeting as the first message if no conversation has taken place
        const chatBoxBody = document.getElementById("aiChatBoxBody");
        if (chatBoxBody && chatBoxBody.children.length <= 1) {
            chatBoxBody.innerHTML = "";
            appendChatMessage("ai", config.greeting);
        }
    };

    // Append Message UI
    const chatBoxBody = document.createElement("div"); // Placeholder to satisfy compiler
    function appendChatMessage(sender, text) {
        const body = document.getElementById("aiChatBoxBody");
        if (!body) return;
        const item = document.createElement("div");
        if (sender === "customer") {
            item.className = "flex gap-2.5 items-start justify-end";
            item.innerHTML = `
                <div class="bg-white/5 border border-white/10 p-3 rounded-2xl rounded-tr-sm max-w-[85%] text-gray-300 text-[11px] font-medium leading-relaxed">
                    ${text}
                </div>
                <div class="w-6 h-6 rounded-full bg-gray-700 flex items-center justify-center text-white shrink-0 text-[10px]">👤</div>
            `;
        } else {
            item.className = "flex gap-2.5 items-start";
            item.innerHTML = `
                <div class="w-6 h-6 rounded-full bg-cyan-500 flex items-center justify-center text-black shrink-0 font-black mascot-glow overflow-hidden"><img src="/static/cho1.jpg" class="w-full h-full object-cover"></div>
                <div class="bg-cyan-500/10 border border-cyan-500/30 p-3 rounded-2xl rounded-tl-sm max-w-[85%] text-cyan-300 text-[11px] font-medium leading-relaxed">
                    ${text}
                </div>
            `;
        }
        body.appendChild(item);
        body.scrollTop = body.scrollHeight;
    }

    // Typing bubble simulator
    function showTypingIndicator() {
        const body = document.getElementById("aiChatBoxBody");
        if (!body) return;
        const item = document.createElement("div");
        item.id = "aiTypingBubble";
        item.className = "flex flex-col gap-1 items-start mt-2";
        const label = currentLanguage === 'vi' ? 'AI đang phân tích nhu cầu...' : (currentLanguage === 'en' ? 'AI is processing...' : 'AI 正在处理需求...');
        item.innerHTML = `
            <span class="text-[8px] text-cyan-400 font-bold ml-8 flex items-center gap-1"><i class="fas fa-spinner fa-spin"></i> ${label}</span>
            <div class="flex gap-2.5 items-start">
                <div class="w-6 h-6 rounded-full bg-cyan-500 flex items-center justify-center text-black shrink-0 font-black overflow-hidden"><img src="/static/cho1.jpg" class="w-full h-full object-cover"></div>
                <div class="typing-bubble bg-cyan-500/10 border border-cyan-500/20">
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                </div>
            </div>
        `;
        body.appendChild(item);
        body.scrollTop = body.scrollHeight;
    }

    function removeTypingIndicator() {
        const bubble = document.getElementById("aiTypingBubble");
        if (bubble) bubble.remove();
    }

    // Trigger Chat Quick Question Click
    window.triggerQuickQuestion = function(idx) {
        const config = chatbotConfig[currentLanguage] || chatbotConfig['vi'];
        const fullQ = config.quickReplies[idx];
        const input = document.getElementById("aiChatMsg");
        if (input) {
            input.value = fullQ;
            const form = document.getElementById("aiChatForm");
            if (form) {
                const submitEvent = new Event("submit", {cancelable: true});
                form.dispatchEvent(submitEvent);
            }
        }
    };

    // Chat widget layout initializer
    const config = chatbotConfig[currentLanguage] || chatbotConfig['vi'];
    chatWidget.innerHTML = `
        <div class="bg-gradient-to-r from-cyan-600 to-blue-700 p-4 flex justify-between items-center text-white border-b border-white/20 animate-pulse-border">
            <div class="flex items-center gap-3">
                <div class="relative">
                    <img src="/static/cho1.jpg" onerror="this.onerror=null; this.src='/static/cho1.jpg';" class="w-10 h-10 rounded-full border-2 border-white/50 object-cover mascot-glow font-black flex items-center justify-center">
                    <div class="absolute bottom-0 right-0 w-3 h-3 bg-green-400 border-2 border-blue-700 rounded-full animate-pulse"></div>
                </div>
                <div>
                    <h4 class="font-bold text-sm flex items-center gap-1.5">${config.expert} <i class="fas fa-robot text-xs animate-bounce text-cyan-300"></i></h4>
                    <p class="text-[9px] text-cyan-100 flex items-center gap-1"><i class="fas fa-bolt"></i> <span>${config.status}</span></p>
                </div>
            </div>
            <button onclick="toggleChat()" class="text-white/70 hover:text-white transition text-lg"><i class="fas fa-times"></i></button>
        </div>
        
        <!-- Live Message Scroll Box -->
        <div id="aiChatBoxBody" class="p-4 h-64 overflow-y-auto flex flex-col gap-3.5 modal-scroll bg-black/25">
            <!-- Greeting loaded on startup -->
        </div>

        <!-- Quick Questions Capsule Container -->
        <div class="p-2 border-t border-white/5 bg-black/40 flex gap-2 overflow-x-auto select-none no-scrollbar" style="scrollbar-width: none;">
            ${config.quickReplies.map((q, idx) => `
                <button onclick="triggerQuickQuestion(${idx})" class="shrink-0 bg-cyan-500/10 hover:bg-cyan-500/25 border border-cyan-500/30 text-cyan-300 text-[9px] font-bold px-3 py-1.5 rounded-full transition-all duration-300 whitespace-nowrap">
                    ${q}
                </button>
            `).join('')}
        </div>
        
        <div class="p-3 border-t border-white/10 bg-black/55">
            <form id="aiChatForm" onsubmit="handleLiveChatSubmit(event)" class="flex flex-col gap-2">
                <input type="text" id="aiChatPhone" placeholder="${config.placeholderPhone}" class="w-full bg-black/60 border border-white/10 rounded-xl px-4 py-2 text-[11px] text-white focus:outline-none focus:border-cyan-400 transition placeholder-gray-600">
                <div class="flex items-center gap-2 bg-black/60 border border-white/10 rounded-xl pr-2 focus-within:border-cyan-400 transition">
                    <input type="text" id="aiChatMsg" placeholder="${config.placeholderMsg}" required class="w-full bg-transparent px-4 py-2.5 text-[11px] text-white focus:outline-none placeholder-gray-600">
                    <button type="submit" class="bg-cyan-500 hover:bg-cyan-400 text-black w-8 h-8 rounded-lg font-black transition flex items-center justify-center shrink-0"><i class="fas fa-paper-plane text-xs"></i></button>
                </div>
            </form>
        </div>
    `;

    // Process submit chat message
    window.handleLiveChatSubmit = function(e) {
        if (e && e.preventDefault) e.preventDefault();
        
        const msgInput = document.getElementById("aiChatMsg");
        const phoneInput = document.getElementById("aiChatPhone");
        
        const messageText = msgInput.value.trim();
        const phoneText = phoneInput ? phoneInput.value.trim() : "";
        
        if (!messageText) return;

        // Reset text value
        msgInput.value = "";
        
        appendChatMessage("customer", messageText);
        showTypingIndicator();
        
        setTimeout(() => {
            removeTypingIndicator();
            
            const lowerMsg = messageText.toLowerCase();
            const rules = responseRules[currentLanguage] || responseRules['vi'];
            
            let matchedResponse = "";
            
            // Sequential wizard state tracker
            if (chatState === "collecting_name") {
                leadData.name = messageText;
                matchedResponse = rules.pricing_phone.replace("{name}", leadData.name);
                chatState = "collecting_phone";
                appendChatMessage("ai", matchedResponse);
                return;
            }
            
            if (chatState === "collecting_phone") {
                leadData.phone = messageText;
                matchedResponse = rules.pricing_email;
                chatState = "collecting_email";
                appendChatMessage("ai", matchedResponse);
                return;
            }
            
            if (chatState === "collecting_email") {
                leadData.email = messageText;
                showTypingIndicator();
                
                // REST API to database CRM registration
                fetch('/api/cskh/request', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        name: leadData.name,
                        phone: leadData.phone,
                        email: leadData.email,
                        message: `Lead captured via Mascot Chat. Industry Interest: ${leadData.message}`
                    })
                })
                .then(res => res.json())
                .then(data => {
                    removeTypingIndicator();
                    const successResponse = rules.pricing_success
                        .replace("{name}", leadData.name)
                        .replace("{phone}", leadData.phone)
                        .replace("{email}", leadData.email);
                    appendChatMessage("ai", successResponse);
                    chatState = "idle";
                })
                .catch(err => {
                    removeTypingIndicator();
                    const successResponse = rules.pricing_success
                        .replace("{name}", leadData.name)
                        .replace("{phone}", leadData.phone)
                        .replace("{email}", leadData.email);
                    appendChatMessage("ai", successResponse);
                    chatState = "idle";
                });
                return;
            }
            
            // Standard NLP Matching rules
            let handled = false;
            
            // Collect Quote flow
            if (lowerMsg.includes("báo giá") || lowerMsg.includes("biết giá") || lowerMsg.includes("pricing") || lowerMsg.includes("price") || lowerMsg.includes("报价") || lowerMsg.includes("价格") || lowerMsg.includes("demo") || lowerMsg.includes("演示") || lowerMsg.includes("dùng thử") || lowerMsg.includes("trial")) {
                leadData.message = messageText;
                matchedResponse = rules.pricing_start;
                chatState = "collecting_name";
                appendChatMessage("ai", matchedResponse);
                return;
            }
            
            // Keyword checks
            if (lowerMsg.includes("spa") || lowerMsg.includes("nail") || lowerMsg.includes("美甲")) {
                matchedResponse = lowerMsg.includes("spa") ? rules.spa : rules.nail;
                handled = true;
            } else if (lowerMsg.includes("khách cũ") || lowerMsg.includes("300") || lowerMsg.includes("retention") || lowerMsg.includes("老客户") || lowerMsg.includes("churn")) {
                matchedResponse = rules.retention;
                handled = true;
            } else if (lowerMsg.includes("chăm sóc") || lowerMsg.includes("tự động") || lowerMsg.includes("automation") || lowerMsg.includes("流失") || lowerMsg.includes("自动")) {
                matchedResponse = rules.retention;
                handled = true;
            } else if (lowerMsg.includes("nhà hàng") || lowerMsg.includes("cafe") || lowerMsg.includes("f&b") || lowerMsg.includes("餐饮") || lowerMsg.includes("咖啡")) {
                matchedResponse = rules.fnb;
                handled = true;
            } else if (lowerMsg.includes("bán lẻ") || lowerMsg.includes("retail") || lowerMsg.includes("shopee") || lowerMsg.includes("tiktok") || lowerMsg.includes("零售")) {
                matchedResponse = rules.retail;
                handled = true;
            } else if (lowerMsg.includes("khách sạn") || lowerMsg.includes("hotel") || lowerMsg.includes("room") || lowerMsg.includes("酒店")) {
                matchedResponse = rules.hotel;
                handled = true;
            } else if (lowerMsg.includes("karaoke") || lowerMsg.includes("ktv") || lowerMsg.includes("包厢")) {
                matchedResponse = rules.karaoke;
                handled = true;
            } else if (lowerMsg.includes("sản xuất") || lowerMsg.includes("production") || lowerMsg.includes("xưởng") || lowerMsg.includes("制造")) {
                matchedResponse = rules.production;
                handled = true;
            }
            
            if (!handled) {
                matchedResponse = rules.fallback.replace("{msg}", messageText);
            }
            
            appendChatMessage("ai", matchedResponse);
        }, 1000);
    };

    // Inject switchers immediately on startup if missing
    injectLanguageSwitcher();

    // Trigger initial language translation setup based on localStorage cache
    window.changeLanguage(currentLanguage);

    // Initial greeting load
    setTimeout(() => {
        const config = chatbotConfig[currentLanguage] || chatbotConfig['vi'];
        appendChatMessage("ai", config.greeting);
    }, 400);
});
