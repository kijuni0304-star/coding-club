(() => {
    const container = document.querySelector('.price-update-countdown');
    const remaining = document.getElementById('price-update-remaining');
    if (!container || !remaining) return;

    const serverNowMs = Number(container.dataset.serverNowMs);
    if (!Number.isFinite(serverNowMs)) return;

    const startedAt = performance.now();
    const nextUpdateMs = (Math.floor(serverNowMs / 60000) + 1) * 60000;
    let timer;

    function updateCountdown() {
        const secondsLeft = Math.ceil((nextUpdateMs - serverNowMs - (performance.now() - startedAt)) / 1000);
        if (secondsLeft <= 0) {
            clearInterval(timer);
            remaining.textContent = '갱신 중...';
            setTimeout(() => window.location.reload(), 3000);
            return;
        }

        const minutes = Math.floor(secondsLeft / 60);
        const seconds = secondsLeft % 60;
        remaining.textContent = `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
    }

    timer = setInterval(updateCountdown, 250);
    updateCountdown();
})();
