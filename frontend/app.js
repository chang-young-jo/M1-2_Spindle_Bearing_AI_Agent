
/* ==========================================
   Spindle Bearing AI Agent
   M1-2 Frontend JavaScript
========================================== */

const API_BASE = "https://m1-2-spindle-bearing-ai-agent.onrender.com";

let conversationId = null;
let vibrationRecords = [];
let editingDataId = null;
let chatBusy = false;


// ==========================================
// 1. 화면 전환
// ==========================================

function showPage(pageId) {
    document.querySelectorAll(".page").forEach(page => {
        page.classList.remove("active");
    });

    const target = document.getElementById(pageId);

    if (!target) return;

    target.classList.add("active");

    if (pageId === "data") {
        loadData();
    }

    if (pageId === "history") {
        loadConversations();
    }
}


// ==========================================
// 2. 채팅 메시지 표시
// ==========================================

function addMessage(role, content) {
    const chatBox = document.getElementById("chatMessages");

    const message = document.createElement("div");
    message.className = `message ${role}`;
    message.textContent = content;

    chatBox.appendChild(message);
    chatBox.scrollTop = chatBox.scrollHeight;
}


// ==========================================
// 3. 새 대화 시작
// ==========================================

function startNewConversation() {
    if (chatBusy) {
        alert("AI 답변이 완료된 후 새 대화를 시작하세요.");
        return;
    }

    conversationId = null;

    const chatBox = document.getElementById("chatMessages");
    chatBox.replaceChildren();

    const welcome = document.createElement("div");
    welcome.className = "welcome";
    welcome.textContent =
        "새 대화를 시작했습니다.\n진동 분석에 대해 질문해 주세요.";

    chatBox.appendChild(welcome);

    document.getElementById("chatInput").value = "";
    showPage("chat");
}


// ==========================================
// 4. AI 채팅
// ==========================================

async function sendMessage() {
    const input = document.getElementById("chatInput");
    const button = document.getElementById("sendButton");

    const message = input.value.trim();

    if (!message || chatBusy) return;

    chatBusy = true;
    button.disabled = true;
    button.textContent = "분석 중...";

    addMessage("user", message);
    input.value = "";

    try {
        const response = await fetch(`${API_BASE}/api/chat`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                message: message,
                conversation_id: conversationId
            })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(
                typeof data.detail === "string"
                    ? data.detail
                    : JSON.stringify(data.detail)
            );
        }

        conversationId = data.conversation_id;
        addMessage("assistant", data.answer);

    } catch (error) {
        addMessage(
            "assistant",
            `오류가 발생했습니다: ${error.message}`
        );
    } finally {
        chatBusy = false;
        button.disabled = false;
        button.textContent = "전송";
        input.focus();
    }
}


// ==========================================
// 5. 추천 질문
// ==========================================

function askExample(question) {
    if (chatBusy) return;

    document.getElementById("chatInput").value = question;
    sendMessage();
}


// ==========================================
// 6. 진동 데이터 조회
// ==========================================

async function loadData() {
    const countElement = document.getElementById("dataCount");
    const tbody = document.getElementById("dataTableBody");

    countElement.textContent = "데이터 조회 중...";
    tbody.replaceChildren();

    try {
        const response = await fetch(`${API_BASE}/api/data`);

        if (!response.ok) {
            throw new Error(`조회 실패 (${response.status})`);
        }

        const result = await response.json();
        vibrationRecords = result.data || [];

        const rpm = document.getElementById("rpmFilter").value;
        const axis = document.getElementById("axisFilter").value;

        const filtered = vibrationRecords.filter(record => {
            return (!rpm || String(record.rpm) === rpm) &&
                   (!axis || record.axis === axis);
        });

        countElement.textContent =
            `조회 ${filtered.length}개 / 전체 ${vibrationRecords.length}개`;

        for (const record of filtered) {
            const tr = document.createElement("tr");

            const values = [
                record.rpm ?? "-",
                record.axis ?? "-",
                record.elapsed_seconds ?? record.date ?? "-",
                record.value ?? "-"
            ];

            for (const value of values) {
                const td = document.createElement("td");
                td.textContent = String(value);
                tr.appendChild(td);
            }

            const actions = document.createElement("td");

            const editButton = document.createElement("button");
            editButton.textContent = "수정";
            editButton.addEventListener("click", () => {
                showEditForm(record.id);
            });

            const deleteButton = document.createElement("button");
            deleteButton.textContent = "삭제";
            deleteButton.className = "delete-btn";
            deleteButton.addEventListener("click", () => {
                deleteVibrationData(record.id);
            });

            actions.append(editButton, deleteButton);
            tr.appendChild(actions);
            tbody.appendChild(tr);
        }

    } catch (error) {
        countElement.textContent = `오류: ${error.message}`;
    }
}


// ==========================================
// 7. 데이터 추가 화면
// ==========================================

function showAddForm() {
    editingDataId = null;

    document.getElementById("formTitle").textContent =
        "진동 데이터 추가";

    document.getElementById("inputDate").value = "";
    document.getElementById("inputValue").value = "";
    document.getElementById("inputRpm").value = "";
    document.getElementById("inputAxis").value = "X";
    document.getElementById("inputMemo").value = "";

    document.getElementById("dataForm").hidden = false;
}


// ==========================================
// 8. 데이터 수정 화면
// ==========================================

function showEditForm(id) {
    const record = vibrationRecords.find(r => r.id === id);

    if (!record) {
        alert("수정할 데이터를 찾을 수 없습니다.");
        return;
    }

    editingDataId = id;

    document.getElementById("formTitle").textContent =
        "진동 데이터 수정";

    document.getElementById("inputDate").value =
        record.date || "";

    document.getElementById("inputValue").value =
        record.value ?? "";

    document.getElementById("inputRpm").value =
        record.rpm ?? "";

    document.getElementById("inputAxis").value =
        record.axis || "X";

    document.getElementById("inputMemo").value =
        record.memo || "";

    document.getElementById("dataForm").hidden = false;

    document.getElementById("dataForm").scrollIntoView({
        behavior: "smooth"
    });
}


// ==========================================
// 9. 입력 화면 닫기
// ==========================================

function cancelDataForm() {
    editingDataId = null;
    document.getElementById("dataForm").hidden = true;
}


// ==========================================
// 10. 데이터 저장
// ==========================================

async function saveData() {
    const date = document.getElementById("inputDate").value.trim();
    const valueText = document.getElementById("inputValue").value;
    const rpmText = document.getElementById("inputRpm").value;
    const axis = document.getElementById("inputAxis").value;
    const memo = document.getElementById("inputMemo").value;

    if (!date || valueText === "" || rpmText === "") {
        alert("시간, RMS, RPM을 모두 입력하세요.");
        return;
    }

    const value = Number(valueText);
    const rpm = Number(rpmText);

    if (!Number.isFinite(value) || value < 0 ||
        !Number.isInteger(rpm) || rpm <= 0) {
        alert("RMS와 RPM 값을 확인하세요.");
        return;
    }

    const record = { date, value, rpm, axis, memo };
    const isEdit = editingDataId !== null;

    if (isEdit && /^vibration_\d{4}$/.test(editingDataId)) {
        alert(
            "원본 측정 데이터는 이번 테스트에서 수정하지 않습니다.\n" +
            "새로운 테스트 데이터를 추가하여 확인하세요."
        );
        return;
    }

    const url = isEdit
        ? `${API_BASE}/api/data/${encodeURIComponent(editingDataId)}`
        : `${API_BASE}/api/data`;

    try {
        const response = await fetch(url, {
            method: isEdit ? "PUT" : "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify(record)
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(JSON.stringify(error.detail));
        }

        alert(isEdit ? "수정 완료" : "추가 완료");

        cancelDataForm();
        await loadData();

    } catch (error) {
        alert(`저장 실패: ${error.message}`);
    }
}


// ==========================================
// 11. 데이터 삭제
// ==========================================

async function deleteVibrationData(id) {
    if (/^vibration_\d{4}$/.test(id)) {
        alert(
            "기존 측정 데이터는 삭제할 수 없습니다.\n" +
            "테스트용으로 새로 추가한 데이터만 삭제하세요."
        );
        return;
    }

    if (!confirm(
        "선택한 데이터를 삭제하시겠습니까?\n" +
        "삭제한 데이터는 복구할 수 없습니다."
    )) {
        return;
    }

    try {
        const response = await fetch(
            `${API_BASE}/api/data/${encodeURIComponent(id)}`,
            { method: "DELETE" }
        );

        if (!response.ok) {
            throw new Error(`삭제 실패 (${response.status})`);
        }

        alert("데이터 삭제 완료");
        await loadData();

    } catch (error) {
        alert(error.message);
    }
}


// ==========================================
// 12. 대화 기록 목록 조회
// ==========================================

async function loadConversations() {
    const count = document.getElementById("historyCount");
    const container = document.getElementById("historyContent");

    count.textContent = "대화 기록 조회 중...";
    container.replaceChildren();

    try {
        const response = await fetch(
            `${API_BASE}/api/conversations`
        );

        if (!response.ok) {
            throw new Error(`조회 실패 (${response.status})`);
        }

        const result = await response.json();
        const conversations = result.conversations || [];

        count.textContent = `저장된 대화 ${conversations.length}개`;

        if (conversations.length === 0) {
            const empty = document.createElement("p");
            empty.className = "empty-state";
            empty.textContent =
                "저장된 대화가 없습니다. AI 채팅을 시작해 보세요.";
            container.appendChild(empty);
            return;
        }

        for (const conversation of conversations) {
            const card = document.createElement("div");
            card.className = "history-card";

            const title = document.createElement("h3");
            title.textContent =
                conversation.title || "제목 없는 대화";

            const meta = document.createElement("div");
            meta.className = "history-meta";

            const date = conversation.updated_at
                ? new Date(conversation.updated_at)
                    .toLocaleString("ko-KR")
                : "날짜 정보 없음";

            meta.textContent =
                `메시지 ${conversation.message_count ?? 0}개 · ${date}`;

            const actions = document.createElement("div");
            actions.className = "history-actions";

            const openButton = document.createElement("button");
            openButton.textContent = "대화 불러오기";
            openButton.addEventListener("click", () => {
                openConversation(conversation.id);
            });

            const deleteButton = document.createElement("button");
            deleteButton.textContent = "삭제";
            deleteButton.className = "delete-btn";
            deleteButton.addEventListener("click", () => {
                deleteConversation(conversation.id);
            });

            actions.append(openButton, deleteButton);
            card.append(title, meta, actions);
            container.appendChild(card);
        }

    } catch (error) {
        count.textContent = `대화 기록 오류: ${error.message}`;
    }
}


// ==========================================
// 13. 과거 대화 불러오기
// ==========================================

async function openConversation(id) {
    if (chatBusy) {
        alert("AI 답변이 완료된 후 대화를 불러오세요.");
        return;
    }

    try {
        const response = await fetch(
            `${API_BASE}/api/conversations/${encodeURIComponent(id)}`
        );

        if (!response.ok) {
            throw new Error(`불러오기 실패 (${response.status})`);
        }

        const data = await response.json();

        conversationId = data.id;

        const chatBox = document.getElementById("chatMessages");
        chatBox.replaceChildren();

        const messages = data.messages || [];

        if (messages.length === 0) {
            const welcome = document.createElement("div");
            welcome.className = "welcome";
            welcome.textContent =
                "저장된 메시지가 없습니다. 질문을 입력해 주세요.";
            chatBox.appendChild(welcome);
        }

        for (const msg of messages) {
            if (msg.role === "user" || msg.role === "assistant") {
                addMessage(msg.role, String(msg.content ?? ""));
            }
        }

        showPage("chat");
        document.getElementById("chatInput").focus();

    } catch (error) {
        alert(`대화 불러오기 오류: ${error.message}`);
    }
}


// ==========================================
// 14. 대화 기록 삭제
// ==========================================

async function deleteConversation(id) {
    if (chatBusy) {
        alert("AI 답변이 완료된 후 삭제하세요.");
        return;
    }

    if (!confirm(
        "이 대화 기록을 삭제하시겠습니까?\n" +
        "삭제 후에는 복구할 수 없습니다."
    )) {
        return;
    }

    try {
        const response = await fetch(
            `${API_BASE}/api/conversations/${encodeURIComponent(id)}`,
            { method: "DELETE" }
        );

        if (!response.ok) {
            throw new Error(`삭제 실패 (${response.status})`);
        }

        if (conversationId === id) {
            startNewConversation();
        }

        await loadConversations();

    } catch (error) {
        alert(`대화 삭제 오류: ${error.message}`);
    }
}


// ==========================================
// 15. Enter 키로 채팅 전송
// ==========================================

document.getElementById("chatInput")
    .addEventListener("keydown", function(event) {
        if (event.key === "Enter" && !event.isComposing) {
            sendMessage();
        }
    });


// ==========================================
// 16. 필터 변경 시 자동 조회
// ==========================================

document.getElementById("rpmFilter")
    .addEventListener("change", loadData);

document.getElementById("axisFilter")
    .addEventListener("change", loadData);
