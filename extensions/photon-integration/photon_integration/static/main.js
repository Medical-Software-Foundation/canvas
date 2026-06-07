// Mounts Photon Elements in the Canvas modal. The provider authenticates with
// Photon (user-access token with write:prescription) and prescribes for the
// already-synced patient. Config is injected server-side as window.PHOTON_CONFIG.

(function () {
  "use strict";

  var port = null;
  window.addEventListener("message", function (event) {
    if (event.data && event.data.type === "INIT_CHANNEL" && event.ports && event.ports[0]) {
      port = event.ports[0];
      port.start();
    }
  });

  function closeModal() {
    if (port) {
      port.postMessage({ type: "CLOSE_MODAL" });
    } else {
      window.close();
    }
  }

  function setStatus(message, isError) {
    var el = document.getElementById("status");
    if (!el) return;
    el.textContent = message;
    el.className = "status" + (isError ? " error" : "");
  }

  var cfg = window.PHOTON_CONFIG || {};
  if (!cfg.clientId || !cfg.patientId) {
    setStatus("Photon modal is misconfigured (missing client id or patient).", true);
    return;
  }

  function mountElements() {
    var client = document.createElement("photon-client");
    client.setAttribute("id", cfg.clientId);
    client.setAttribute("org", cfg.org);
    client.setAttribute("redirect-uri", cfg.redirectUri);
    client.setAttribute("dev-mode", cfg.devMode ? "true" : "false");
    client.setAttribute("auto-login", "true");

    var workflow = document.createElement("photon-prescribe-workflow");
    workflow.setAttribute("patient-id", cfg.patientId);
    workflow.setAttribute("enable-order", "true");
    client.appendChild(workflow);

    var root = document.getElementById("root");
    root.innerHTML = "";
    root.appendChild(client);

    document.addEventListener("photon-prescriptions-created", function () {
      setStatus("Prescription created in Photon.");
    });
    document.addEventListener("photon-order-created", function () {
      setStatus("Order placed in Photon. Closing…");
      setTimeout(closeModal, 1500);
    });
    document.addEventListener("photon-prescriptions-error", function (event) {
      setStatus("Prescription error: " + describe(event), true);
    });
    document.addEventListener("photon-order-error", function (event) {
      setStatus("Order error: " + describe(event), true);
    });
  }

  function describe(event) {
    try {
      return JSON.stringify((event && event.detail) || {});
    } catch (e) {
      return "unknown error";
    }
  }

  setStatus("Loading Photon Elements…");
  import("https://esm.sh/@photonhealth/elements")
    .then(function () {
      setStatus("Authenticating with Photon…");
      mountElements();
    })
    .catch(function (err) {
      setStatus("Failed to load Photon Elements: " + err, true);
      // eslint-disable-next-line no-console
      console.error("Photon Elements failed to load", err);
    });
})();
