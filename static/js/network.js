/* =========================================================================
   BITPAW NETWORK - DYNAMIC INTERACTION CONTROLLER (CLIENT-SIDE)
   ========================================================================= */

document.addEventListener('DOMContentLoaded', () => {
    // 1. Galaxy Node Graph Canvas Connection Line Drawer
    initGalaxyGraph();

    // 2. Multi-step Onboarding Form Wizard
    initOnboardingWizard();

    // 3. Simulated Waitlist Live Activity Counter
    initWaitlistCounter();

    // 4. LocalStorage Messages & Chat Bot Simulation
    initChatSimulator();

    // 5. Digital CV Builder Workspace logic
    initCVBuilder();
});

// --- 1. GALAXY NETWORK GRAPH CONNECTIONS ---
function initGalaxyGraph() {
    const canvas = document.getElementById('galaxyCanvas');
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    const resizeCanvas = () => {
        canvas.width = canvas.parentElement.clientWidth;
        canvas.height = canvas.parentElement.clientHeight;
    };
    resizeCanvas();
    window.addEventListener('resize', resizeCanvas);

    const nodes = document.querySelectorAll('.galaxy-node');
    
    function drawConnections() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        
        // Find positions relative to canvas container
        const rects = [];
        const containerRect = canvas.parentElement.getBoundingClientRect();

        nodes.forEach(node => {
            const rect = node.getBoundingClientRect();
            const x = (rect.left + rect.width / 2) - containerRect.left;
            const y = (rect.top + rect.height / 2) - containerRect.top;
            rects.push({ x, y, color: node.dataset.color || '#06b6d4' });
        });

        // Draw web lines
        ctx.lineWidth = 1;
        for (let i = 0; i < rects.length; i++) {
            for (let j = i + 1; j < rects.length; j++) {
                const dist = Math.hypot(rects[i].x - rects[j].x, rects[i].y - rects[j].y);
                if (dist < 280) {
                    const gradient = ctx.createLinearGradient(rects[i].x, rects[i].y, rects[j].x, rects[j].y);
                    gradient.addColorStop(0, hexToRgbA(rects[i].color, 0.25));
                    gradient.addColorStop(1, hexToRgbA(rects[j].color, 0.25));
                    ctx.strokeStyle = gradient;
                    ctx.beginPath();
                    ctx.moveTo(rects[i].x, rects[i].y);
                    ctx.lineTo(rects[j].x, rects[j].y);
                    ctx.stroke();
                }
            }
        }

        requestAnimationFrame(drawConnections);
    }
    requestAnimationFrame(drawConnections);
}

function hexToRgbA(hex, alpha = 1) {
    let c;
    if(/^#([A-Fa-f0-9]{3}){1,2}$/.test(hex)){
        c= hex.substring(1).split('');
        if(c.length== 3){
            c= [c[0], c[0], c[1], c[1], c[2], c[2]];
        }
        c= '0x' + c.join('');
        return 'rgba('+[(c>>16)&255, (c>>8)&255, c&255].join(',')+','+alpha+')';
    }
    return 'rgba(6,182,212,'+alpha+')';
}

// --- 2. ONBOARDING WIZARD ---
function initOnboardingWizard() {
    const wizardForm = document.getElementById('onboardingWizardForm');
    if (!wizardForm) return;

    const steps = wizardForm.querySelectorAll('.wizard-step');
    const progressBar = document.querySelector('.wizard-progress-active');
    const stepLabel = document.getElementById('stepIndicatorLabel');
    let currentStepIdx = 0;

    const updateWizard = () => {
        steps.forEach((step, idx) => {
            step.classList.toggle('active', idx === currentStepIdx);
        });

        if (progressBar) {
            const percent = ((currentStepIdx + 1) / steps.length) * 100;
            progressBar.style.width = `${percent}%`;
        }

        if (stepLabel) {
            stepLabel.innerText = `Bước ${currentStepIdx + 1} / ${steps.length}`;
        }
    };

    window.nextWizardStep = () => {
        // Simple inputs verification
        const activeStep = steps[currentStepIdx];
        const requiredInputs = activeStep.querySelectorAll('[required]');
        let isValid = true;
        requiredInputs.forEach(input => {
            if (!input.value.trim()) {
                input.classList.add('border-red-500');
                isValid = false;
            } else {
                input.classList.remove('border-red-500');
            }
        });

        if (!isValid) return;

        if (currentStepIdx < steps.length - 1) {
            currentStepIdx++;
            updateWizard();
            syncPreviewCard();
        } else {
            wizardForm.submit();
        }
    };

    window.prevWizardStep = () => {
        if (currentStepIdx > 0) {
            currentStepIdx--;
            updateWizard();
        }
    };

    // Live sync inputs to Preview Card
    const syncPreviewCard = () => {
        const previewName = document.getElementById('previewCardName');
        const previewHeadline = document.getElementById('previewCardHeadline');
        const previewRole = document.getElementById('previewCardRole');
        const previewLocation = document.getElementById('previewCardLocation');

        const inputName = wizardForm.querySelector('input[name="fullname"]');
        const selectRole = wizardForm.querySelector('select[name="role"]');
        const inputLocation = wizardForm.querySelector('input[name="location"]');
        
        let headlineVal = "";
        if (selectRole && selectRole.value === 'job_seeker') {
            const inputHeadline = wizardForm.querySelector('input[name="headline"]');
            headlineVal = inputHeadline ? inputHeadline.value : "";
        } else if (selectRole && selectRole.value === 'employer') {
            const inputCompany = wizardForm.querySelector('input[name="company_name"]');
            headlineVal = `Chủ tiệm / Nhà tuyển dụng tại ${inputCompany ? inputCompany.value : ""}`;
        } else if (selectRole && selectRole.value === 'provider') {
            const inputSvc = wizardForm.querySelector('input[name="service_type"]');
            headlineVal = `Cung cấp dịch vụ: ${inputSvc ? inputSvc.value : ""}`;
        }

        if (previewName && inputName) previewName.innerText = inputName.value || "Tên của bạn";
        if (previewHeadline) previewHeadline.innerText = headlineVal || "Tiêu đề công việc";
        if (previewRole && selectRole) previewRole.innerText = selectRole.value.toUpperCase();
        if (previewLocation && inputLocation) previewLocation.innerText = inputLocation.value || "Khu vực hoạt động";
    };

    wizardForm.querySelectorAll('input, select, textarea').forEach(input => {
        input.addEventListener('input', syncPreviewCard);
    });
    
    // Listen for role toggle
    const selectRole = wizardForm.querySelector('select[name="role"]');
    if (selectRole) {
        selectRole.addEventListener('change', () => {
            const role = selectRole.value;
            document.querySelectorAll('[data-role-flow]').forEach(el => {
                el.style.display = el.dataset.roleFlow === role ? 'block' : 'none';
                el.querySelectorAll('[required-flow]').forEach(input => {
                    input.required = el.dataset.roleFlow === role;
                });
            });
            syncPreviewCard();
        });
        // trigger initial change
        selectRole.dispatchEvent(new Event('change'));
    }
}

// --- 3. WAITLIST / DYNAMIC TEXT TICKER ---
function initWaitlistCounter() {
    const listCount = document.getElementById('waitlistCounter');
    if (!listCount) return;

    // Simulate real-time signup counter increases
    let startVal = parseInt(localStorage.getItem('waitlist_count') || '14280');
    listCount.innerText = startVal.toLocaleString();

    setInterval(() => {
        if (Math.random() > 0.4) {
            startVal += Math.floor(Math.random() * 3) + 1;
            listCount.innerText = startVal.toLocaleString();
            localStorage.setItem('waitlist_count', startVal);
        }
    }, 6000);
}

// --- 4. CHAT MESSAGES INBOX SIMULATOR ---
function initChatSimulator() {
    const messageLog = document.getElementById('chatMessagesLog');
    const sendBtn = document.getElementById('chatSendBtn');
    const textInput = document.getElementById('chatInput');
    if (!messageLog || !sendBtn || !textInput) return;

    const appendMessage = (sender, content, isSelf = false) => {
        const wrap = document.createElement('div');
        wrap.className = `flex ${isSelf ? 'justify-end' : 'justify-start'}`;
        
        const card = document.createElement('div');
        card.className = `max-w-[70%] p-3.5 rounded-2xl text-xs leading-relaxed ${
            isSelf 
                ? 'bg-cyan-500/20 border border-cyan-500/30 text-cyan-200' 
                : 'bg-white/5 border border-white/10 text-gray-200'
        }`;
        card.innerHTML = `
            <span class="block font-black text-[9px] uppercase tracking-wider text-gray-500 mb-1">${sender}</span>
            <p>${content}</p>
        `;
        wrap.appendChild(card);
        messageLog.appendChild(wrap);
        messageLog.scrollTop = messageLog.scrollHeight;
    };

    window.triggerSendMessage = () => {
        const text = textInput.value.trim();
        if (!text) return;

        appendMessage('Bạn', text, true);
        textInput.value = '';

        // Bot responds trigger
        setTimeout(() => {
            let reply = "Tôi là AI Career Copilot của BitPaw. Bạn có thể hỏi tôi về hồ sơ nghề nghiệp, viết CV hoặc gợi ý công việc phù hợp.";
            if (text.toLowerCase().includes('nail') || text.toLowerCase().includes('việc làm')) {
                reply = "Gợi ý việc làm Nails đang tuyển gấp: **Thợ chính đắp bột Acrylic** tại *Bloom Nails Q3* (Lương 12tr - 18tr). Bạn có muốn tôi hỗ trợ viết thư giới thiệu không?";
            } else if (text.toLowerCase().includes('cv') || text.toLowerCase().includes('hồ sơ')) {
                reply = "Tôi thấy bạn có kỹ năng tốt về Nails. Tôi khuyên bạn nên bổ sung thêm hình ảnh dự án móng đã vẽ vào mục Gallery để tăng 40% tỉ lệ phản hồi từ nhà tuyển dụng.";
            }
            appendMessage('AI Copilot', reply);
        }, 1200);
    };

    sendBtn.addEventListener('click', window.triggerSendMessage);
    textInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') window.triggerSendMessage();
    });

    // Pinned chat initial greeting
    setTimeout(() => {
        appendMessage('AI Copilot', 'Chào mừng bạn đến với phòng hội thoại BitPaw Network! Tôi là AI Career Copilot. Tôi có thể hỗ trợ bạn tìm kiếm cơ hội và phân tích hồ sơ.');
    }, 500);
}

// --- 5. CV BUILDER WORKSPACE ---
function initCVBuilder() {
    const cvForm = document.getElementById('cvBuilderForm');
    if (!cvForm) return;

    window.previewCV = () => {
        const previewName = document.getElementById('cvPreviewName');
        const previewHeadline = document.getElementById('cvPreviewHeadline');
        const previewExp = document.getElementById('cvPreviewExp');
        const previewSkills = document.getElementById('cvPreviewSkills');
        const previewSalary = document.getElementById('cvPreviewSalary');

        const name = document.getElementById('cvName').value;
        const headline = document.getElementById('cvHeadline').value;
        const exp = document.getElementById('cvExperience').value;
        const skills = document.getElementById('cvSkills').value;
        const salary = document.getElementById('cvSalary').value;

        if (previewName) previewName.innerText = name || "Đặng Ngọc Minh Triết";
        if (previewHeadline) previewHeadline.innerText = headline || "Thợ Nails chính 3 năm kinh nghiệm";
        if (previewExp) previewExp.innerText = exp || "Kinh nghiệm làm việc của bạn";
        if (previewSalary) previewSalary.innerText = salary || "12.000.000đ - 15.000.000đ";
        
        if (previewSkills) {
            previewSkills.innerHTML = '';
            skills.split(',').forEach(skill => {
                if (skill.trim()) {
                    const span = document.createElement('span');
                    span.className = 'px-2 py-0.5 bg-black/40 border border-white/10 rounded text-[9px]';
                    span.innerText = skill.trim();
                    previewSkills.appendChild(span);
                }
            });
        }
    };

    cvForm.querySelectorAll('input, textarea').forEach(input => {
        input.addEventListener('input', window.previewCV);
    });

    window.downloadPDFMock = () => {
        alert('Đang biên dịch tệp PDF CV dạng Glassmorphism... Tải xuống thành công!');
    };
}
