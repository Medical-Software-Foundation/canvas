// JavaScript helpers for the messaging conversational view
(function () {
  const chatContainer = document.getElementById("chat-container");
  if (!chatContainer) {
    return;
  }

  const patientId = chatContainer.dataset.patientId;
  const customerIdentifier = chatContainer.dataset.customerIdentifier;
  const markAllReadButtonSelector = "#mark-all-read-btn";
  const sendMessageFormSelector = ".send-message-form";
  const loadMoreButtonSelector = "#load-more-btn";
  const conversationViewSelector = "#conversation-view";
  const scrollContainerSelector = "#chat-scroll-container";
  let refreshInFlight = false;
  let suppressRefreshUntil = 0;
  const pageSize = Number(chatContainer.dataset.limit) || 20;
  let currentOffset = Number(chatContainer.dataset.offset) || 0;
  let totalMessages = Number(chatContainer.dataset.total) || 0;

  if (!patientId || !customerIdentifier) {
    console.error("Missing patient or customer identifier on chat container dataset");
    return;
  }

  const updateStateFromDoc = (doc) => {
    const docContainer = doc.getElementById("chat-container");
    if (docContainer) {
      if (docContainer.dataset.offset !== undefined) {
        chatContainer.dataset.offset = docContainer.dataset.offset;
      }
      if (docContainer.dataset.total !== undefined) {
        chatContainer.dataset.total = docContainer.dataset.total;
      }
      if (docContainer.dataset.limit !== undefined) {
        chatContainer.dataset.limit = docContainer.dataset.limit;
      }
    }

    currentOffset = Number(chatContainer.dataset.offset) || 0;
    totalMessages = Number(chatContainer.dataset.total) || 0;
  };

  const refreshConversation = (targetOffset = 0) => {
    if (refreshInFlight) {
      return;
    }

    refreshInFlight = true;
    fetch(
      `/plugin-io/api/conversational_messaging/conversation/${patientId}?limit=${pageSize}&offset=${targetOffset}`,
      {
      credentials: "include",
    }
    )
      .then((response) => {
        if (!response.ok) {
          throw new Error(`Conversation refresh failed with status ${response.status}`);
        }
        return response.text();
      })
      .then((html) => {
        const parser = new DOMParser();
        const doc = parser.parseFromString(html, "text/html");
        const newScrollContainer = doc.getElementById("chat-scroll-container");
        const currentScrollContainer = document.querySelector(scrollContainerSelector);

        if (newScrollContainer && currentScrollContainer) {
          currentScrollContainer.innerHTML = newScrollContainer.innerHTML;
          currentScrollContainer.scrollTop = currentScrollContainer.scrollHeight;
        }

        updateStateFromDoc(doc);
      })
      .catch((error) => {
        if (error.name === "AbortError" || error.message === "Failed to fetch") {
          return;
        }
        console.error("Error refreshing conversation:", error);
      })
      .finally(() => {
        refreshInFlight = false;
      });
  };

  const handleMarkAllReadClick = () => {
    fetch(`/plugin-io/api/conversational_messaging/mark-all-read/${patientId}`, {
      method: "POST",
      credentials: "include",
    })
      .then((response) => {
        if (response.ok) {
          refreshConversation();
          return;
        }
        throw new Error(`Mark read failed with status ${response.status}`);
      })
      .catch((error) =>
        console.error("Error marking messages as read:", error)
      );
  };

  const handleSendMessageSubmit = (form) => {
    const submitButton = form.querySelector("button[type='submit']");

    if (submitButton?.disabled) {
      return;
    }

    const formData = new FormData(form);
    if (submitButton) {
      submitButton.disabled = true;
    }

    fetch(form.action, {
      method: "POST",
      body: formData,
      credentials: "include",
      headers: {
        "X-Requested-With": "XMLHttpRequest",
      },
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error(`Send message failed with status ${response.status}`);
        }

        form.reset();
        suppressRefreshUntil = Date.now() + 2000;
        setTimeout(() => refreshConversation(0), 250);
      })
      .catch((error) => {
        console.error("Error sending message:", error);
      })
      .finally(() => {
        if (submitButton) {
          submitButton.disabled = false;
        }
      });
  };

  let loadOlderInFlight = false;

  const loadOlderMessages = () => {
    if (loadOlderInFlight || refreshInFlight) {
      return;
    }

    const nextOffset = currentOffset + pageSize;
    if (nextOffset >= totalMessages) {
      return;
    }

    loadOlderInFlight = true;

    const scrollContainer = document.querySelector(scrollContainerSelector);
    const conversationView = document.querySelector(conversationViewSelector);
    if (!conversationView) {
      loadOlderInFlight = false;
      return;
    }
    const previousHeight = scrollContainer?.scrollHeight ?? 0;
    const previousScroll = scrollContainer?.scrollTop ?? 0;

    fetch(
      `/plugin-io/api/conversational_messaging/conversation/${patientId}?limit=${pageSize}&offset=${nextOffset}`,
      {
        credentials: "include",
      }
    )
      .then((response) => {
        if (!response.ok) {
          throw new Error(`Conversation pagination failed with status ${response.status}`);
        }
        return response.text();
      })
      .then((html) => {
        const parser = new DOMParser();
        const doc = parser.parseFromString(html, "text/html");
        const docConversation = doc.getElementById("conversation-view");
        const currentConversation = document.querySelector(conversationViewSelector);

        if (!docConversation || !currentConversation) {
          return;
        }

        // Update load-more button state
        const existingLoadButton = currentConversation.querySelector(loadMoreButtonSelector);
        if (existingLoadButton) {
          existingLoadButton.remove();
        }

        const newLoadButton = docConversation.querySelector(loadMoreButtonSelector);
        if (newLoadButton) {
          currentConversation.insertBefore(newLoadButton.cloneNode(true), currentConversation.firstChild);
        }

        const anchor = currentConversation.querySelector(loadMoreButtonSelector)?.nextSibling || currentConversation.firstChild;
        const nodesToInsert = Array.from(docConversation.children).filter(
          (node) => node.id !== "load-more-btn"
        );

        nodesToInsert.forEach((node) => {
          currentConversation.insertBefore(node.cloneNode(true), anchor);
        });

        updateStateFromDoc(doc);

        if (scrollContainer) {
          const newHeight = scrollContainer.scrollHeight;
          scrollContainer.scrollTop = newHeight - (previousHeight - previousScroll);
        }
      })
      .catch((error) => {
        console.error("Error loading older messages:", error);
      })
      .finally(() => {
        loadOlderInFlight = false;
      });
  };

  chatContainer.addEventListener("click", (event) => {
    const loadMoreButton = event.target.closest(loadMoreButtonSelector);
    if (loadMoreButton) {
      event.preventDefault();
      loadOlderMessages();
      return;
    }

    const markAllButton = event.target.closest(markAllReadButtonSelector);
    if (!markAllButton) {
      return;
    }

    event.preventDefault();
    handleMarkAllReadClick();
  });

  chatContainer.addEventListener("submit", (event) => {
    if (!event.target.matches(sendMessageFormSelector)) {
      return;
    }

    event.preventDefault();
    handleSendMessageSubmit(event.target);
  });

  window.addEventListener("load", () => {
    const initialScrollContainer = document.querySelector(scrollContainerSelector);
    if (initialScrollContainer) {
      initialScrollContainer.scrollTop = initialScrollContainer.scrollHeight;
    }

    const socket = new WebSocket(
      `wss://${customerIdentifier}.canvasmedical.com/plugin-io/ws/conversational_messaging/${patientId}/`
    );

    socket.onmessage = () => {
      if (Date.now() < suppressRefreshUntil) {
        return;
      }
      refreshConversation(0);
    };

    setInterval(() => {
        if (socket.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({ type: 'ping' }));
        }
    }, 30000); // Send ping every 30 seconds

    socket.onerror = (error) => {
      console.error("WebSocket error:", error);
    };
  });
})();

