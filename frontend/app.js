/*
 * Spindle Bearing AI Agent
 * frontend/app.js
 * 16-60단계: RAW 업로드 및 AI 자동 진단 기능 포함
 *
 * 기존 기능:
 * - AI 채팅
 * - Firebase 진동 데이터 관리
 * - 대화 기록
 * - 수동 베어링 주파수 분석
 *
 * 추가 기능:
 * - RAW 파일 업로드
 * - FFT / Envelope FFT 분석
 * - RPM별 RMS 그래프
 * - Python 판정 근거표
 * - AI 진단 보고서
 * - JSON 결과 다운로드
 */

const API_BASE =
    ["localhost", "127.0.0.1"].includes(window.location.hostname)
        ? "http://127.0.0.1:8000"
        : "https://m1-2-spindle-bearing-ai-agent.onrender.com";

let conversationId = null;
let vibrationRecords = [];
let editingDataId = null;
let chatBusy = false;

let bearingAnalysisForChat = null;
let latestBearingInput = null;
let latestBearingResult = null;

let latestRawResponse = null;
let rawUploadBusy = false;


// ==========================================
// 1. 공통 함수
// ==========================================

function formatHz(value) {
    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        return "-";
    }

    const number = Number(value);

    return Number.isFinite(number)
        ? String(Math.round(number))
        : "-";
}

function rawNumber(value, digits = 3) {
    const number = Number(value);

    if (
        value === null ||
        value === undefined ||
        !Number.isFinite(number)
    ) {
        return "-";
    }

    return number.toFixed(digits);
}

function getErrorMessage(data, status) {
    if (typeof data?.detail === "string") {
        return data.detail;
    }

    if (data?.detail) {
        return JSON.stringify(data.detail);
    }

    return `HTTP ${status}`;
}

async function readJsonResponse(response) {
    let data;

    try {
        data = await response.json();
    } catch (error) {
        throw new Error(
            `서버 응답을 읽을 수 없습니다. HTTP ${response.status}`
        );
    }

    if (!response.ok) {
        throw new Error(
            getErrorMessage(data, response.status)
        );
    }

    return data;
}

function rawCell(row, value, className = "") {
    const cell = document.createElement("td");

    cell.textContent = String(value ?? "-");

    if (className) {
        cell.className = className;
    }

    row.appendChild(cell);

    return cell;
}


// ==========================================
// 2. 화면 전환
// ==========================================

function showPage(pageId) {
    document.querySelectorAll(".page").forEach(page => {
        page.classList.remove("active");
    });

    const target = document.getElementById(pageId);

    if (!target) {
        return;
    }

    target.classList.add("active");

    if (pageId === "data") {
        loadData();
    }

    if (pageId === "history") {
        loadConversations();
    }
}


// ==========================================
// 3. AI 채팅 메시지 표시
// ==========================================

function addMessage(role, content) {
    const chatBox =
        document.getElementById("chatMessages");

    if (!chatBox) {
        return;
    }

    const message = document.createElement("div");

    message.className = `message ${role}`;
    message.textContent = String(content ?? "");

    chatBox.appendChild(message);
    chatBox.scrollTop = chatBox.scrollHeight;
}


// ==========================================
// 4. 새 대화
// ==========================================

function startNewConversation() {
    if (chatBusy) {
        alert(
            "AI 답변이 완료된 후 새 대화를 시작하세요."
        );
        return;
    }

    conversationId = null;
    bearingAnalysisForChat = null;

    const chatBox =
        document.getElementById("chatMessages");

    chatBox.replaceChildren();

    const welcome = document.createElement("div");

    welcome.className = "welcome";
    welcome.textContent =
        "새 대화를 시작했습니다.\n" +
        "진동 분석에 대해 질문해 주세요.";

    chatBox.appendChild(welcome);

    document.getElementById("chatInput").value = "";

    showPage("chat");
}


// ==========================================
// 5. AI 채팅
// ==========================================

async function sendMessage() {
    const input =
        document.getElementById("chatInput");

    const button =
        document.getElementById("sendButton");

    const message = input.value.trim();

    if (!message || chatBusy) {
        return;
    }

    chatBusy = true;
    button.disabled = true;
    button.textContent = "분석 중...";

    addMessage("user", message);

    input.value = "";

    try {
        const payload = {
            message: message,
            conversation_id: conversationId,
            include_raw_fft: true
        };

        if (bearingAnalysisForChat) {
            payload.bearing_analysis =
                bearingAnalysisForChat;
        }

        const response = await fetch(
            `${API_BASE}/api/chat`,
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify(payload)
            }
        );

        const data = await readJsonResponse(response);

        conversationId =
            data.conversation_id ?? conversationId;

        addMessage(
            "assistant",
            data.answer ?? "답변이 없습니다."
        );

        bearingAnalysisForChat = null;

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
// 6. 추천 질문
// ==========================================

function askExample(question) {
    if (chatBusy) {
        return;
    }

    document.getElementById("chatInput").value =
        question;

    sendMessage();
}


// ==========================================
// 7. 진동 데이터 조회
// ==========================================

async function loadData() {
    const countElement =
        document.getElementById("dataCount");

    const tbody =
        document.getElementById("dataTableBody");

    countElement.textContent =
        "데이터 조회 중...";

    tbody.replaceChildren();

    try {
        const response = await fetch(
            `${API_BASE}/api/data`
        );

        const result =
            await readJsonResponse(response);

        vibrationRecords =
            Array.isArray(result.data)
                ? result.data
                : [];

        const rpm =
            document.getElementById("rpmFilter").value;

        const axis =
            document.getElementById("axisFilter").value;

        const filtered = vibrationRecords.filter(
            record =>
                (!rpm || String(record.rpm) === rpm) &&
                (!axis || record.axis === axis)
        );

        countElement.textContent =
            `조회 ${filtered.length}개 / ` +
            `전체 ${vibrationRecords.length}개`;

        for (const record of filtered) {
            const tr = document.createElement("tr");

            const values = [
                record.rpm ?? "-",
                record.axis ?? "-",
                record.elapsed_seconds ??
                    record.date ??
                    "-",
                record.value ??
                    record.acc_rms_m_s2 ??
                    "-"
            ];

            for (const value of values) {
                rawCell(tr, value);
            }

            const actions =
                document.createElement("td");

            const editButton =
                document.createElement("button");

            editButton.textContent = "수정";

            editButton.addEventListener(
                "click",
                () => showEditForm(record.id)
            );

            const deleteButton =
                document.createElement("button");

            deleteButton.textContent = "삭제";
            deleteButton.className = "delete-btn";

            deleteButton.addEventListener(
                "click",
                () => deleteVibrationData(record.id)
            );

            actions.append(
                editButton,
                deleteButton
            );

            tr.appendChild(actions);
            tbody.appendChild(tr);
        }

    } catch (error) {
        countElement.textContent =
            `오류: ${error.message}`;
    }
}


// ==========================================
// 8. 데이터 추가
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

    document.getElementById("dataForm").hidden =
        false;
}


// ==========================================
// 9. 데이터 수정
// ==========================================

function showEditForm(id) {
    const record = vibrationRecords.find(
        item => item.id === id
    );

    if (!record) {
        alert("수정할 데이터를 찾을 수 없습니다.");
        return;
    }

    editingDataId = id;

    document.getElementById("formTitle").textContent =
        "진동 데이터 수정";

    document.getElementById("inputDate").value =
        record.date ?? "";

    document.getElementById("inputValue").value =
        record.value ??
        record.acc_rms_m_s2 ??
        "";

    document.getElementById("inputRpm").value =
        record.rpm ?? "";

    document.getElementById("inputAxis").value =
        record.axis ?? "X";

    document.getElementById("inputMemo").value =
        record.memo ?? "";

    const form =
        document.getElementById("dataForm");

    form.hidden = false;

    form.scrollIntoView({
        behavior: "smooth"
    });
}


// ==========================================
// 10. 데이터 입력 취소
// ==========================================

function cancelDataForm() {
    editingDataId = null;

    document.getElementById("dataForm").hidden =
        true;
}


// ==========================================
// 11. 데이터 저장
// ==========================================

async function saveData() {
    const date =
        document.getElementById("inputDate")
            .value.trim();

    const valueText =
        document.getElementById("inputValue").value;

    const rpmText =
        document.getElementById("inputRpm").value;

    const axis =
        document.getElementById("inputAxis").value;

    const memo =
        document.getElementById("inputMemo").value;

    if (
        !date ||
        valueText === "" ||
        rpmText === ""
    ) {
        alert(
            "시간, RMS, RPM을 모두 입력하세요."
        );
        return;
    }

    const value = Number(valueText);
    const rpm = Number(rpmText);

    if (
        !Number.isFinite(value) ||
        value < 0 ||
        !Number.isInteger(rpm) ||
        rpm <= 0
    ) {
        alert(
            "RMS와 RPM 값을 확인하세요."
        );
        return;
    }

    if (
        editingDataId !== null &&
        /^vibration_\d{4}$/.test(editingDataId)
    ) {
        alert(
            "원본 측정 데이터는 수정하지 않습니다."
        );
        return;
    }

    const record = {
        date,
        value,
        rpm,
        axis,
        memo
    };

    const isEdit =
        editingDataId !== null;

    const url = isEdit
        ? `${API_BASE}/api/data/${
            encodeURIComponent(editingDataId)
          }`
        : `${API_BASE}/api/data`;

    try {
        const response = await fetch(url, {
            method: isEdit ? "PUT" : "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify(record)
        });

        await readJsonResponse(response);

        alert(
            isEdit ? "수정 완료" : "추가 완료"
        );

        cancelDataForm();
        await loadData();

    } catch (error) {
        alert(
            `저장 실패: ${error.message}`
        );
    }
}


// ==========================================
// 12. 데이터 삭제
// ==========================================

async function deleteVibrationData(id) {
    if (/^vibration_\d{4}$/.test(id)) {
        alert(
            "기존 측정 데이터는 삭제할 수 없습니다."
        );
        return;
    }

    if (
        !confirm(
            "선택한 데이터를 삭제하시겠습니까?\n" +
            "삭제 후 복구할 수 없습니다."
        )
    ) {
        return;
    }

    try {
        const response = await fetch(
            `${API_BASE}/api/data/${
                encodeURIComponent(id)
            }`,
            {
                method: "DELETE"
            }
        );

        if (!response.ok) {
            throw new Error(
                `삭제 실패 (${response.status})`
            );
        }

        alert("데이터 삭제 완료");

        await loadData();

    } catch (error) {
        alert(error.message);
    }
}


// ==========================================
// 13. 대화 기록 목록
// ==========================================

async function loadConversations() {
    const count =
        document.getElementById("historyCount");

    const container =
        document.getElementById("historyContent");

    count.textContent =
        "대화 기록 조회 중...";

    container.replaceChildren();

    try {
        const response = await fetch(
            `${API_BASE}/api/conversations`
        );

        const result =
            await readJsonResponse(response);

        const conversations =
            result.conversations ?? [];

        count.textContent =
            `저장된 대화 ${conversations.length}개`;

        if (conversations.length === 0) {
            const empty =
                document.createElement("p");

            empty.className = "empty-state";
            empty.textContent =
                "저장된 대화가 없습니다.";

            container.appendChild(empty);
            return;
        }

        for (const conversation of conversations) {
            const card =
                document.createElement("div");

            card.className = "history-card";

            const title =
                document.createElement("h3");

            title.textContent =
                conversation.title ??
                "제목 없는 대화";

            const meta =
                document.createElement("div");

            meta.className = "history-meta";

            const date = conversation.updated_at
                ? new Date(
                    conversation.updated_at
                  ).toLocaleString("ko-KR")
                : "날짜 정보 없음";

            meta.textContent =
                `메시지 ${
                    conversation.message_count ?? 0
                }개 · ${date}`;

            const actions =
                document.createElement("div");

            actions.className = "history-actions";

            const openButton =
                document.createElement("button");

            openButton.textContent =
                "대화 불러오기";

            openButton.addEventListener(
                "click",
                () => openConversation(conversation.id)
            );

            const deleteButton =
                document.createElement("button");

            deleteButton.textContent = "삭제";
            deleteButton.className = "delete-btn";

            deleteButton.addEventListener(
                "click",
                () => deleteConversation(conversation.id)
            );

            actions.append(
                openButton,
                deleteButton
            );

            card.append(
                title,
                meta,
                actions
            );

            container.appendChild(card);
        }

    } catch (error) {
        count.textContent =
            `대화 기록 오류: ${error.message}`;
    }
}


// ==========================================
// 14. 과거 대화 불러오기
// ==========================================

async function openConversation(id) {
    if (chatBusy) {
        alert(
            "AI 답변이 완료된 후 불러오세요."
        );
        return;
    }

    try {
        const response = await fetch(
            `${API_BASE}/api/conversations/${
                encodeURIComponent(id)
            }`
        );

        const data =
            await readJsonResponse(response);

        conversationId = data.id;

        const chatBox =
            document.getElementById("chatMessages");

        chatBox.replaceChildren();

        const messages = data.messages ?? [];

        if (messages.length === 0) {
            const welcome =
                document.createElement("div");

            welcome.className = "welcome";
            welcome.textContent =
                "저장된 메시지가 없습니다.";

            chatBox.appendChild(welcome);
        }

        for (const msg of messages) {
            if (
                msg.role === "user" ||
                msg.role === "assistant"
            ) {
                addMessage(
                    msg.role,
                    msg.content ?? ""
                );
            }
        }

        showPage("chat");

        document.getElementById(
            "chatInput"
        ).focus();

    } catch (error) {
        alert(
            `대화 불러오기 오류: ${error.message}`
        );
    }
}


// ==========================================
// 15. 대화 기록 삭제
// ==========================================

async function deleteConversation(id) {
    if (chatBusy) {
        alert(
            "AI 답변이 완료된 후 삭제하세요."
        );
        return;
    }

    if (
        !confirm(
            "이 대화 기록을 삭제하시겠습니까?\n" +
            "삭제 후 복구할 수 없습니다."
        )
    ) {
        return;
    }

    try {
        const response = await fetch(
            `${API_BASE}/api/conversations/${
                encodeURIComponent(id)
            }`,
            {
                method: "DELETE"
            }
        );

        if (!response.ok) {
            throw new Error(
                `삭제 실패 (${response.status})`
            );
        }

        if (conversationId === id) {
            startNewConversation();
        }

        await loadConversations();

    } catch (error) {
        alert(
            `대화 삭제 오류: ${error.message}`
        );
    }
}


// ==========================================
// 16. 베어링 예제 입력
// ==========================================

function fillBearingExample() {
    document.getElementById("bearingRpm").value =
        "2000";

    document.getElementById("bearingPeaks").value =
        "168.34";

    const status =
        document.getElementById("bearingStatus");

    status.textContent =
        "예시 입력값입니다. " +
        "실제 측정 결과와 구분해 주세요.";

    status.className = "bearing-status";

    document.getElementById(
        "bearingResults"
    ).hidden = true;

    document.getElementById(
        "bearingAiButton"
    ).disabled = true;

    latestBearingInput = null;
    latestBearingResult = null;
}


// ==========================================
// 17. 수동 베어링 주파수 분석
// ==========================================

async function analyzeBearing() {
    const rpmElement =
        document.getElementById("bearingRpm");

    const peaksElement =
        document.getElementById("bearingPeaks");

    const rpm = Number(rpmElement.value);
    const raw = peaksElement.value.trim();

    const tokens = raw
        .split(/[,\s;]+/)
        .filter(Boolean);

    const peaks = tokens.map(Number);

    const status =
        document.getElementById("bearingStatus");

    const button =
        document.getElementById(
            "bearingAnalyzeButton"
        );

    const aiButton =
        document.getElementById(
            "bearingAiButton"
        );

    const results =
        document.getElementById(
            "bearingResults"
        );

    status.className = "bearing-status";
    results.hidden = true;
    aiButton.disabled = true;

    latestBearingInput = null;
    latestBearingResult = null;

    if (
        !rpmElement.value.trim() ||
        !Number.isFinite(rpm) ||
        rpm <= 0
    ) {
        status.className =
            "bearing-status error";

        status.textContent =
            "올바른 양수 RPM을 입력하세요.";

        return;
    }

    if (
        tokens.length === 0 ||
        peaks.some(
            value =>
                !Number.isFinite(value) ||
                value < 0
        )
    ) {
        status.className =
            "bearing-status error";

        status.textContent =
            "0 이상의 FFT 피크 주파수를 입력하세요.";

        return;
    }

    if (peaks.length > 20000) {
        status.className =
            "bearing-status error";

        status.textContent =
            "피크는 최대 20,000개까지 입력 가능합니다.";

        return;
    }

    const payload = {
        rpm: rpm,
        peak_frequencies_hz: peaks,
        tolerance_hz: 1.0
    };

    button.disabled = true;

    status.textContent =
        "베어링 결함 주파수 분석 중...";

    try {
        const response = await fetch(
            `${API_BASE}/api/bearing/analyze`,
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify(payload)
            }
        );

        const result =
            await readJsonResponse(response);

        const matches =
            result.frequency_matches ?? {};

        const tbody =
            document.getElementById(
                "bearingResultBody"
            );

        tbody.replaceChildren();

        let matchCount = 0;

        for (
            const name of [
                "FTF",
                "BPFO",
                "BPFI",
                "BSF"
            ]
        ) {
            const item = matches[name];

            if (!item) {
                continue;
            }

            const tr =
                document.createElement("tr");

            const matched =
                item.matched === true;

            const values = [
                name,
                formatHz(item.theoretical_hz),
                formatHz(item.measured_hz),
                formatHz(item.difference_hz),
                matched
                    ? "주파수 일치"
                    : "주파수 불일치"
            ];

            values.forEach(
                (value, index) => {
                    const td =
                        document.createElement("td");

                    td.textContent = value;

                    if (index === 4) {
                        td.className = matched
                            ? "bearing-match"
                            : "bearing-no-match";
                    }

                    tr.appendChild(td);
                }
            );

            tbody.appendChild(tr);

            if (matched) {
                matchCount++;
            }
        }

        if (!tbody.children.length) {
            throw new Error(
                "주파수 비교 결과가 없습니다."
            );
        }

        latestBearingInput = payload;
        latestBearingResult = result;

        results.hidden = false;
        aiButton.disabled = false;

        status.className =
            "bearing-status success";

        status.textContent =
            `분석 완료: ${formatHz(rpm)} RPM · ` +
            `피크 ${peaks.length}개 · ` +
            `일치 항목 ${matchCount}개 / 4개 ` +
            `(허용오차 ±1 Hz)`;

    } catch (error) {
        status.className =
            "bearing-status error";

        status.textContent =
            `분석 실패: ${error.message}`;

    } finally {
        button.disabled = false;
    }
}


// ==========================================
// 18. 베어링 분석 결과 AI 해석
// ==========================================

function requestBearingAI() {
    if (
        !latestBearingInput ||
        !latestBearingResult
    ) {
        alert(
            "먼저 베어링 주파수 분석을 실행하세요."
        );
        return;
    }

    if (chatBusy) {
        alert(
            "진행 중인 AI 답변이 완료된 후 다시 시도하세요."
        );
        return;
    }

    bearingAnalysisForChat = {
        rpm: latestBearingInput.rpm,
        peak_frequencies_hz:
            latestBearingInput.peak_frequencies_hz
    };

    const rpm = latestBearingInput.rpm;

    const peaks =
        latestBearingInput.peak_frequencies_hz;

    const peakText = peaks
        .map(value => formatHz(value))
        .join(", ");

    showPage("chat");

    document.getElementById("chatInput").value =
        `${formatHz(rpm)} RPM의 FFT 피크 ` +
        `${peakText} Hz에 대한 ` +
        "BPFO, BPFI, BSF, FTF 주파수 일치 여부를 " +
        "±1 Hz 기준으로 분석해줘. " +
        "모든 주파수는 정수 Hz로 표시하고, " +
        "일치 판정은 원본 정밀도 값으로 계산해줘. " +
        "주파수 일치와 실제 베어링 결함 확정을 " +
        "구분하고 추가 점검 사항을 설명해줘. " +
        "현재 입력값은 사용자가 제공한 FFT 피크이며 " +
        "RAW 데이터 자동 FFT 분석 결과는 아닙니다.";

    sendMessage();
}


// ==========================================
// 19. 수동 분석 입력 변경
// ==========================================

function invalidateBearingAnalysis() {
    latestBearingInput = null;
    latestBearingResult = null;
    bearingAnalysisForChat = null;

    const aiButton =
        document.getElementById(
            "bearingAiButton"
        );

    const results =
        document.getElementById(
            "bearingResults"
        );

    const status =
        document.getElementById(
            "bearingStatus"
        );

    if (aiButton) {
        aiButton.disabled = true;
    }

    if (results) {
        results.hidden = true;
    }

    if (status) {
        status.className = "bearing-status";

        status.textContent =
            "입력값이 변경되었습니다. " +
            "다시 분석해 주세요.";
    }
}


// ==========================================
// 20. RAW 파일 업로드 및 AI 자동 진단
// ==========================================

async function analyzeRawUpload() {
    if (rawUploadBusy) {
        return;
    }

    const input =
        document.getElementById("rawFile");

    const file = input?.files?.[0];

    const status =
        document.getElementById("rawStatus");

    const button =
        document.getElementById(
            "rawAnalyzeButton"
        );

    const download =
        document.getElementById(
            "rawDownloadButton"
        );

    if (!file) {
        status.className =
            "bearing-status error";

        status.textContent =
            "먼저 RAW 파일을 선택하세요.";

        return;
    }

    if (!/\.(lst|csv)$/i.test(file.name)) {
        status.className =
            "bearing-status error";

        status.textContent =
            ".lst 또는 .csv 파일만 업로드할 수 있습니다.";

        return;
    }

    if (file.size > 70 * 1024 * 1024) {
        status.className =
            "bearing-status error";

        status.textContent =
            "파일 크기는 최대 70 MB입니다.";

        return;
    }

    rawUploadBusy = true;
    latestRawResponse = null;

    button.disabled = true;
    download.disabled = true;

    document.getElementById(
        "rawResults"
    ).hidden = true;

    status.className = "bearing-status";

    status.textContent =
        "RAW 파일 업로드 및 AI 분석 중입니다. " +
        "창을 닫지 마세요...";

    try {
        const form = new FormData();

        form.append(
            "file",
            file,
            file.name
        );

        const response = await fetch(
            `${API_BASE}/api/bearing/upload-diagnose`,
            {
                method: "POST",
                body: form
            }
        );

        const result =
            await readJsonResponse(response);

        if (
            !Array.isArray(
                result?.analysis?.results
            ) ||
            !Array.isArray(
                result?.evidence_summary?.results
            )
        ) {
            throw new Error(
                "서버 응답에 분석 결과 또는 " +
                "판정 근거표가 없습니다."
            );
        }

        latestRawResponse = result;

        renderRawResults(result);

        document.getElementById(
            "rawResults"
        ).hidden = false;

        download.disabled = false;

        status.className =
            "bearing-status success";

        status.textContent =
            `분석 완료: ${file.name} · ` +
            `${result.analysis.results.length}개 ` +
            "RPM/방향 조합";

    } catch (error) {
        status.className =
            "bearing-status error";

        status.textContent =
            `분석 실패: ${error.message}`;

    } finally {
        rawUploadBusy = false;
        button.disabled = false;
    }
}


// ==========================================
// 21. RAW 분석 결과 표시
// ==========================================

function renderRawResults(result) {
    const analysis = result.analysis;

    const meta =
        document.getElementById("rawMeta");

    meta.textContent =
        `파일: ${
            result.filename ??
            analysis.filename ??
            "-"
        } · ` +
        `샘플링: ${
            analysis.sample_rate_hz ?? "-"
        } Hz · ` +
        `데이터 행: ${
            analysis.total_rows ?? "-"
        } · ` +
        `AI 모델: ${result.model ?? "-"}`;

    const notice =
        document.getElementById("rawNotice");

    notice.textContent =
        result.diagnostic_notice ??
        "탐색용 분석이며 베어링 결함을 " +
        "확정할 수 없습니다.";

    const body =
        document.getElementById("rawRmsBody");

    body.replaceChildren();

    const sorted = [...analysis.results].sort(
        (a, b) =>
            a.rpm - b.rpm ||
            a.axis.localeCompare(b.axis)
    );

    for (const item of sorted) {
        const tr =
            document.createElement("tr");

        rawCell(tr, item.rpm);
        rawCell(tr, item.axis);

        rawCell(
            tr,
            rawNumber(item.rms_m_s2, 6)
        );

        rawCell(
            tr,
            rawNumber(
                item.firebase_comparison_rms_0_1s_mean_m_s2,
                6
            )
        );

        body.appendChild(tr);
    }

    renderRawChart(sorted);
    renderRawPeaks();

    document.getElementById(
        "rawReport"
    ).textContent =
        result.report ??
        "AI 진단 보고서가 없습니다.";
}


// ==========================================
// 22. RPM별 RMS 그래프
// ==========================================

function renderRawChart(items) {
    const chart =
        document.getElementById(
            "rawRmsChart"
        );

    chart.replaceChildren();

    const max = Math.max(
        0.001,
        ...items.map(
            item =>
                Number(item.rms_m_s2) || 0
        )
    );

    const rpmValues = [
        ...new Set(
            items.map(item => item.rpm)
        )
    ].sort((a, b) => a - b);

    for (const rpm of rpmValues) {
        const group =
            document.createElement("div");

        group.className =
            "raw-chart-group";

        const heading =
            document.createElement("strong");

        heading.textContent =
            `${rpm} RPM`;

        group.appendChild(heading);

        const rpmItems = items.filter(
            item => item.rpm === rpm
        );

        for (const item of rpmItems) {
            const row =
                document.createElement("div");

            row.className = "raw-bar-row";

            const axis =
                document.createElement("span");

            axis.textContent = item.axis;

            const track =
                document.createElement("div");

            track.className =
                "raw-bar-track";

            const bar =
                document.createElement("div");

            bar.className =
                `raw-bar raw-bar-${
                    item.axis.toLowerCase()
                }`;

            const width = Math.max(
                0,
                Math.min(
                    100,
                    Number(item.rms_m_s2) /
                        max *
                        100
                )
            );

            bar.style.width =
                `${width}%`;

            track.appendChild(bar);

            const value =
                document.createElement("span");

            value.textContent =
                rawNumber(
                    item.rms_m_s2,
                    3
                );

            row.append(
                axis,
                track,
                value
            );

            group.appendChild(row);
        }

        chart.appendChild(group);
    }
}


// ==========================================
// 23. FFT 및 Envelope FFT 판정표
// ==========================================

function renderRawPeaks() {
    if (!latestRawResponse) {
        return;
    }

    const rpm =
        document.getElementById(
            "rawRpmFilter"
        ).value;

    const axis =
        document.getElementById(
            "rawAxisFilter"
        ).value;

    const method =
        document.getElementById(
            "rawMethodFilter"
        ).value;

    const body =
        document.getElementById(
            "rawPeakBody"
        );

    body.replaceChildren();

    const evidence =
        latestRawResponse.evidence_summary;

    for (const item of evidence.results) {
        if (
            rpm !== "all" &&
            String(item.rpm) !== rpm
        ) {
            continue;
        }

        if (
            axis !== "all" &&
            item.axis !== axis
        ) {
            continue;
        }

        const methods =
            item.frequency_candidates ?? {};

        for (
            const [
                methodName,
                candidates
            ] of Object.entries(methods)
        ) {
            if (
                method !== "all" &&
                methodName !== method
            ) {
                continue;
            }

            for (
                const name of [
                    "FTF",
                    "BPFO",
                    "BPFI",
                    "BSF"
                ]
            ) {
                const candidate =
                    candidates[name];

                if (!candidate) {
                    continue;
                }

                const tr =
                    document.createElement("tr");

                rawCell(tr, item.rpm);
                rawCell(tr, item.axis);
                rawCell(tr, methodName);
                rawCell(tr, name);

                rawCell(
                    tr,
                    formatHz(
                        candidate.theoretical_hz
                    )
                );

                rawCell(
                    tr,
                    formatHz(
                        candidate.measured_hz
                    )
                );

                rawCell(
                    tr,
                    rawNumber(
                        candidate.snr_db,
                        1
                    )
                );

                const strong =
                    candidate.exploratory_strong_peak ===
                    true;

                rawCell(
                    tr,
                    strong
                        ? "강한 탐색 피크"
                        : "강한 탐색 피크 아님",
                    strong
                        ? "bearing-match"
                        : "bearing-no-match"
                );

                body.appendChild(tr);
            }
        }
    }

    if (!body.children.length) {
        const tr =
            document.createElement("tr");

        const td =
            document.createElement("td");

        td.colSpan = 8;
        td.textContent =
            "선택한 조건에 해당하는 결과가 없습니다.";

        tr.appendChild(td);
        body.appendChild(tr);
    }
}


// ==========================================
// 24. RAW 분석 결과 JSON 다운로드
// ==========================================

function downloadRawJson() {
    if (!latestRawResponse) {
        alert(
            "먼저 RAW 파일 분석을 실행하세요."
        );
        return;
    }

    const json = JSON.stringify(
        latestRawResponse,
        null,
        2
    );

    const blob = new Blob(
        [json],
        {
            type:
                "application/json;charset=utf-8"
        }
    );

    const url =
        URL.createObjectURL(blob);

    const link =
        document.createElement("a");

    link.href = url;

    const timestamp = new Date()
        .toISOString()
        .replace(/[:.]/g, "-");

    link.download =
        `spindle_raw_diagnosis_${timestamp}.json`;

    document.body.appendChild(link);

    link.click();
    link.remove();

    setTimeout(
        () => URL.revokeObjectURL(url),
        1000
    );
}


// ==========================================
// 25. 이벤트 등록
// ==========================================

document.addEventListener(
    "DOMContentLoaded",
    () => {
        // AI 채팅 Enter 전송
        const chatInput =
            document.getElementById(
                "chatInput"
            );

        if (chatInput) {
            chatInput.addEventListener(
                "keydown",
                event => {
                    if (
                        event.key === "Enter" &&
                        !event.isComposing
                    ) {
                        sendMessage();
                    }
                }
            );
        }

        // Firebase 데이터 필터
        const rpmFilter =
            document.getElementById(
                "rpmFilter"
            );

        if (rpmFilter) {
            rpmFilter.addEventListener(
                "change",
                loadData
            );
        }

        const axisFilter =
            document.getElementById(
                "axisFilter"
            );

        if (axisFilter) {
            axisFilter.addEventListener(
                "change",
                loadData
            );
        }

        // 수동 베어링 입력 변경
        for (
            const id of [
                "bearingRpm",
                "bearingPeaks"
            ]
        ) {
            const element =
                document.getElementById(id);

            if (element) {
                element.addEventListener(
                    "input",
                    invalidateBearingAnalysis
                );
            }
        }

        // RAW 분석 결과 필터
        for (
            const id of [
                "rawRpmFilter",
                "rawAxisFilter",
                "rawMethodFilter"
            ]
        ) {
            const element =
                document.getElementById(id);

            if (element) {
                element.addEventListener(
                    "change",
                    renderRawPeaks
                );
            }
        }
    }
);