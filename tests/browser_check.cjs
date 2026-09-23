const {chromium} = require("playwright");
const assert = require("node:assert/strict");
const path = require("node:path");

(async () => {
  const browser = await chromium.launch({channel: process.env.BROWSER_CHANNEL || "chrome", headless: true});
  try {
    const context = await browser.newContext();
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    // 외부 폰트 CDN 사용 없이도 기본 폰트로 모든 기능과 레이아웃이 동작해야 한다.
    await context.route("https://cdn.jsdelivr.net/**", route => route.abort());
    const base = process.argv[2];
    await page.goto(base);
    await page.locator("#nickname").fill("user1");
    await page.getByRole("button", {name: "로그인", exact: true}).click();
    await page.waitForURL("**/portfolio");
    for (const width of [320, 375, 480, 1280]) {
      await page.setViewportSize({width, height: 900});
      for (const url of ["/", "/portfolio", "/ranking", "/order/1", "/history"]) {
        await page.goto(base + url);
        await page.evaluate(() => document.fonts.ready);
        const geometry = await page.evaluate(() => ({
          viewport: innerWidth, scroll: document.documentElement.scrollWidth,
          container: document.querySelector(".app, .app-container, .login-container").getBoundingClientRect().width,
          overlaps: [...document.querySelectorAll(".stock-item-link, .stock-item, .history-item, .stock-main, .stock-summary")].some(row => {
            const r = [...row.children].map(el => el.getBoundingClientRect());
            return r.some((a, i) => r.slice(i+1).some(b =>
              Math.min(a.right,b.right)-Math.max(a.left,b.left)>1 &&
              Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top)>1));
          }),
        }));
        assert.ok(geometry.scroll <= width, JSON.stringify({url, width, geometry}));
        assert.ok(geometry.container <= 480, JSON.stringify({url, width, geometry}));
        assert.equal(geometry.overlaps, false, JSON.stringify({url, width, geometry}));
      }
    }
    await page.setViewportSize({width: 375, height: 900});
    await page.goto(base + "/order/1");
    assert.equal(await page.locator('[data-action="price"]').count(), 0);
    await page.locator('[data-action="quantity"][data-side="buy"][data-delta="1"]').click();
    assert.equal(await page.locator('[data-total-amount][data-side="buy"]').innerText(), "22,400");
    await page.locator('[data-action="order"][data-side="buy"]').click();
    await page.locator('[data-order-result][data-side="buy"].success').waitFor();
    await page.locator('[data-action="order"][data-side="sell"]').click();
    await page.locator('[data-order-result][data-side="sell"].success').waitFor();
    const colors = await page.evaluate(() => [
      getComputedStyle(document.querySelector(".buy .trade-title")).color,
      getComputedStyle(document.querySelector(".sell .trade-title")).color,
      getComputedStyle(document.querySelector(".trade-area")).backgroundColor,
    ]);
    assert.deepEqual(colors, ["rgb(255, 82, 82)", "rgb(77, 141, 255)", "rgb(25, 32, 45)"]);
    await page.screenshot({path: path.join(".audit-results", "trade-mobile.png"), fullPage: true});
    await page.goto(base + "/order/10");
    assert.equal(await page.locator("#buyPrice").innerText(), "1,001,000,000");

    await page.clock.install();
    await page.goto(base + "/ranking");
    const stocks = await page.evaluate(async () => (await (await fetch(document.body.dataset.stocksApi)).json()).stocks);
    const firstId = stocks[0].id;
    const newTop = stocks[stocks.length - 1];
    newTop.current_price_display = "12,345";
    newTop.change_amount_display = "▲ +2,345";
    newTop.change_percent_display = "+23.45%";
    newTop.change_class = "text-red";
    newTop.direction = "up";
    const reordered = [newTop, ...stocks.filter(s => s.id !== newTop.id)];
    await page.route("**/api/stocks", route => route.fulfill({json: {stocks: reordered}}));
    // 실제 등록된 15초 폴링 타이머를 가상 시계로 진행한다.
    assert.notEqual(await page.locator("[data-stock-id]").first().getAttribute("data-stock-id"), String(newTop.id));
    await page.clock.runFor(15_100);
    await page.waitForFunction(id => document.querySelector("[data-stock-id]").dataset.stockId === String(id), newTop.id);
    assert.notEqual(newTop.id, firstId);
    assert.equal(await page.locator("[data-current-price]").first().innerText(), "12,345");
    const link = await page.locator(".stock-item-link").first().getAttribute("href");
    assert.equal(link, "/order/" + newTop.id);
    await page.unroute("**/api/stocks");
    await page.goto(base + "/history");
    await page.screenshot({path: path.join(".audit-results", "history-mobile.png"), fullPage: true});
    await page.getByRole("button", {name: "로그아웃"}).click();
    await page.waitForURL(base + "/");
    await page.goto(base + "/portfolio");
    assert.equal(page.url(), base + "/");
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({pages:5, widths:[320,375,480,1280],
      checks:["login","buy","sell","exact server price","polling/reorder/link","colors","logout","no JS errors","no horizontal overflow/overlap"]}));
  } finally {
    await browser.close();
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
