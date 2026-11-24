document.addEventListener("DOMContentLoaded", () => {
    console.log("[PAGE]    페이지 로드 완료");

    const searchForm = document.getElementById("search-form");
    const codeInput = document.getElementById("stock-code-input");
    const fetchBtn = document.getElementById("fetch-btn");
    const loadingBox = document.getElementById("loading-box");
    const errorBox = document.getElementById("error-box");
    const warningBox = document.getElementById("warning-box");
    const resultArea = document.getElementById("result-area");

    const chipButtons = document.querySelectorAll(".chip-btn");
    chipButtons.forEach((btn) => {
        btn.addEventListener("click", () => {
            const code = btn.getAttribute("data-code");
            codeInput.value = code;
            requestStockData(code);
        });
    });

    searchForm.addEventListener("submit", (e) => {
        e.preventDefault();
        const code = codeInput.value.trim();
        requestStockData(code);
    });

    function showError(message) {
        errorBox.textContent = message;
        errorBox.classList.remove("hidden");
    }

    function hideStatusBoxes() {
        errorBox.classList.add("hidden");
        warningBox.classList.add("hidden");
        warningBox.textContent = "";
    }

    function formatNumber(num) {
        if (num === null || num === undefined || Number.isNaN(num)) return "-";
        return Number(num).toLocaleString("ko-KR");
    }

    function formatKoreanAmount(num) {
        if (num === null || num === undefined || Number.isNaN(num)) return "-";
        const sign = num < 0 ? "-" : "";
        const abs = Math.abs(num);
        const jo = Math.floor(abs / 1e12);
        const eok = Math.round((abs % 1e12) / 1e8);

        if (jo > 0 && eok > 0) {
            return `${sign}${jo.toLocaleString("ko-KR")}조 ${eok.toLocaleString("ko-KR")}억`;
        }
        if (jo > 0) {
            return `${sign}${jo.toLocaleString("ko-KR")}조`;
        }
        if (eok > 0) {
            return `${sign}${eok.toLocaleString("ko-KR")}억`;
        }
        return `${sign}${abs.toLocaleString("ko-KR")}원`;
    }

    function formatMetric(value, suffix = "") {
        if (value === null || value === undefined || Number.isNaN(value)) return "-";
        return `${Number(value).toLocaleString("ko-KR")}${suffix}`;
    }

    async function requestStockData(code) {
        hideStatusBoxes();

        if (!code) {
            const msg = "종목명 또는 종목코드를 입력해 주세요.";
            console.error(`[ERROR]   수집 중 오류 발생 (${msg})`);
            showError(msg);
            return;
        }

        console.log(`[SEARCH]  종목 수집 요청 시작 (${code})`);
        loadingBox.classList.remove("hidden");
        resultArea.classList.add("hidden");
        fetchBtn.disabled = true;

        try {
            const response = await fetch("/fetch", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ code }),
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.error || `요청 실패 (HTTP ${response.status})`);
            }

            const currentPrice = data.snapshot ? data.snapshot.current_price : null;
            console.log(`[PARSED]  기본 정보 수집 완료 (${data.name}, ${formatMetric(currentPrice, "원")})`);
            console.log(`[NEWS]    뉴스 수집 완료 (${(data.news || []).length}건)`);

            renderResult(data);
            console.log("[RENDER]  화면 데이터 카드 렌더링 완료");
        } catch (err) {
            console.error(`[ERROR]   수집 중 오류 발생 (${err.message})`);
            showError(err.message || "데이터 수집 중 알 수 없는 오류가 발생했습니다.");
        } finally {
            loadingBox.classList.add("hidden");
            fetchBtn.disabled = false;
        }
    }

    function renderResult(data) {
        // 1. 부분 오류(errors) 확인
        if (Array.isArray(data.errors) && data.errors.length > 0) {
            const messages = data.errors.map((e) => `[${e.section}] ${e.message}`).join(" | ");
            warningBox.textContent = `일부 데이터 수집에 제한이 있었습니다: ${messages}`;
            warningBox.classList.remove("hidden");
        }

        // 2. 상단 종목명 및 현재가/등락률
        const snapshot = data.snapshot || {};
        document.getElementById("stock-name").textContent = data.name || "-";
        document.getElementById("stock-code-badge").textContent = data.code || "000000";
        document.getElementById("current-price").textContent = formatMetric(snapshot.current_price, "원");

        const rateEl = document.getElementById("change-rate");
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

        // 3. 투자정보 스냅샷 카드 렌더링
        const metrics = [
            { label: "시가총액", value: formatKoreanAmount(snapshot.market_cap) },
            { label: "52주 최고", value: formatMetric(snapshot.high_52w, "원") },
            { label: "52주 최저", value: formatMetric(snapshot.low_52w, "원") },
            { label: "외인소진율", value: formatMetric(snapshot.foreign_rate, "%") },
            { label: "PER (실적)", value: formatMetric(snapshot.per, "배") },
            { label: "추정 PER", value: formatMetric(snapshot.cns_per, "배") },
            { label: "PBR", value: formatMetric(snapshot.pbr, "배") },
            { label: "BPS (주당순자산)", value: formatMetric(snapshot.bps, "원") },
            { label: "배당수익률", value: formatMetric(snapshot.dividend_yield, "%") },
        ];

        const snapshotGrid = document.getElementById("snapshot-grid");
        snapshotGrid.innerHTML = "";
        metrics.forEach((m) => {
            const card = document.createElement("div");
            card.className = "metric-item";

            const labelEl = document.createElement("div");
            labelEl.className = "metric-label";
            labelEl.textContent = m.label;

            const valueEl = document.createElement("div");
            valueEl.className = "metric-value";
            valueEl.textContent = m.value;

            card.appendChild(labelEl);
            card.appendChild(valueEl);
            snapshotGrid.appendChild(card);
        });

        // 4. 기업실적분석 표 렌더링
        renderFinancialTable(data.financials || []);

        // 5. 뉴스 리스트 렌더링
        renderNewsList(data.news || []);

        resultArea.classList.remove("hidden");
    }

    function renderFinancialTable(financials) {
        const thead = document.getElementById("finance-thead");
        const tbody = document.getElementById("finance-tbody");
        thead.innerHTML = "";
        tbody.innerHTML = "";

        if (financials.length === 0) {
            const tr = document.createElement("tr");
            const td = document.createElement("td");
            td.textContent = "수집된 실적 데이터가 없습니다.";
            tr.appendChild(td);
            tbody.appendChild(tr);
            return;
        }

        // 헤더 행
        const headRow = document.createElement("tr");
        const firstTh = document.createElement("th");
        firstTh.textContent = "항목";
        headRow.appendChild(firstTh);

        financials.forEach((item) => {
            const th = document.createElement("th");
            if (item.is_consensus) {
                th.classList.add("consensus-col");
            }
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

        // 데이터 행 정의
        const rowsSpec = [
            { label: "매출액", key: "revenue", formatter: formatKoreanAmount },
            { label: "영업이익", key: "operating_income", formatter: formatKoreanAmount },
            { label: "영업이익률", key: "operating_margin", formatter: (v) => formatMetric(v, "%") },
            { label: "ROE", key: "roe", formatter: (v) => formatMetric(v, "%") },
            { label: "부채비율", key: "debt_ratio", formatter: (v) => formatMetric(v, "%") },
            { label: "유보율", key: "reserve_ratio", formatter: (v) => formatMetric(v, "%") },
        ];

        rowsSpec.forEach((spec) => {
            const tr = document.createElement("tr");
            const nameTd = document.createElement("td");
            nameTd.textContent = spec.label;
            tr.appendChild(nameTd);

            financials.forEach((item) => {
                const td = document.createElement("td");
                if (item.is_consensus) {
                    td.classList.add("consensus-col");
                }
                td.textContent = spec.formatter(item[spec.key]);
                tr.appendChild(td);
            });

            tbody.appendChild(tr);
        });
    }

    function renderNewsList(news) {
        const newsList = document.getElementById("news-list");
        const countBadge = document.getElementById("news-count-badge");
        newsList.innerHTML = "";
        countBadge.textContent = `${news.length}건`;

        if (news.length === 0) {
            const li = document.createElement("li");
            li.className = "news-item";
            li.textContent = "수집된 최신 뉴스가 없습니다.";
            newsList.appendChild(li);
            return;
        }

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
});
