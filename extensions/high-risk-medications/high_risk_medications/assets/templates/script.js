// JavaScript for high-risk medications real-time updates
(function () {
  const container = document.getElementById("high-risk-container");

  if (!container) {
    console.error("high-risk-container not found!");
    return;
  }

  const patientId = container.dataset.patientId;
  const customerIdentifier = container.dataset.customerIdentifier;
  let refreshInFlight = false;

  if (!patientId || !customerIdentifier) {
    console.error("Missing patient or customer identifier");
    return;
  }

  const refreshView = () => {
    if (refreshInFlight) {
      return;
    }

    refreshInFlight = true;
    fetch(
      `/plugin-io/api/high_risk_medications/high-risk-meds/${patientId}`,
      {
        credentials: "include",
      }
    )
      .then((response) => {
        if (!response.ok) {
          throw new Error(`Refresh failed with status ${response.status}`);
        }
        return response.text();
      })
      .then((html) => {
        const parser = new DOMParser();
        const doc = parser.parseFromString(html, "text/html");
        const newContent = doc.getElementById("medications-content");
        const currentContent = document.getElementById("medications-content");

        if (newContent && currentContent) {
          currentContent.innerHTML = newContent.innerHTML;
        }
      })
      .catch((error) => {
        console.error("Error refreshing view:", error);
      })
      .finally(() => {
        refreshInFlight = false;
      });
  };

  // Establish WebSocket connection for real-time updates
  window.addEventListener("load", () => {
    // Channel names must be alphanumeric with underscores only (no dashes)
    // Replace dashes with underscores to match broadcast channel format
    const channelName = patientId.replace(/-/g, "_");
    const wsUrl = `wss://${customerIdentifier}.canvasmedical.com/plugin-io/ws/high_risk_medications/${channelName}/`;
    const socket = new WebSocket(wsUrl);

    socket.onmessage = (event) => {
      refreshView();
    };

    socket.onerror = (error) => {
      console.error("WebSocket error:", error);
    };

    // Keep connection alive with periodic pings
    setInterval(() => {
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: "ping" }));
      }
    }, 30000); // Send ping every 30 seconds
  });
})();
