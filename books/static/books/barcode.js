(function () {
  const input = document.getElementById("isbn-lookup-input");
  const scanBtn = document.getElementById("barcode-scan-btn");
  if (!input || !scanBtn || typeof BarcodeDetector === "undefined") {
    if (scanBtn) scanBtn.hidden = true;
    return;
  }

  scanBtn.addEventListener("click", async function () {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
      const video = document.createElement("video");
      video.srcObject = stream;
      video.setAttribute("playsinline", "true");
      await video.play();

      const detector = new BarcodeDetector({ formats: ["ean_13", "ean_8", "upc_a", "upc_e"] });
      const deadline = Date.now() + 15000;
      scanBtn.disabled = true;
      scanBtn.textContent = "Scanning…";

      while (Date.now() < deadline) {
        const codes = await detector.detect(video);
        if (codes.length) {
          const raw = codes[0].rawValue.replace(/\D/g, "");
          if (raw.length >= 10) {
            input.value = raw;
            input.dispatchEvent(new Event("change", { bubbles: true }));
            break;
          }
        }
        await new Promise((r) => requestAnimationFrame(r));
      }

      stream.getTracks().forEach((t) => t.stop());
    } catch (err) {
      console.warn("Barcode scan unavailable", err);
    } finally {
      scanBtn.disabled = false;
      scanBtn.textContent = "Scan barcode";
    }
  });
})();
