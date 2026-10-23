let qrScanner = null;
const resultBox = document.getElementById("scan-result");
const codeInput = document.getElementById("person-code");

function showResult(message, success) {
  resultBox.textContent = message;
  resultBox.className = "result " + (success ? "success" : "error");
}

async function recordScan(code) {
  const payload = {
    person_code: code,
    scan_type: document.getElementById("scan-type").value,
    class_name: document.getElementById("class-name").value,
    subject: document.getElementById("subject").value,
    scanned_by: document.getElementById("scanner-name").value
  };
  try {
    const response = await fetch("/api/scan", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload)
    });
    const data = await response.json();
    showResult(data.message || "Scan failed.", response.ok && data.ok);
    if (response.ok && data.ok) {
      codeInput.value = "";
      // Refresh dashboard to show the new event and updated counters.
      setTimeout(() => window.location.reload(), 1200);
    }
  } catch (error) {
    showResult("Could not reach the server. Check your connection and try again.", false);
  }
}

document.getElementById("submit-scan").addEventListener("click", () => {
  const code = codeInput.value.trim();
  if (!code) return showResult("Enter an ID code first.", false);
  recordScan(code);
});
codeInput.addEventListener("keydown", event => {
  if (event.key === "Enter") {
    event.preventDefault();
    document.getElementById("submit-scan").click();
  }
});

document.getElementById("start-camera").addEventListener("click", async () => {
  if (typeof Html5Qrcode === "undefined") {
    return showResult("QR scanning library could not load. Check internet access or use manual ID entry.", false);
  }
  if (qrScanner) return;
  qrScanner = new Html5Qrcode("reader");
  try {
    await qrScanner.start(
      { facingMode: "environment" },
      { fps: 10, qrbox: { width: 230, height: 180 } },
      decodedText => {
        codeInput.value = decodedText.trim();
        qrScanner.stop().then(() => { qrScanner = null; recordScan(decodedText.trim()); }).catch(() => { qrScanner = null; });
      },
      () => {}
    );
    showResult("Camera active. Point it at the QR code.", true);
  } catch (error) {
    qrScanner = null;
    showResult("Camera could not start. Allow camera permission and use HTTPS or localhost, or enter the ID manually.", false);
  }
});
document.getElementById("stop-camera").addEventListener("click", async () => {
  if (qrScanner) {
    try { await qrScanner.stop(); } catch (e) {}
    qrScanner = null;
  }
  showResult("Camera stopped.", true);
});
