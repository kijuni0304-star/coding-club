const MIN_QUANTITY = 1;
const MAX_QUANTITY = 1_000_000;

const tradeState = {
  buy: { quantity: 1, price: 0n },
  sell: { quantity: 1, price: 0n },
};


function toSafeInteger(value, fallback = 0) {
  const number = Number(value);
  return Number.isSafeInteger(number) ? number : fallback;
}


function clampQuantity(quantity) {
  return Math.min(
    MAX_QUANTITY,
    Math.max(MIN_QUANTITY, toSafeInteger(quantity, MIN_QUANTITY)),
  );
}


function formatWon(amount) {
  return amount.toLocaleString("ko-KR");
}


function renderTradeSide(side) {
  const state = tradeState[side];
  const quantityElement = document.querySelector(
    `#${side}Quantity`,
  );
  const priceElement = document.querySelector(
    `[data-order-price][data-side="${side}"]`,
  );
  const totalElement = document.querySelector(
    `[data-total-amount][data-side="${side}"]`,
  );

  quantityElement.textContent = state.quantity;
  priceElement.textContent = formatWon(state.price);
  totalElement.textContent = formatWon(state.price * BigInt(state.quantity));
}


function changeQuantity(side, delta) {
  if (!tradeState[side]) return;
  tradeState[side].quantity = clampQuantity(
    tradeState[side].quantity + toSafeInteger(delta),
  );
  renderTradeSide(side);
}


function showOrderResult(side, message, type = "info") {
  const resultElement = document.querySelector(
    `[data-order-result][data-side="${side}"]`,
  );
  resultElement.textContent = message;
  resultElement.classList.remove("success", "error", "info");
  resultElement.classList.add(type);
}


async function submitOrder(side) {
  if (!Object.hasOwn(tradeState, side)) return;
  const button = document.querySelector(
    `[data-action="order"][data-side="${side}"]`,
  );
  if (button.disabled) return;
  button.disabled = true;
  tradeState[side].quantity = clampQuantity(tradeState[side].quantity);
  const orderLabel = side === "buy" ? "매수" : "매도";
  const orderUrl = side === "buy"
    ? document.body.dataset.buyUrl
    : document.body.dataset.sellUrl;
  showOrderResult(side, `${orderLabel} 주문을 확인하고 있습니다.`, "info");

  try {
    const response = await fetch(orderUrl, {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "X-CSRF-Token": document.body.dataset.csrfToken,
      },
      body: JSON.stringify({
        stock_id: Number(document.body.dataset.selectedStockId),
        quantity: tradeState[side].quantity,
      }),
    });
    const result = await response.json();
    if (!response.ok) {
      showOrderResult(
        side,
        result.error?.message || `${orderLabel} 주문이 거부되었습니다.`,
        "error",
      );
      return;
    }

    showOrderResult(
      side,
      `${result.message} 체결가 ${result.order.price_display}원 · 남은 예수금 ${result.order.remaining_cash_display}원`,
      "success",
    );
    refreshStockPrices().catch(() => {});
  } catch (error) {
    showOrderResult(side, "응답을 확인하지 못했습니다. 재주문 전에 거래 내역을 확인해 주세요.", "error");
  } finally {
    button.disabled = false;
  }
}


function initializeTradeControls() {
  const initialPrice = BigInt(document.body.dataset.initialCurrentPrice);
  tradeState.buy.price = initialPrice;
  tradeState.sell.price = initialPrice;
  renderTradeSide("buy");
  renderTradeSide("sell");

  document.querySelectorAll("[data-action]").forEach((button) => {
    const { action, side, delta } = button.dataset;
    button.addEventListener("click", () => {
      if (action === "quantity") changeQuantity(side, delta);
      if (action === "order") submitOrder(side);
    });
  });

  window.addEventListener("stock-price-updated", (event) => {
    // JSON number의 큰 정수 반올림을 피하고 서버가 포맷한 원 금액을 사용한다.
    const currentPrice = BigInt(event.detail.current_price_display.replaceAll(",", ""));
    tradeState.buy.price = currentPrice;
    tradeState.sell.price = currentPrice;
    renderTradeSide("buy");
    renderTradeSide("sell");
  });
}


initializeTradeControls();
