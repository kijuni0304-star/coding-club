const POLL_INTERVAL_MS = 15_000;
let refreshInProgress = false;


function applyChangeStyle(element, stock) {
  element.classList.remove("text-red", "text-blue", "text-neutral");
  element.classList.add(stock.change_class);
}


function updateRanking(stocks) {
  const stockList = document.querySelector(".stock-list");
  const rowsByStockId = new Map(
    [...stockList.querySelectorAll("[data-stock-id]")].map((row) => [
      Number(row.dataset.stockId),
      row,
    ]),
  );

  stocks.forEach((stock, index) => {
    const row = rowsByStockId.get(stock.id);
    if (!row) return;

    row.querySelector("[data-rank]").textContent = index + 1;
    row.querySelector("[data-current-price]").textContent = stock.current_price_display;
    row.querySelector("[data-change-amount]").textContent = stock.change_amount_display;

    const changeInfo = row.querySelector("[data-change-info]");
    applyChangeStyle(changeInfo, stock);

    const changePercent = row.querySelector("[data-change-percent]");
    changePercent.textContent = stock.change_percent_display;
    changePercent.classList.remove("up", "down", "flat");
    changePercent.classList.add(stock.direction);

    // API가 등락률 순으로 반환하므로 화면에서도 같은 순서를 유지한다.
    stockList.appendChild(row);
  });
}


function updateTrade(stock) {
  document.querySelector("[data-company-name]").textContent = stock.company_name;
  document.querySelector(".current-price").textContent = stock.current_price_display;
  document.querySelector("[data-previous-price]").textContent =
    stock.previous_price_display;
  document.querySelector("[data-change-amount]").textContent =
    stock.change_amount_display;
  document.querySelectorAll("[data-change-percent]").forEach((element) => {
    element.textContent = stock.change_percent_display;
  });

  const currentPrice = document.querySelector(".current-price");
  currentPrice.classList.remove("up", "down", "flat");
  currentPrice.classList.add(stock.direction);
  applyChangeStyle(document.querySelector("[data-change-info]"), stock);
  window.dispatchEvent(new CustomEvent("stock-price-updated", { detail: stock }));
}


async function refreshStockPrices() {
  if (refreshInProgress) return;
  refreshInProgress = true;
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 10_000);
  try {
    const page = document.body.dataset.stockPage;
    const response = await fetch(document.body.dataset.stocksApi, {
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal: controller.signal,
    });
    if (!response.ok) return;

    const { stocks } = await response.json();
    if (page === "ranking") {
      updateRanking(stocks);
      return;
    }

    const selectedStockId = Number(document.body.dataset.selectedStockId);
    const selectedStock = stocks.find((stock) => stock.id === selectedStockId);
    if (selectedStock) updateTrade(selectedStock);
  } finally {
    window.clearTimeout(timeout);
    refreshInProgress = false;
  }
}


function startStockPricePolling() {
  refreshStockPrices().catch(() => {});
  window.setInterval(() => {
    if (document.visibilityState === "visible") {
      refreshStockPrices().catch(() => {});
    }
  }, POLL_INTERVAL_MS);

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
      refreshStockPrices().catch(() => {});
    }
  });
}


startStockPricePolling();
