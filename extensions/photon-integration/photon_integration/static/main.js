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

  // Sign in to Photon via a POPUP, not a redirect or silent-iframe auth. Photon's
  // Auth0 connection is Google-backed, and Google refuses to render its sign-in
  // inside an iframe (which this modal is) — both loginWithRedirect and the silent
  // getTokenSilently iframe hit a Google 403. A popup is a top-level window Google
  // accepts. Popups need a user gesture (hence the button), and the Canvas origin
  // must be an Allowed Web Origin in the Photon SPA app for the popup to post back.
  function addSignInButton(client) {
    var btn = document.createElement("button");
    btn.className = "switch-btn";
    btn.textContent = "Sign in to Photon";
    btn.addEventListener("click", function () {
      btn.disabled = true;
      setStatus("Opening Photon sign-in…");
      client.auth0Client
        .loginWithPopup({ authorizationParams: { organization: cfg.org } })
        .then(function () {
          window.location.reload();
        })
        .catch(function (err) {
          setStatus("Photon sign-in failed: " + (err && err.message ? err.message : err), true);
          btn.disabled = false;
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

    // Read the cached session ONLY — cacheMode 'cache-only' never triggers the
    // silent-auth iframe or a redirect (both frame Google and 403 in this modal).
    var token = null;
    try {
      token = await client.auth0Client.getTokenSilently({ cacheMode: "cache-only" });
    } catch (e) {
      token = null;
    }
    if (!token) {
      setStatus("Sign in to Photon to prescribe.");
      addSignInButton(client);
      return;
    }

    var photonUser = null;
    try {
      photonUser = await client.auth0Client.getUser();
    } catch (e) {
      /* ignore */
    }
    var photonEmail = ((photonUser && photonUser.email) || "").toLowerCase();
    var canvasEmail = (cfg.canvasUserEmail || "").toLowerCase();
    if (!photonEmail || !canvasEmail || photonEmail !== canvasEmail) {
      // Stay inside our modal — surface the problem here rather than bouncing
      // the user out to an external sign-out page.
      setStatus("You're not signed in to Photon. Sign in to Photon to prescribe.", true);
      addSignInButton(client);
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
