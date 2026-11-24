document.addEventListener("DOMContentLoaded", () => {
    console.log("[PAGE]      페이지 로드 및 탭 초기화 완료");

    const globalErrorBox = document.getElementById("global-error-box");

    // 상태 저장소
    let tab1CurrentCode = "";
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

        if (role === "bot" && !isLoading && typeof marked !== "undefined") {
            msgEl.classList.add("markdown-body");
            const rawHtml = marked.parse(text || "");
            msgEl.innerHTML = typeof DOMPurify !== "undefined" ? DOMPurify.sanitize(rawHtml) : rawHtml;
        } else {
            msgEl.textContent = text;
        }

        container.appendChild(msgEl);
        container.scrollTop = container.scrollHeight;
        return msgEl;
    }

    function formatNumber(num, suffix = "") {
        if (num === null || num === undefined || Number.isNaN(num)) return "-";
        return `${Number(num).toLocaleString("ko-KR")}${suffix}`;
    }

    function formatPrice(num, currency = "KRW") {
        if (num === null || num === undefined || Number.isNaN(num)) return "-";
        if (currency === "USD") {
            return `$${Number(num).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
        }
        return `${Number(num).toLocaleString("ko-KR")}원`;
    }

    function attachAutocomplete(inputEl, listEl, onSelect) {
        let timer = null;

        inputEl.addEventListener("input", () => {
            const q = inputEl.value.trim();
            clearTimeout(timer);
            if (!q) {
                listEl.classList.add("hidden");
                listEl.innerHTML = "";
                return;
            }
            timer = setTimeout(async () => {
                try {
                    const res = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
                    const data = await res.json();
                    const items = data.items || [];
                    listEl.innerHTML = "";
                    if (items.length === 0) {
                        listEl.classList.add("hidden");
                        return;
                    }
                    items.forEach((item) => {
                        const li = document.createElement("li");
                        li.className = "autocomplete-item";

                        const nameSpan = document.createElement("span");
                        nameSpan.className = "ac-name";
                        nameSpan.textContent = item.name;

                        const metaSpan = document.createElement("span");
                        metaSpan.className = "ac-meta";
                        metaSpan.textContent = `${item.code} · ${item.exchange || item.nation}`;

                        li.appendChild(nameSpan);
                        li.appendChild(metaSpan);
                        li.addEventListener("mousedown", (e) => {
                            e.preventDefault();
                            inputEl.value = item.code;
                            listEl.classList.add("hidden");
                            onSelect(item.code);
                        });
                        listEl.appendChild(li);
                    });
                    listEl.classList.remove("hidden");
                } catch {
                    listEl.classList.add("hidden");
                }
            }, 220);
        });

        inputEl.addEventListener("blur", () => {
            setTimeout(() => listEl.classList.add("hidden"), 150);
        });
    }

    function formatKoreanAmount(num) {
        if (num === null || num === undefined || Number.isNaN(num)) return "-";
        const sign = num < 0 ? "-" : "";
        const abs = Math.abs(num);
        const jo = Math.floor(abs / 1e12);
        const eok = Math.round((abs % 1e12) / 1e8);

        if (jo > 0 && eok > 0) return `${sign}${jo.toLocaleString("ko-KR")}조 ${eok.toLocaleString("ko-KR")}억`;
        if (jo > 0) return `${sign}${jo.toLocaleString("ko-KR")}조`;
        if (eok > 0) return `${sign}${eok.toLocaleString("ko-KR")}억`;
        return `${sign}${abs.toLocaleString("ko-KR")}원`;
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
    // 1. 탭 1: 종목 심층분석 & AI 채팅 (Dify 챗봇①)
    // =========================================================
    const tab1SearchForm = document.getElementById("tab1-search-form");
    const tab1CodeInput = document.getElementById("tab1-code-input");
    const tab1BuyPriceInput = document.getElementById("tab1-buy-price-input");
    const tab1AnalyzeBtn = document.getElementById("tab1-analyze-btn");
    const tab1Loading = document.getElementById("tab1-loading");
    const tab1Warning = document.getElementById("tab1-warning");
    const tab1ResultArea = document.getElementById("tab1-result-area");
    const tab1DetailsToggle = document.getElementById("tab1-details-toggle");
    const tab1DetailsBox = document.getElementById("tab1-details-box");
    const tab1ChatLog = document.getElementById("tab1-chat-log");
    const tab1ChatForm = document.getElementById("tab1-chat-form");
    const tab1QuestionInput = document.getElementById("tab1-question-input");
    const tab1SendBtn = document.getElementById("tab1-send-btn");
    const tab1ResetBtn = document.getElementById("tab1-reset-btn");

    document.querySelectorAll(".tab1-chip").forEach((chip) => {
        chip.addEventListener("click", () => {
            const code = chip.getAttribute("data-code");
            tab1CodeInput.value = code;
            analyzeStock(code);
        });
    });

    const tab1Autocomplete = document.getElementById("tab1-autocomplete");
    attachAutocomplete(tab1CodeInput, tab1Autocomplete, (selectedCode) => {
        analyzeStock(selectedCode);
    });

    tab1BuyPriceInput.addEventListener("input", () => {
        const raw = tab1BuyPriceInput.value.replace(/[^\d.]/g, "");
        if (!raw) {
            tab1BuyPriceInput.value = "";
            return;
        }
        const parts = raw.split(".");
        const intPart = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ",");
        tab1BuyPriceInput.value = parts.length > 1 ? `${intPart}.${parts[1].slice(0, 2)}` : intPart;
    });

    tab1SearchForm.addEventListener("submit", (e) => {
        e.preventDefault();
        tab1Autocomplete.classList.add("hidden");
        analyzeStock(tab1CodeInput.value.trim());
    });

    tab1DetailsToggle.addEventListener("click", () => {
        const isHidden = tab1DetailsBox.classList.toggle("hidden");
        tab1DetailsToggle.textContent = isHidden
            ? "상세 실적 · 수급 · 리포트 · 뉴스 펼쳐보기 ▾"
            : "상세 실적 · 수급 · 리포트 · 뉴스 접기 ▴";
    });

    tab1ResetBtn.addEventListener("click", () => {
        tab1CurrentCode = "";
        tab1ConversationId = "";
        tab1CodeInput.value = "";
        tab1BuyPriceInput.value = "";
        tab1Warning.classList.add("hidden");
        tab1ResultArea.classList.add("hidden");
        tab1ChatLog.innerHTML = "";
    });

    function renderMyPositionBar(stockData, buyPriceRaw) {
        const bar = document.getElementById("tab1-my-position-bar");
        bar.className = "position-bar hidden";
        bar.textContent = "";

        const cleaned = String(buyPriceRaw || "").replace(/,/g, "").trim();
        const buyPrice = Number(cleaned);
        const curr = stockData.snapshot ? stockData.snapshot.current_price : null;
        if (!cleaned || Number.isNaN(buyPrice) || buyPrice <= 0 || !curr || curr <= 0) {
            return null;
        }

        const currency = stockData.currency || "KRW";
        const pnlPct = ((curr - buyPrice) / buyPrice) * 100;
        const breakevenPct = curr < buyPrice ? ((buyPrice - curr) / curr) * 100 : 0;

        bar.classList.remove("hidden");
        bar.classList.add(pnlPct >= 0 ? "is-profit" : "is-loss");
        const pnlText = `${pnlPct >= 0 ? "+" : ""}${pnlPct.toFixed(2)}%`;
        const extraText = breakevenPct > 0 ? ` | 본전 회복 필요 상승률: +${breakevenPct.toFixed(1)}%` : " | 현재 수익 구간";
        bar.textContent = `내 매수가: ${formatPrice(buyPrice, currency)} | 현재 손익률: ${pnlText}${extraText}`;
        return buyPrice;
    }

    async function analyzeStock(code) {
        hideGlobalError();
        tab1Warning.classList.add("hidden");

        if (!code) {
            const msg = "종목명 또는 종목코드를 입력해 주세요. (예: 애플, 삼성전자, 000660)";
            console.error(`[ERROR]     요청 중 오류 발생 (${msg})`);
            showGlobalError(msg);
            return;
        }

        const buyPriceRaw = tab1BuyPriceInput.value.trim();

        tab1CurrentCode = code;
        tab1ConversationId = "";
        tab1Loading.textContent = "1/2단계: 종목 시세 · 실적 · 공시 · 뉴스를 수집 중입니다...";
        tab1Loading.classList.remove("hidden");
        tab1ResultArea.classList.add("hidden");
        tab1AnalyzeBtn.disabled = true;

        try {
            // 1단계: 빠른 데이터 수집 (/fetch) 후 즉시 화면 렌더링
            const fetchRes = await fetch("/fetch", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ code }),
            });
            const stockData = await fetchRes.json();

            if (!fetchRes.ok) {
                throw new Error(stockData.error || `데이터 수집 실패 (HTTP ${fetchRes.status})`);
            }

            tab1CurrentCode = stockData.code || code;
            tab1CodeInput.value = tab1CurrentCode;
            renderTab1Evidence(stockData);
            const validBuyPrice = renderMyPositionBar(stockData, buyPriceRaw);
            console.log(`[COLLECT]   종목 근거 데이터 수집 완료 (${stockData.name})`);
            tab1Loading.classList.add("hidden");
            tab1ResultArea.classList.remove("hidden");

            // 2단계: 수집된 근거(+ 내 매수가)를 넘겨 Dify 전문가 리포트 생성
            tab1ChatLog.innerHTML = "";
            const loadingMsg = appendChatMessage(
                tab1ChatLog,
                validBuyPrice
                    ? `내 매수가(${formatPrice(validBuyPrice, stockData.currency)}) 기준으로 맞춤형 AI 리포트를 작성하고 있습니다...`
                    : "수집된 근거를 바탕으로 전문가 AI 리포트를 작성하고 있습니다...",
                "bot",
                true
            );

            const aiRes = await fetch("/api/chat/analysis", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    code: tab1CurrentCode,
                    mode: "init",
                    stock_data: stockData,
                    buy_price: validBuyPrice,
                }),
            });
            const aiData = await aiRes.json();

            loadingMsg.remove();
            if (!aiRes.ok) {
                throw new Error(aiData.error || `AI 분석 실패 (HTTP ${aiRes.status})`);
            }

            tab1ConversationId = aiData.conversation_id || "";
            console.log(`[DIFY]      Dify 챗봇 응답 수신 완료 (bot=analysis, conversation_id=${tab1ConversationId})`);
            appendChatMessage(tab1ChatLog, aiData.answer, "bot");
        } catch (err) {
            console.error(`[ERROR]     요청 중 오류 발생 (${err.message})`);
            if (tab1ResultArea.classList.contains("hidden")) {
                showGlobalError(err.message);
            } else {
                tab1ChatLog.innerHTML = "";
                appendChatMessage(tab1ChatLog, `AI 분석 오류: ${err.message}`, "bot");
            }
        } finally {
            tab1Loading.classList.add("hidden");
            tab1AnalyzeBtn.disabled = false;
        }
    }

    function renderTab1Evidence(data) {
        if (Array.isArray(data.errors) && data.errors.length > 0) {
            const messages = data.errors.map((e) => `[${e.section}] ${e.message}`).join(" | ");
            tab1Warning.textContent = `일부 데이터 수집에 제한이 있었습니다: ${messages}`;
            tab1Warning.classList.remove("hidden");
        }

        const currency = data.currency || "KRW";
        const snapshot = data.snapshot || {};
        document.getElementById("tab1-stock-name").textContent = data.name || "-";
        document.getElementById("tab1-code-badge").textContent = data.code || "000000";

        const sourceBar = document.getElementById("tab1-source-bar");
        sourceBar.innerHTML = "";
        const src = data.sources || {};
        const srcSpan = document.createElement("span");
        const dartSrcText = src.dart ? ` · ${src.dart}` : "";
        srcSpan.textContent = `데이터 출처: ${src.market || "네이버 증권"}${dartSrcText} · ${src.news || "Serper Google News"} | 수집 시각: ${src.collected_at || "-"}`;
        sourceBar.appendChild(srcSpan);
        if (src.naver_url) {
            const naverLink = document.createElement("a");
            naverLink.href = src.naver_url;
            naverLink.target = "_blank";
            naverLink.rel = "noopener noreferrer";
            naverLink.textContent = "네이버 증권 원본 ↗";
            sourceBar.appendChild(naverLink);
        }
        document.getElementById("tab1-current-price").textContent = formatPrice(snapshot.current_price, currency);

        const rateEl = document.getElementById("tab1-change-rate");
        const rate = snapshot.change_rate;
        rateEl.className = "change-rate";
        if (rate === null || rate === undefined) {
            rateEl.textContent = "-";
            rateEl.classList.add("is-flat");
        } else if (rate > 0) {
            rateEl.textContent = `+${rate}%`;
            rateEl.classList.add("is-rise");
        } else if (rate < 0) {
            rateEl.textContent = `${rate}%`;
            rateEl.classList.add("is-fall");
        } else {
            rateEl.textContent = "0.00%";
            rateEl.classList.add("is-flat");
        }

        const cons = data.consensus || {};
        const etf = snapshot.etf_info;
        let metrics = [];

        if (data.stock_type === "etf" && etf) {
            metrics = [
                { label: "순자산/시총", value: formatKoreanAmount(snapshot.market_cap), hint: "ETF 전체 규모" },
                { label: "NAV (순자산가치)", value: formatNumber(etf.nav, "원"), hint: "1주당 실제 자산가치" },
                { label: "총보수", value: formatNumber(etf.total_fee_pct, "%"), hint: "연간 운용 수수료" },
                { label: "괴리율", value: formatNumber(etf.deviation_rate_pct, "%"), hint: "시장가와 NAV 차이" },
                { label: "1년 수익률", value: formatNumber(etf.return_1y_pct, "%"), hint: "최근 12개월 성과" },
                { label: "분배율(배당)", value: formatNumber(snapshot.dividend_yield, "%"), hint: "연간 분배금 비율" },
                { label: "52주 최고", value: formatNumber(snapshot.high_52w, "원"), hint: "최근 1년 최고가" },
                { label: "52주 최저", value: formatNumber(snapshot.low_52w, "원"), hint: "최근 1년 최저가" },
                { label: "운용사", value: etf.issuer || "-", hint: "ETF 발행 운용사" },
            ];
        } else {
            const targetStr = cons.target_price
                ? `${formatPrice(cons.target_price, currency)}${cons.upside_pct !== undefined ? ` (${cons.upside_pct > 0 ? "+" : ""}${cons.upside_pct}%)` : ""}`
                : "-";
            metrics = [
                { label: "시가총액 (원화환산)", value: formatKoreanAmount(snapshot.market_cap), hint: "회사 전체 몸값" },
                { label: "증권사 목표주가", value: targetStr, hint: "애널리스트 평균 예상가" },
                { label: "투자의견 (5점 만점)", value: cons.opinion_score ? `${cons.opinion_score}점` : "-", hint: "4점 이상: 매수 우위" },
                { label: "52주 최고 / 최저", value: `${formatPrice(snapshot.high_52w, currency)} / ${formatPrice(snapshot.low_52w, currency)}`, hint: "최근 1년 주가 범위" },
                { label: "외인소진율", value: formatNumber(snapshot.foreign_rate, "%"), hint: "외국인 보유 비중" },
                { label: "PER (실적) / 추정PER", value: `${formatNumber(snapshot.per, "배")} / ${formatNumber(snapshot.cns_per, "배")}`, hint: "낮을수록 이익 대비 저평가" },
                { label: "PBR", value: formatNumber(snapshot.pbr, "배"), hint: "1배 미만이면 자산가치 이하" },
                { label: "BPS (주당순자산)", value: formatPrice(snapshot.bps, currency), hint: "청산 시 1주당 자산" },
                { label: "배당수익률", value: formatNumber(snapshot.dividend_yield, "%"), hint: "예금 금리와 비교 척도" },
            ];
        }

        const grid = document.getElementById("tab1-snapshot-grid");
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
            if (m.hint) {
                const hintEl = document.createElement("div");
                hintEl.className = "metric-hint";
                hintEl.textContent = m.hint;
                card.appendChild(hintEl);
            }
            grid.appendChild(card);
        });

        // 공통 실적 표 렌더링 헬퍼
        function fillFinanceTable(theadId, tbodyId, wrapId, rows) {
            const wrap = document.getElementById(wrapId);
            const thead = document.getElementById(theadId);
            const tbody = document.getElementById(tbodyId);
            thead.innerHTML = "";
            tbody.innerHTML = "";

            if (!rows || rows.length === 0) {
                wrap.classList.add("hidden");
                return;
            }
            wrap.classList.remove("hidden");

            const headRow = document.createElement("tr");
            const firstTh = document.createElement("th");
            firstTh.textContent = "항목";
            headRow.appendChild(firstTh);

            rows.forEach((item) => {
                const th = document.createElement("th");
                if (item.is_consensus) th.classList.add("consensus-col");
                th.textContent = item.period || "-";
                if (item.is_consensus) {
                    const badge = document.createElement("span");
                    badge.className = "e-tag";
                    badge.textContent = "E";
                    th.appendChild(badge);
                }
                headRow.appendChild(th);
            });
            thead.appendChild(headRow);

            const rowsSpec = [
                { label: "매출액", key: "revenue", formatter: formatKoreanAmount },
                { label: "영업이익", key: "operating_income", formatter: formatKoreanAmount },
                { label: "영업이익률", key: "operating_margin", formatter: (v) => formatNumber(v, "%") },
                { label: "ROE", key: "roe", formatter: (v) => formatNumber(v, "%") },
                { label: "부채비율", key: "debt_ratio", formatter: (v) => formatNumber(v, "%") },
                { label: "유보율", key: "reserve_ratio", formatter: (v) => formatNumber(v, "%") },
            ];
            rowsSpec.forEach((spec) => {
                const tr = document.createElement("tr");
                const nameTd = document.createElement("td");
                nameTd.textContent = spec.label;
                tr.appendChild(nameTd);
                rows.forEach((item) => {
                    const td = document.createElement("td");
                    if (item.is_consensus) td.classList.add("consensus-col");
                    td.textContent = spec.formatter(item[spec.key]);
                    tr.appendChild(td);
                });
                tbody.appendChild(tr);
            });
        }

        fillFinanceTable("tab1-finance-thead", "tab1-finance-tbody", "tab1-annual-wrap", data.financials || []);
        fillFinanceTable("tab1-quarter-thead", "tab1-quarter-tbody", "tab1-quarter-wrap", data.quarterly_financials || []);

        // 최근 5거래일 수급 동향 표
        const trendWrap = document.getElementById("tab1-trend-wrap");
        const trendTbody = document.getElementById("tab1-trend-tbody");
        const trend = data.investor_trend || [];
        trendTbody.innerHTML = "";
        if (trend.length > 0) {
            trendWrap.classList.remove("hidden");
            trend.forEach((d) => {
                const tr = document.createElement("tr");
                const dateTd = document.createElement("td");
                dateTd.textContent = d.date;
                const priceTd = document.createElement("td");
                priceTd.textContent = formatNumber(d.close_price, "원");
                tr.appendChild(dateTd);
                tr.appendChild(priceTd);

                [d.foreigner_net, d.organ_net, d.individual_net].forEach((val) => {
                    const td = document.createElement("td");
                    if (val !== null && val !== undefined) {
                        td.textContent = `${val > 0 ? "+" : ""}${Number(val).toLocaleString("ko-KR")}`;
                        if (val > 0) td.classList.add("num-pos");
                        else if (val < 0) td.classList.add("num-neg");
                    } else {
                        td.textContent = "-";
                    }
                    tr.appendChild(td);
                });
                trendTbody.appendChild(tr);
            });
        } else {
            trendWrap.classList.add("hidden");
        }

        // 동종 업종 비교
        const peersWrap = document.getElementById("tab1-peers-wrap");
        const peersGrid = document.getElementById("tab1-peers-grid");
        const peers = data.peers || [];
        peersGrid.innerHTML = "";
        if (peers.length > 0) {
            peersWrap.classList.remove("hidden");
            peers.forEach((p) => {
                const card = document.createElement("div");
                card.className = "metric-item";
                const lbl = document.createElement("div");
                lbl.className = "metric-label";
                lbl.textContent = `${p.name} (${p.code})`;
                const val = document.createElement("div");
                val.className = "metric-value";
                const rText = p.change_rate !== null ? ` (${p.change_rate > 0 ? "+" : ""}${p.change_rate}%)` : "";
                val.textContent = `${formatPrice(p.current_price, currency)}${rText}`;
                card.appendChild(lbl);
                card.appendChild(val);
                peersGrid.appendChild(card);
            });
        } else {
            peersWrap.classList.add("hidden");
        }

        // 증권사 최신 리포트
        const resWrap = document.getElementById("tab1-research-wrap");
        const resList = document.getElementById("tab1-research-list");
        const researches = data.researches || [];
        resList.innerHTML = "";
        if (researches.length > 0) {
            resWrap.classList.remove("hidden");
            researches.forEach((r) => {
                const li = document.createElement("li");
                li.className = "news-item";
                const link = document.createElement("a");
                link.className = "news-title";
                link.href = r.url || "#";
                link.target = "_blank";
                link.rel = "noopener noreferrer";
                link.textContent = `[${r.broker}] ${r.title}`;
                const meta = document.createElement("div");
                meta.className = "news-meta";
                meta.textContent = `발행일: ${r.date}`;
                li.appendChild(link);
                li.appendChild(meta);
                resList.appendChild(li);
            });
        } else {
            resWrap.classList.add("hidden");
        }

        // Open DART 기업개황 & 공식 공시
        const dartWrap = document.getElementById("tab1-dart-wrap");
        const dartProfileEl = document.getElementById("tab1-dart-profile");
        const dartListEl = document.getElementById("tab1-dart-list");
        const dart = data.dart;
        dartProfileEl.innerHTML = "";
        dartListEl.innerHTML = "";

        if (dart && (dart.profile || (dart.disclosures && dart.disclosures.length > 0))) {
            dartWrap.classList.remove("hidden");
            const prof = dart.profile || {};
            const profSpan = document.createElement("span");
            profSpan.textContent = `대표이사: ${prof.ceo_name || "-"} · 설립일: ${prof.established || "-"} · 결산월: ${prof.fiscal_month || "-"}`;
            dartProfileEl.appendChild(profSpan);
            if (prof.homepage) {
                const hpLink = document.createElement("a");
                hpLink.href = prof.homepage;
                hpLink.target = "_blank";
                hpLink.rel = "noopener noreferrer";
                hpLink.textContent = "공식 홈페이지 ↗";
                dartProfileEl.appendChild(hpLink);
            }

            (dart.disclosures || []).forEach((d) => {
                const li = document.createElement("li");
                li.className = "news-item";
                const link = document.createElement("a");
                link.className = "news-title";
                link.href = d.url || "#";
                link.target = "_blank";
                link.rel = "noopener noreferrer";
                link.textContent = d.title || "공시 제목 없음";
                const meta = document.createElement("div");
                meta.className = "news-meta";
                meta.textContent = `접수일: ${d.date || "-"} · 제출인: ${d.filer || "-"}`;
                li.appendChild(link);
                li.appendChild(meta);
                dartListEl.appendChild(li);
            });
        } else if (data.currency === "KRW" && data.stock_type !== "etf") {
            dartWrap.classList.remove("hidden");
            dartProfileEl.textContent = "DART 공식 공시 데이터가 없습니다. (서버 환경변수 DART_API_KEY 설정 여부를 확인해 주세요)";
        } else {
            dartWrap.classList.add("hidden");
        }

        // 뉴스 렌더링
        const news = data.news || [];
        const newsList = document.getElementById("tab1-news-list");
        document.getElementById("tab1-news-count").textContent = `${news.length}건`;
        newsList.innerHTML = "";

        if (news.length === 0) {
            const li = document.createElement("li");
            li.className = "news-item";
            li.textContent = "수집된 최신 뉴스가 없습니다.";
            newsList.appendChild(li);
        } else {
            news.forEach((article) => {
                const li = document.createElement("li");
                li.className = "news-item";
                const link = document.createElement("a");
                link.className = "news-title";
                link.href = article.url || "#";
                link.target = "_blank";
                link.rel = "noopener noreferrer";
                link.textContent = article.title || "제목 없음";
                li.appendChild(link);

                if (article.description) {
                    const desc = document.createElement("p");
                    desc.className = "news-desc";
                    desc.textContent = article.description;
                    li.appendChild(desc);
                }
                if (article.published) {
                    const meta = document.createElement("div");
                    meta.className = "news-meta";
                    meta.textContent = article.published;
                    li.appendChild(meta);
                }
                newsList.appendChild(li);
            });
        }
    }

    tab1ChatForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        hideGlobalError();

        const question = tab1QuestionInput.value.trim();
        if (!tab1CurrentCode) {
            showGlobalError("먼저 상단에서 종목코드를 조회하여 분석을 시작해 주세요.");
            return;
        }
        if (!question) {
            showGlobalError("질문 내용을 입력해 주세요.");
            return;
        }

        appendChatMessage(tab1ChatLog, question, "user");
        tab1QuestionInput.value = "";
        const loadingMsg = appendChatMessage(
            tab1ChatLog,
            "AI 애널리스트가 답변을 작성 중입니다...",
            "bot",
            true
        );
        tab1SendBtn.disabled = true;

        try {
            const res = await fetch("/api/chat/analysis", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    code: tab1CurrentCode,
                    question,
                    mode: "chat",
                    conversation_id: tab1ConversationId,
                }),
            });
            const data = await res.json();

            if (!res.ok) {
                throw new Error(data.error || `요청 실패 (HTTP ${res.status})`);
            }

            tab1ConversationId = data.conversation_id || tab1ConversationId;
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
        const src2 = data.source || {};
        document.getElementById("tab2-source-bar").textContent =
            `데이터 출처: ${src2.provider || "FinanceDataReader"} | 분석 기간: ${src2.period || "-"} | 계산 시각: ${src2.collected_at || "-"}`;
        document.getElementById("tab2-rationale").textContent = data.rationale;
        document.getElementById("tab2-allocation-example").textContent = data.allocation_example || "";

        const compareGrid = document.getElementById("tab2-compare-grid");
        compareGrid.innerHTML = "";

        const portfolios = [
            { title: "★ 최고 가성비 조합 (추천)", info: data.max_sharpe, highlight: true },
            { title: "🛡️ 마음 편한 안전 조합", info: data.min_volatility, highlight: false },
            { title: "⚖️ 똑같이 나누기 (1/N)", info: data.equal_weight, highlight: false },
        ];

        portfolios.forEach((p) => {
            const card = document.createElement("div");
            card.className = `compare-card${p.highlight ? " highlight" : ""}`;

            const h4 = document.createElement("h4");
            h4.textContent = p.title;
            card.appendChild(h4);

            const stats = [
                ["1년 기대수익률", `${p.info.expected_return_pct}%`],
                ["출렁임 (변동성)", `${p.info.volatility_pct}%`],
                ["가성비 점수 (샤프)", `${p.info.sharpe_ratio}`],
                ["최악의 낙폭 (MDD)", `${p.info.mdd_pct}%`],
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
                        label: "무작위 조합 (3,000회)",
                        data: simPoints,
                        backgroundColor: "rgba(148, 163, 184, 0.45)",
                        pointRadius: 3,
                    },
                    {
                        label: "★ 추천 (최고 가성비)",
                        data: [{ x: data.max_sharpe.volatility_pct, y: data.max_sharpe.expected_return_pct }],
                        backgroundColor: "#dc2626",
                        pointRadius: 8,
                    },
                    {
                        label: "안전 제일 (최소 변동성)",
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
                    x: { title: { display: true, text: "출렁임 / 위험도 (왼쪽일수록 안전, %)" } },
                    y: { title: { display: true, text: "1년 기대수익률 (위쪽일수록 수익 큼, %)" } },
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

    const tab3Autocomplete = document.getElementById("tab3-autocomplete");
    attachAutocomplete(tab3CodeInput, tab3Autocomplete, () => {
        loadTechnicalChart();
    });

    tab3Form.addEventListener("submit", (e) => {
        e.preventDefault();
        tab3Autocomplete.classList.add("hidden");
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
        const src3 = data.source || {};
        document.getElementById("tab3-source-bar").textContent =
            `데이터 출처: ${src3.provider || "FinanceDataReader"} | 조회 기간: ${src3.period || "-"} | 계산 시각: ${src3.collected_at || "-"}`;

        const currency3 = /^[A-Za-z]/.test(data.code || "") ? "USD" : "KRW";
        const metrics = [
            { label: "종가", value: formatPrice(latest.close, currency3) },
            { label: "MA5 / MA20", value: `${formatPrice(latest.ma5, currency3)} / ${formatPrice(latest.ma20, currency3)}` },
            { label: "MA60", value: formatPrice(latest.ma60, currency3) },
            { label: "RSI (14)", value: formatNumber(latest.rsi14) },
            { label: "MACD / Signal", value: `${formatNumber(latest.macd)} / ${formatNumber(latest.macd_signal)}` },
            { label: "볼린저 상/하단", value: `${formatPrice(latest.bb_upper, currency3)} / ${formatPrice(latest.bb_lower, currency3)}` },
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
