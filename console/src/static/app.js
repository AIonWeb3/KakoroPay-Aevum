// KakoroPay Console Client
document.addEventListener("DOMContentLoaded", () => {
  const statusBadge = document.getElementById("vault-status");
  const pauseBtn = document.getElementById("btn-pause-toggle");
  const balanceElem = document.getElementById("tusd8-balance");
  const nativeElem = document.getElementById("native-balance");
  const addrElem = document.getElementById("account-address");
  const explorerLink = document.getElementById("explorer-link");
  const revokeBtn = document.getElementById("btn-revoke");
  const targetKeyInput = document.getElementById("target-session-key");
  const revokeResult = document.getElementById("revoke-result");
  const timeline = document.getElementById("timeline");
  const eventCountElem = document.getElementById("event-count");

  let isPaused = false;
  let eventCount = 0;

  async function fetchStatus() {
    try {
      const resp = await fetch("/api/status");
      if (!resp.ok) return;
      const data = await resp.json();

      isPaused = data.isPaused;
      statusBadge.textContent = isPaused ? "Vault Paused" : "Vault Active";
      statusBadge.className = isPaused ? "badge badge-paused" : "badge badge-normal";
      pauseBtn.textContent = isPaused ? "Unpause Vault" : "Pause Vault";

      balanceElem.textContent = data.tusd8BalanceFormatted;
      nativeElem.textContent = data.nativeBalance;
      addrElem.textContent = data.accountAddress;
      explorerLink.href = data.explorerAccountUrl;
    } catch (err) {
      console.error("Failed to load status:", err);
    }
  }

  async function togglePause() {
    pauseBtn.disabled = true;
    const endpoint = isPaused ? "/api/unpause" : "/api/pause";
    try {
      const resp = await fetch(endpoint, { method: "POST" });
      if (resp.ok) {
        await fetchStatus();
      }
    } finally {
      pauseBtn.disabled = false;
    }
  }

  async function revokeKey() {
    const key = targetKeyInput.value.trim();
    if (!key.startsWith("0x") || key.length !== 42) {
      revokeResult.textContent = "Please enter a valid 0x address (42 chars)";
      revokeResult.style.color = "var(--danger)";
      return;
    }

    revokeBtn.disabled = true;
    try {
      const resp = await fetch("/api/revoke", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_key: key }),
      });
      const data = await resp.json();
      if (resp.ok) {
        revokeResult.textContent = `Revoked session ${key.slice(0, 8)}... tx: ${data.txHash.slice(0, 10)}...`;
        revokeResult.style.color = "var(--emerald)";
        targetKeyInput.value = "";
      } else {
        revokeResult.textContent = data.detail || "Revoke failed";
        revokeResult.style.color = "var(--danger)";
      }
    } finally {
      revokeBtn.disabled = false;
    }
  }

  function addTimelineEvent(evt) {
    if (eventCount === 0) {
      timeline.innerHTML = "";
    }
    eventCount++;
    eventCountElem.textContent = eventCount;

    const item = document.createElement("div");
    item.className = "timeline-item";

    let typeClass = "type-payment";
    if (evt.type === "SessionRevoked") typeClass = "type-revoked";
    if (evt.type.includes("Pause")) typeClass = "type-paused";

    const detailText = evt.amount ? `${(evt.amount / 1000000).toFixed(2)} tUSD8` : (evt.sessionKey ? `${evt.sessionKey.slice(0, 10)}...` : "");
    const txLink = evt.explorerUrl ? `<a href="${evt.explorerUrl}" target="_blank" class="link-ext">Tx: ${evt.txHash ? evt.txHash.slice(0, 10) : "view"}... ↗</a>` : "";

    item.innerHTML = `
      <div class="timeline-left">
        <span class="type-pill ${typeClass}">${evt.type || "Event"}</span>
        <span>${detailText}</span>
      </div>
      <div>
        ${txLink}
      </div>
    `;

    timeline.prepend(item);
  }

  // SSE Stream
  function setupEventStream() {
    const source = new EventSource("/api/stream");
    source.onmessage = (e) => {
      try {
        const evt = JSON.parse(e.data);
        addTimelineEvent(evt);
        fetchStatus();
      } catch (err) {
        console.error(err);
      }
    };
  }

  pauseBtn.addEventListener("click", togglePause);
  revokeBtn.addEventListener("click", revokeKey);

  fetchStatus();
  setupEventStream();
  setInterval(fetchStatus, 8000);
});
