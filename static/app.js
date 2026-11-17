document.addEventListener("DOMContentLoaded", () => {
    console.log("[PAGE]      페이지 로드 및 탭 초기화 완료");

    const globalErrorBox = document.getElementById("global-error-box");

    // 상태 저장소
    let tab1ConversationId = "";
    let tab3ConversationId = "";
    let tab3CurrentCode = "";
    let tab3LatestIndicators = null;

    // Chart.js 인스턴스 관리 (재계산 시 destroy)
    let weightChart = null;
    let frontierChart = null;
    let techPriceChart = null;
    let techRsiChart = null;
    let techMacdChart = null;

    function showGlobalError(msg) {
        globalErrorBox.textContent = msg;
        globalErrorBox.classList.remove("hidden");
    }

    function hideGlobalError() {
        globalErrorBox.classList.add("hidden");
        globalErrorBox.textContent = "";
    }

    function appendChatMessage(container, text, role, isLoading = false) {
        const msgEl = document.createElement("div");
        msgEl.className = `chat-msg ${role}${isLoading ? " loading-msg" : ""}`;
        msgEl.textContent = text;
        container.appendChild(msgEl);
        container.scrollTop = container.scrollHeight;
        return msgEl;
    }

    function formatNumber(num, suffix = "") {
        if (num === null || num === undefined || Number.isNaN(num)) return "-";
        return `${Number(num).toLocaleString("ko-KR")}${suffix}`;
    }

    // =========================================================
    // 0. 3탭 전환 로직
    // =========================================================
    const tabButtons = document.querySelectorAll(".tab-btn");
    const tabPanels = document.querySelectorAll(".tab-panel");

    tabButtons.forEach((btn) => {
        btn.addEventListener("click", () => {
            const targetTab = btn.getAttribute("data-tab");
            hideGlobalError();

            tabButtons.forEach((b) => b.classList.remove("active"));
            tabPanels.forEach((p) => p.classList.remove("active"));

            btn.classList.add("active");
            document.getElementById(targetTab).classList.add("active");
            console.log(`[TAB]       탭 전환 (${targetTab})`);
        });
    });

    // =========================================================
    // 1. 탭 1: 종목 심층분석 채팅 (Dify 챗봇①)
    // =========================================================
    const tab1CodeInput = document.getElementById("tab1-code-input");
    const tab1EvidenceBox = document.getElementById("tab1-evidence-box");
    const tab1ChatLog = document.getElementById("tab1-chat-log");
    const tab1ChatForm = document.getElementById("tab1-chat-form");
    const tab1QuestionInput = document.getElementById("tab1-question-input");
    const tab1SendBtn = document.getElementById("tab1-send-btn");
    const tab1ResetBtn = document.getElementById("tab1-reset-btn");

    document.querySelectorAll(".tab1-chip").forEach((chip) => {
        chip.addEventListener("click", () => {
            tab1CodeInput.value = chip.getAttribute("data-code");
        });
    });

    tab1ResetBtn.addEventListener("click", () => {
        tab1ConversationId = "";
        tab1EvidenceBox.classList.add("hidden");
        tab1ChatLog.innerHTML = "";
        appendChatMessage(
            tab1ChatLog,
            "새 대화를 시작합니다. 종목코드를 입력하고 질문을 남겨주세요.",
            "bot"
        );
    });

    tab1ChatForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        hideGlobalError();

        const code = tab1CodeInput.value.trim();
        const question = tab1QuestionInput.value.trim();

        if (!/^\d{6}$/.test(code)) {
            const msg = "종목코드는 6자리 숫자여야 합니다. (예: 000660)";
            console.error(`[ERROR]     요청 중 오류 발생 (${msg})`);
            showGlobalError(msg);
            return;
        }
        if (!question) {
            showGlobalError("질문 내용을 입력해 주세요.");
            return;
        }

        appendChatMessage(tab1ChatLog, `[${code}] ${question}`, "user");
        tab1QuestionInput.value = "";
        const loadingMsg = appendChatMessage(
            tab1ChatLog,
            "네이버 금융 지표와 최신 뉴스를 수집하여 AI가 분석 중입니다...",
            "bot",
            true
        );
        tab1SendBtn.disabled = true;

        try {
            const res = await fetch("/api/chat/analysis", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    code,
                    question,
                    conversation_id: tab1ConversationId,
                }),
            });
            const data = await res.json();

            if (data.stock_data) {
                const sd = data.stock_data;
                const price = sd.snapshot ? formatNumber(sd.snapshot.current_price, "원") : "-";
                const newsCount = (sd.news || []).length;
                tab1EvidenceBox.textContent = `수집 근거: ${sd.name} (${sd.code}) | 현재가 ${price} | 실적 ${(sd.financials || []).length}개년 | Serper 뉴스 ${newsCount}건`;
                tab1EvidenceBox.classList.remove("hidden");
                console.log(`[COLLECT]   종목 근거 데이터 수집 완료 (${sd.name})`);
            }

            if (!res.ok) {
                throw new Error(data.error || `요청 실패 (HTTP ${res.status})`);
            }

            tab1ConversationId = data.conversation_id || "";
            console.log(`[DIFY]      Dify 챗봇 응답 수신 완료 (bot=analysis, conversation_id=${tab1ConversationId})`);

            loadingMsg.remove();
            appendChatMessage(tab1ChatLog, data.answer, "bot");
        } catch (err) {
            loadingMsg.remove();
            console.error(`[ERROR]     요청 중 오류 발생 (${err.message})`);
            appendChatMessage(tab1ChatLog, `오류: ${err.message}`, "bot");
        } finally {
            tab1SendBtn.disabled = false;
        }
    });

    // =========================================================
    // 2. 탭 2: 리밸런싱 도우미 (Dify 없음 — 순수 Python 계산)
    // =========================================================
    const tab2Form = document.getElementById("tab2-form");
    const tab2CodesInput = document.getElementById("tab2-codes-input");
    const tab2CalcBtn = document.getElementById("tab2-calc-btn");
    const tab2Loading = document.getElementById("tab2-loading");
    const tab2Result = document.getElementById("tab2-result");

    document.querySelectorAll(".tab2-preset").forEach((btn) => {
        btn.addEventListener("click", () => {
            tab2CodesInput.value = btn.getAttribute("data-codes");
            runRebalancing();
        });
    });

    tab2Form.addEventListener("submit", (e) => {
        e.preventDefault();
        runRebalancing();
    });

    async function runRebalancing() {
        hideGlobalError();
        const raw = tab2CodesInput.value.trim();
        const codes = raw.split(",").map((s) => s.trim()).filter(Boolean);

        if (codes.length < 2) {
            const msg = "리밸런싱을 계산하려면 종목/ETF 코드를 쉼표로 구분해 2개 이상 입력해 주세요.";
            console.error(`[ERROR]     요청 중 오류 발생 (${msg})`);
            showGlobalError(msg);
            return;
        }

        tab2Loading.classList.remove("hidden");
        tab2Result.classList.add("hidden");
        tab2CalcBtn.disabled = true;

        try {
            const res = await fetch("/api/rebalance", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ codes }),
            });
            const data = await res.json();

            if (!res.ok) {
                throw new Error(data.error || `계산 실패 (HTTP ${res.status})`);
            }

            console.log(
                `[PORTFOLIO] 리밸런싱 시뮬레이션 완료 (${data.codes.length}종목, 최대 샤프 비중=${JSON.stringify(data.max_sharpe.weights)})`
            );
            renderRebalanceResult(data);
        } catch (err) {
            console.error(`[ERROR]     요청 중 오류 발생 (${err.message})`);
            showGlobalError(err.message);
        } finally {
            tab2Loading.classList.add("hidden");
            tab2CalcBtn.disabled = false;
        }
    }

    function renderRebalanceResult(data) {
        document.getElementById("tab2-meta-badge").textContent =
            `${data.trading_days}거래일 · ${data.simulations.toLocaleString("ko-KR")}회 시뮬레이션`;
        document.getElementById("tab2-rationale").textContent = data.rationale;

        const compareGrid = document.getElementById("tab2-compare-grid");
        compareGrid.innerHTML = "";

        const portfolios = [
            { title: "★ 최대 샤프 (추천)", info: data.max_sharpe, highlight: true },
            { title: "최소 변동성 (방어형)", info: data.min_volatility, highlight: false },
            { title: "동일 비중 (단순 분산)", info: data.equal_weight, highlight: false },
        ];

        portfolios.forEach((p) => {
            const card = document.createElement("div");
            card.className = `compare-card${p.highlight ? " highlight" : ""}`;

            const h4 = document.createElement("h4");
            h4.textContent = p.title;
            card.appendChild(h4);

            const stats = [
                ["기대 수익률(연)", `${p.info.expected_return_pct}%`],
                ["변동성(연)", `${p.info.volatility_pct}%`],
                ["샤프 지수", `${p.info.sharpe_ratio}`],
                ["최대 낙폭(MDD)", `${p.info.mdd_pct}%`],
            ];
            stats.forEach(([label, val]) => {
                const row = document.createElement("div");
                row.className = "compare-stat";
                const sp = document.createElement("span");
                sp.textContent = label;
                const st = document.createElement("strong");
                st.textContent = val;
                row.appendChild(sp);
                row.appendChild(st);
                card.appendChild(row);
            });

            compareGrid.appendChild(card);
        });

        // 종목별 성과 테이블
        const tbody = document.getElementById("tab2-asset-tbody");
        tbody.innerHTML = "";
        (data.asset_stats || []).forEach((item) => {
            const tr = document.createElement("tr");
            const cells = [
                item.code,
                `${item.annual_return_pct}%`,
                `${item.annual_volatility_pct}%`,
                `${item.mdd_pct}%`,
                `${item.recommended_weight_pct}%`,
            ];
            cells.forEach((text) => {
                const td = document.createElement("td");
                td.textContent = text;
                tr.appendChild(td);
            });
            tbody.appendChild(tr);
        });

        // 차트 1: 최대 샤프 비중 도넛 차트
        const weightCtx = document.getElementById("rebalance-weight-chart").getContext("2d");
        if (weightChart) weightChart.destroy();
        const labels = Object.keys(data.max_sharpe.weights);
        const values = Object.values(data.max_sharpe.weights);

        weightChart = new Chart(weightCtx, {
            type: "doughnut",
            data: {
                labels,
                datasets: [{
                    data: values,
                    backgroundColor: ["#2563eb", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#06b6d4"],
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: "bottom" },
                },
            },
        });

        // 차트 2: 효율적 프론티어 산점도
        const frontierCtx = document.getElementById("rebalance-frontier-chart").getContext("2d");
        if (frontierChart) frontierChart.destroy();

        const simPoints = (data.frontier_points || []).map((pt) => ({ x: pt.volatility, y: pt.return }));

        frontierChart = new Chart(frontierCtx, {
            type: "scatter",
            data: {
                datasets: [
                    {
                        label: "몬테카를로 포트폴리오",
                        data: simPoints,
                        backgroundColor: "rgba(148, 163, 184, 0.45)",
                        pointRadius: 3,
                    },
                    {
                        label: "★ 최대 샤프 (추천)",
                        data: [{ x: data.max_sharpe.volatility_pct, y: data.max_sharpe.expected_return_pct }],
                        backgroundColor: "#dc2626",
                        pointRadius: 8,
                    },
                    {
                        label: "최소 변동성",
                        data: [{ x: data.min_volatility.volatility_pct, y: data.min_volatility.expected_return_pct }],
                        backgroundColor: "#2563eb",
                        pointRadius: 7,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: { title: { display: true, text: "연환산 변동성 (%)" } },
                    y: { title: { display: true, text: "연환산 기대수익률 (%)" } },
                },
            },
        });

        tab2Result.classList.remove("hidden");
    }

    // =========================================================
    // 3. 탭 3: 기술지표 차트 + 지표해석기 채팅 (Dify 챗봇②)
    // =========================================================
    const tab3Form = document.getElementById("tab3-form");
    const tab3CodeInput = document.getElementById("tab3-code-input");
    const tab3LoadBtn = document.getElementById("tab3-load-btn");
    const tab3Loading = document.getElementById("tab3-loading");
    const tab3Result = document.getElementById("tab3-result");
    const tab3ChatLog = document.getElementById("tab3-chat-log");
    const tab3ChatForm = document.getElementById("tab3-chat-form");
    const tab3QuestionInput = document.getElementById("tab3-question-input");
    const tab3SendBtn = document.getElementById("tab3-send-btn");
    const tab3ResetBtn = document.getElementById("tab3-reset-btn");

    document.querySelectorAll(".tab3-chip").forEach((chip) => {
        chip.addEventListener("click", () => {
            tab3CodeInput.value = chip.getAttribute("data-code");
            loadTechnicalChart();
        });
    });

    tab3Form.addEventListener("submit", (e) => {
        e.preventDefault();
        loadTechnicalChart();
    });

    tab3ResetBtn.addEventListener("click", () => {
        tab3ConversationId = "";
        tab3ChatLog.innerHTML = "";
        appendChatMessage(
            tab3ChatLog,
            "새 대화를 시작합니다. 현재 계산된 기술지표에 대해 궁금한 점을 물어보세요!",
            "bot"
        );
    });

    async function loadTechnicalChart() {
        hideGlobalError();
        const code = tab3CodeInput.value.trim();
        if (!code) {
            showGlobalError("종목코드를 입력해 주세요.");
            return;
        }

        tab3Loading.classList.remove("hidden");
        tab3Result.classList.add("hidden");
        tab3LoadBtn.disabled = true;

        try {
            const res = await fetch("/api/technical", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ code }),
            });
            const data = await res.json();

            if (!res.ok) {
                throw new Error(data.error || `조회 실패 (HTTP ${res.status})`);
            }

            tab3CurrentCode = data.code;
            tab3LatestIndicators = data.latest;
            tab3ConversationId = "";

            renderTechnicalResult(data);
            console.log(`[TECH]      기술지표 계산 및 차트 렌더링 완료 (${data.code})`);
        } catch (err) {
            console.error(`[ERROR]     요청 중 오류 발생 (${err.message})`);
            showGlobalError(err.message);
        } finally {
            tab3Loading.classList.add("hidden");
            tab3LoadBtn.disabled = false;
        }
    }

    function renderTechnicalResult(data) {
        const latest = data.latest;
        const s = data.series;

        document.getElementById("tab3-title").textContent = `${data.code} 최신 기술지표 요약`;
        document.getElementById("tab3-date-badge").textContent = `기준일: ${latest.date}`;

        const metrics = [
            { label: "종가", value: formatNumber(latest.close, "원") },
            { label: "MA5 / MA20", value: `${formatNumber(latest.ma5)} / ${formatNumber(latest.ma20)}` },
            { label: "MA60", value: formatNumber(latest.ma60, "원") },
            { label: "RSI (14)", value: formatNumber(latest.rsi14) },
            { label: "MACD / Signal", value: `${formatNumber(latest.macd)} / ${formatNumber(latest.macd_signal)}` },
            { label: "볼린저 상/하단", value: `${formatNumber(latest.bb_upper)} / ${formatNumber(latest.bb_lower)}` },
        ];

        const grid = document.getElementById("tab3-latest-grid");
        grid.innerHTML = "";
        metrics.forEach((m) => {
            const card = document.createElement("div");
            card.className = "metric-item";
            const lbl = document.createElement("div");
            lbl.className = "metric-label";
            lbl.textContent = m.label;
            const val = document.createElement("div");
            val.className = "metric-value";
            val.textContent = m.value;
            card.appendChild(lbl);
            card.appendChild(val);
            grid.appendChild(card);
        });

        // 1. 주가 + MA + 볼린저밴드 차트
        const priceCtx = document.getElementById("tech-price-chart").getContext("2d");
        if (techPriceChart) techPriceChart.destroy();
        techPriceChart = new Chart(priceCtx, {
            type: "line",
            data: {
                labels: s.dates,
                datasets: [
                    { label: "종가", data: s.close, borderColor: "#0f172a", borderWidth: 2, pointRadius: 0 },
                    { label: "MA5", data: s.ma5, borderColor: "#ef4444", borderWidth: 1.5, pointRadius: 0 },
                    { label: "MA20", data: s.ma20, borderColor: "#2563eb", borderWidth: 1.5, pointRadius: 0 },
                    { label: "MA60", data: s.ma60, borderColor: "#10b981", borderWidth: 1.5, pointRadius: 0 },
                    { label: "BB 상단", data: s.bb_upper, borderColor: "#94a3b8", borderDash: [4, 4], borderWidth: 1, pointRadius: 0 },
                    { label: "BB 하단", data: s.bb_lower, borderColor: "#94a3b8", borderDash: [4, 4], borderWidth: 1, pointRadius: 0 },
                ],
            },
            options: { responsive: true, maintainAspectRatio: false },
        });

        // 2. RSI 차트
        const rsiCtx = document.getElementById("tech-rsi-chart").getContext("2d");
        if (techRsiChart) techRsiChart.destroy();
        techRsiChart = new Chart(rsiCtx, {
            type: "line",
            data: {
                labels: s.dates,
                datasets: [
                    { label: "RSI(14)", data: s.rsi14, borderColor: "#8b5cf6", borderWidth: 2, pointRadius: 0 },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: { y: { min: 0, max: 100 } },
            },
        });

        // 3. MACD 차트
        const macdCtx = document.getElementById("tech-macd-chart").getContext("2d");
        if (techMacdChart) techMacdChart.destroy();
        techMacdChart = new Chart(macdCtx, {
            type: "line",
            data: {
                labels: s.dates,
                datasets: [
                    { label: "MACD", data: s.macd, borderColor: "#2563eb", borderWidth: 2, pointRadius: 0 },
                    { label: "Signal", data: s.macd_signal, borderColor: "#f59e0b", borderWidth: 1.5, pointRadius: 0 },
                ],
            },
            options: { responsive: true, maintainAspectRatio: false },
        });

        tab3Result.classList.remove("hidden");
    }

    tab3ChatForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        hideGlobalError();

        const question = tab3QuestionInput.value.trim();
        if (!tab3CurrentCode || !tab3LatestIndicators) {
            showGlobalError("먼저 상단에서 종목의 차트와 지표를 조회해 주세요.");
            return;
        }
        if (!question) {
            showGlobalError("질문 내용을 입력해 주세요.");
            return;
        }

        appendChatMessage(tab3ChatLog, question, "user");
        tab3QuestionInput.value = "";
        const loadingMsg = appendChatMessage(
            tab3ChatLog,
            "계산된 기술지표를 바탕으로 Dify 지표해석기가 설명을 작성 중입니다...",
            "bot",
            true
        );
        tab3SendBtn.disabled = true;

        try {
            const res = await fetch("/api/chat/technical", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    code: tab3CurrentCode,
                    question,
                    indicators: tab3LatestIndicators,
                    conversation_id: tab3ConversationId,
                }),
            });
            const data = await res.json();

            if (!res.ok) {
                throw new Error(data.error || `요청 실패 (HTTP ${res.status})`);
            }

            tab3ConversationId = data.conversation_id || "";
            console.log(`[DIFY]      Dify 챗봇 응답 수신 완료 (bot=tech, conversation_id=${tab3ConversationId})`);

            loadingMsg.remove();
            appendChatMessage(tab3ChatLog, data.answer, "bot");
        } catch (err) {
            loadingMsg.remove();
            console.error(`[ERROR]     요청 중 오류 발생 (${err.message})`);
            appendChatMessage(tab3ChatLog, `오류: ${err.message}`, "bot");
        } finally {
            tab3SendBtn.disabled = false;
        }
    });
});
