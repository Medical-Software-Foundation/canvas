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
  if (!cfg.clientId) {
    setStatus("Photon modal is misconfigured (missing client id).", true);
    return;
  }

  // Carry the Photon patient id across the SSO redirect: Auth0 returns to this
  // page without patient_id, so stash it on the way out and restore it on return.
  var PATIENT_KEY = "photon_patient_id";
  try {
    if (cfg.patientId) {
      sessionStorage.setItem(PATIENT_KEY, cfg.patientId);
    } else {
      cfg.patientId = sessionStorage.getItem(PATIENT_KEY) || "";
    }
  } catch (e) {
    /* storage unavailable in this sandbox; fall through */
  }

  var hadCallback =
    /[?&]code=/.test(location.search) && /[?&]state=/.test(location.search);

  function mountElements() {
    var client = document.createElement("photon-client");
    client.setAttribute("id", cfg.clientId);
    client.setAttribute("org", cfg.org);
    client.setAttribute("redirect-uri", cfg.redirectUri);
    client.setAttribute("dev-mode", cfg.devMode ? "true" : "false");
    client.setAttribute("auto-login", "true");

    if (cfg.patientId) {
      var workflow = document.createElement("photon-prescribe-workflow");
      workflow.setAttribute("patient-id", cfg.patientId);
      workflow.setAttribute("enable-order", "true");
      client.appendChild(workflow);
    } else {
      setStatus("Completing Photon sign-in…");
    }

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

  function addSwitchProviderButton(client) {
    var btn = document.createElement("button");
    btn.className = "switch-btn";
    btn.textContent = "Sign in to Photon as yourself";
    btn.addEventListener("click", function () {
      btn.disabled = true;
      Promise.resolve()
        .then(function () {
          return client.authentication.logout();
        })
        .catch(function () {})
        .then(function () {
          return client.authentication.login({ redirectURI: cfg.redirectUri });
        })
        .catch(function (err) {
          setStatus("Could not switch Photon provider: " + err, true);
        });
    });
    document.getElementById("root").appendChild(btn);
  }

  async function run() {
    // Use the SDK (same Auth0 session as photon-client) to verify identity before
    // mounting the prescribe workflow — so a cached session for someone else can't
    // be used by a different Canvas user.
    var sdk = await import("https://cdn.jsdelivr.net/npm/@photonhealth/sdk@1.3.4/+esm");
    var client = new sdk.PhotonClient({
      clientId: cfg.clientId,
      organization: cfg.org,
      redirectURI: cfg.redirectUri,
      developmentMode: !!cfg.devMode,
    });

    if (hadCallback) {
      setStatus("Completing Photon sign-in…");
      await client.authentication.handleRedirect();
    }
    try {
      window.history.replaceState({}, document.title, window.location.pathname);
    } catch (e) {
      /* ignore */
    }

    var token = null;
    try {
      token = await client.authentication.getAccessToken();
    } catch (e) {
      token = null;
    }
    if (!token) {
      setStatus("Redirecting to Photon sign-in…");
      await client.authentication.login({ redirectURI: cfg.redirectUri });
      return;
    }

    var photonUser = null;
    try {
      photonUser = await client.authentication.getUser();
    } catch (e) {
      /* ignore */
    }
    var photonEmail = ((photonUser && photonUser.email) || "").toLowerCase();
    var photonName = (photonUser && photonUser.name) || photonEmail || "your Photon account";
    var canvasEmail = (cfg.canvasUserEmail || "").toLowerCase();
    if (!photonEmail || !canvasEmail || photonEmail !== canvasEmail) {
      setStatus("You're not signed in to Photon as yourself. Sign in to Photon to prescribe.", true);
      addSwitchProviderButton(client);
      return;
    }

    setStatus("Loading Photon Elements…");
    await import("./elements.js");
    mountElements();
  }

  run().catch(function (err) {
    setStatus("Photon modal failed: " + (err && err.message ? err.message : err), true);
    // eslint-disable-next-line no-console
    console.error("Photon modal error", err);
  });
})();
