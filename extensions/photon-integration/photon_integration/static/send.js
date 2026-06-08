// API-direct send: authenticate the provider with Photon (user token via the
// vendored SDK), then submit each flagged prescription with the validated
// GraphQL mutations (createPrescription + createOrder) using that token.
// Config is injected server-side as window.PHOTON_SEND_CONFIG.

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
    if (port) port.postMessage({ type: "CLOSE_MODAL" });
    else window.close();
  }
  function setStatus(message, isError) {
    var el = document.getElementById("status");
    if (!el) return;
    el.textContent = message;
    el.className = "status" + (isError ? " error" : "");
  }
  function addResult(label, ok, detail) {
    var li = document.createElement("li");
    li.className = "result " + (ok ? "ok" : "fail");
    li.textContent = (ok ? "✓ " : "✗ ") + label + (detail ? " — " + detail : "");
    document.getElementById("results").appendChild(li);
  }

  var cfg = window.PHOTON_SEND_CONFIG || {};
  if (!cfg.clientId) {
    setStatus("Photon send modal is misconfigured (missing client id).", true);
    return;
  }

  // Carry patient id + the prescription list across the SSO redirect.
  var KEY_P = "photon_patient_id";
  var KEY_RX = "photon_send_rx";
  try {
    if (cfg.patientId) sessionStorage.setItem(KEY_P, cfg.patientId);
    else cfg.patientId = sessionStorage.getItem(KEY_P) || "";
    if (cfg.prescriptions && cfg.prescriptions.length) {
      sessionStorage.setItem(KEY_RX, JSON.stringify(cfg.prescriptions));
    } else {
      cfg.prescriptions = JSON.parse(sessionStorage.getItem(KEY_RX) || "[]");
    }
  } catch (e) {
    /* storage unavailable */
  }

  var CREATE_PRESCRIPTION = [
    "mutation createPrescription($externalId: ID, $patientId: ID!, $treatmentId: ID!,",
    "  $dispenseAsWritten: Boolean, $dispenseQuantity: Float, $dispenseUnit: String,",
    "  $refillsAllowed: Int, $daysSupply: Int, $instructions: String, $notes: String) {",
    "  createPrescription(externalId: $externalId, patientId: $patientId, treatmentId: $treatmentId,",
    "    dispenseAsWritten: $dispenseAsWritten, dispenseQuantity: $dispenseQuantity,",
    "    dispenseUnit: $dispenseUnit, refillsAllowed: $refillsAllowed, daysSupply: $daysSupply,",
    "    instructions: $instructions, notes: $notes) { id }",
    "}",
  ].join("\n");

  var CREATE_ORDER = [
    "mutation createOrder($externalId: ID, $patientId: ID!, $fills: [FillInput!]!, $address: AddressInput) {",
    "  createOrder(externalId: $externalId, patientId: $patientId, fills: $fills, address: $address) { id }",
    "}",
  ].join("\n");

  function gql(token, query, variables) {
    return fetch(cfg.graphqlUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: "Bearer " + token },
      body: JSON.stringify({ query: query, variables: variables }),
    })
      .then(function (r) {
        return r.json();
      })
      .then(function (body) {
        if (body.errors && body.errors.length) {
          throw new Error(body.errors[0].message || "GraphQL error");
        }
        return body.data;
      });
  }

  async function sendOne(token, rx) {
    if (rx.error || !rx.treatmentId) {
      addResult(rx.medication, false, rx.error || "no Photon medication match");
      return false;
    }
    var label = rx.photonMedication ? rx.medication + " → Photon: " + rx.photonMedication : rx.medication;
    var presc = await gql(token, CREATE_PRESCRIPTION, {
      externalId: rx.externalId,
      patientId: rx.patientId || cfg.patientId,
      treatmentId: rx.treatmentId,
      dispenseAsWritten: rx.dispenseAsWritten,
      dispenseQuantity: rx.dispenseQuantity,
      dispenseUnit: rx.dispenseUnit,
      refillsAllowed: rx.refillsAllowed,
      daysSupply: rx.daysSupply,
      instructions: rx.instructions,
      notes: rx.notes,
    });
    var prescriptionId = presc.createPrescription.id;
    await gql(token, CREATE_ORDER, {
      externalId: rx.externalId,
      patientId: rx.patientId || cfg.patientId,
      fills: [{ prescriptionId: prescriptionId }],
      address: cfg.address || null,
    });
    addResult(label, true, "sent");
    return true;
  }

  async function run() {
    // Loaded from jsDelivr (allowed by Canvas's script-src) so the SDK's own
    // /npm/ dependency imports resolve against jsDelivr rather than our origin.
    var mod = await import("https://cdn.jsdelivr.net/npm/@photonhealth/sdk@1.3.4/+esm");
    var client = new mod.PhotonClient({
      clientId: cfg.clientId,
      organization: cfg.org,
      redirectURI: cfg.redirectUri,
      // sandbox (Neutron) vs production is selected by `developmentMode`; with it
      // false the SDK uses auth.photon.health and the sandbox client 404s.
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
      setStatus("Sign in to Photon to send these prescriptions.");
      addSignInButton(client);
      return;
    }

    if (!cfg.prescriptions.length) {
      setStatus("No prescriptions are flagged 'Send via Photon' on this note.", true);
      return;
    }

    // Photon attributes the prescription to the signed-in user (there is no
    // prescriberId). Only send an Rx when the signed-in Photon provider matches
    // the command's prescriber — never under a cached session for someone else.
    var photonUser = null;
    try {
      photonUser = await client.auth0Client.getUser();
    } catch (e) {
      /* ignore */
    }
    var photonEmail = ((photonUser && photonUser.email) || "").toLowerCase();
    var photonName = (photonUser && photonUser.name) || photonEmail || "your Photon account";

    // The operator must BE the signed-in Photon provider — don't let a cached
    // Photon session (someone else) be used by a different Canvas user.
    var canvasEmail = (cfg.canvasUserEmail || "").toLowerCase();
    if (!photonEmail || !canvasEmail || photonEmail !== canvasEmail) {
      // eslint-disable-next-line no-console
      console.warn("[photon] identity gate blocked send", {
        photonEmail: photonEmail,
        canvasEmail: canvasEmail,
      });
      // Stay inside our modal — surface the problem here rather than bouncing the
      // user out to an external sign-out page.
      setStatus("You're not signed in to Photon. Sign in to Photon to send.", true);
      addSignInButton(client);
      return;
    }

    function prescriberError(rx) {
      if (!rx.prescriberEmail) {
        return "Could not verify the prescriber's Photon identity — use Prescribe via Photon";
      }
      if (!photonEmail || rx.prescriberEmail.toLowerCase() !== photonEmail) {
        return (
          "Prescriber is " + (rx.prescriberName || rx.prescriberEmail) +
          ", but Photon is signed in as " + photonName +
          ". Sign in to Photon as the prescriber."
        );
      }
      return null;
    }

    setStatus("Signed in to Photon as " + photonName + ". Sending…");
    var sent = 0;
    var mismatch = false;
    for (var i = 0; i < cfg.prescriptions.length; i++) {
      var rx = cfg.prescriptions[i];
      if (!rx.error) {
        var perr = prescriberError(rx);
        if (perr) {
          rx.error = perr;
          mismatch = true;
        }
      }
      try {
        if (await sendOne(token, rx)) sent++;
      } catch (err) {
        var msg = String(err && err.message ? err.message : err);
        if (/already exists/i.test(msg)) {
          addResult(rx.medication, true, "already sent to Photon");
          sent++;
        } else {
          addResult(rx.medication, false, msg);
        }
      }
    }
    setStatus(sent + " of " + cfg.prescriptions.length + " sent to Photon as " + photonName + ".");
    if (mismatch) {
      // Keep the pending list so a re-login as the right provider can retry.
      addSignInButton(client);
    } else {
      try {
        sessionStorage.removeItem(KEY_RX);
      } catch (e) {
        /* ignore */
      }
    }
  }

  // Sign in to Photon via a POPUP, not a redirect or silent-iframe auth. Photon's
  // Auth0 connection is Google-backed, and Google refuses to render its sign-in
  // inside an iframe (which this modal is) — both loginWithRedirect and the silent
  // getTokenSilently iframe hit a Google 403. A popup is a top-level window Google
  // accepts. Popups need a user gesture (hence the button), and the Canvas origin
  // must be an Allowed Web Origin in the Photon SPA app for the popup to post back.
  // After sign-in we reload so the server re-gathers the flagged prescriptions.
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

  run().catch(function (err) {
    setStatus("Photon send failed: " + (err && err.message ? err.message : err), true);
    // eslint-disable-next-line no-console
    console.error("Photon send error", err);
  });
})();
