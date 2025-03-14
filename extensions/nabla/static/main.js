const INITIAL_USER_ACCESS_TOKEN = window._canvas_nabla_extension_user_access_token;
const INITIAL_USER_REFRESH_TOKEN = window._canvas_nabla_extension_user_refresh_token;
const REGION = "us" // "us" or "eu"

let generatedNote = undefined;
let websocket;
let transcriptItems = {};
let audioContext;
let pcmWorker;
let mediaSource;
let mediaStream
let thinkingId;
const rawPCM16WorkerName = "raw-pcm-16-worker";
let transcriptSeqId = 0;

const CORE_API_BASE_URL = `${REGION}.api.nabla.com/v1/core`;

// Authentication utilities

let userAccessToken = INITIAL_USER_ACCESS_TOKEN;
let userRefreshToken = INITIAL_USER_REFRESH_TOKEN;

const showTokenError = (message) => {
    const errorDiv = document.getElementById("token-error");
    if (!errorDiv) return;
    errorDiv.innerHTML = message;
    errorDiv.classList.remove("hide");
}

const decodeJWT = (token) => {
    const parts = token.split('.');
    if (parts.length !== 3) {
        showTokenError("The user tokens seem invalid. You maybe forgot to provide initial tokens in the source code.");
        throw new Error("Invalid JWT token");
    }
    const payload = parts[1];
    return JSON.parse(atob(payload.replace(/-/g, '+').replace(/_/g, '/'))); // replace URL-safe characters
}

const isTokenExpiredOrExpiringSoon = (token) => {
    const nowSeconds = Math.floor(Date.now() / 1000);
    return (decodeJWT(token).exp - nowSeconds) < 5;
}

const setUserTokens = (newAccessToken, newRefreshToken) => {
    userAccessToken = newAccessToken;
    userRefreshToken = newRefreshToken;
}

const getOrRefetchUserAccessToken = async () => {
    if (!isTokenExpiredOrExpiringSoon(userAccessToken)) {
        return userAccessToken;
    }

    if (isTokenExpiredOrExpiringSoon(userRefreshToken)) {
        showTokenError("Your user refresh token has expired. Please provide new initial tokens in the source code.");
        throw new Error("Refresh token expired");
    }

    const refreshResponse = await fetch(`https://${CORE_API_BASE_URL}/user/jwt/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: userRefreshToken }),
    });
    if (!refreshResponse.ok) {
        showTokenError("The user access token refresh failed. Please try to provide new initial tokens in the source code.");
        throw new Error(`Refresh call failed (status: ${refreshResponse.status})`);
    }

    const data = await refreshResponse.json();
    setUserTokens(data.access_token, data.refresh_token);
}

// Common utilities -----------------------------------------------------------

const disableElementById = (elementId) => {
    const element = document.getElementById(elementId);
    if (element.hasAttribute("disabled")) return;
    element.setAttribute("disabled", "disabled");
}

const enableElementById = (elementId) => {
    const element = document.getElementById(elementId);
    if (!element.hasAttribute("disabled")) return;
    element.removeAttribute("disabled");
}

const toggleStartStopVisibility = () => {
    const startButton = document.getElementById("start-btn");
    const stopButton = document.getElementById("stop-btn");
    startButton.classList.toggle("hide");
    stopButton.classList.toggle("hide");
}

const ensureStartButtonVisibility = () => {
    const startButton = document.getElementById("start-btn");
    const stopButton = document.getElementById("stop-btn");
    startButton.classList.remove("hide");
    stopButton.classList.add("hide");
}

const startThinking = (parent) => {
    const thinking = document.createElement("div");
    thinking.setAttribute("id", "thinking");
    let count = 0;
    thinkingId = setInterval(() => {
        const dots = ".".repeat(count % 3 + 1)
        thinking.innerHTML = `Thinking${dots} `
        count++;
    }, 500);
    parent.appendChild(thinking);
}

const stopThinking = (parent) => {
    clearInterval(thinkingId);
    if (!parent) return;
    const thinking = document.getElementById("thinking");
    parent.removeChild(thinking);
}

const endConnection = async (endObject) => {
    if (!websocket || websocket.readyState !== WebSocket.OPEN) return;

    websocket.send(JSON.stringify(endObject));

    // Await server closing the WS
    for (let i = 0; i < 50; i++) {
        if (websocket.readyState === WebSocket.OPEN) {
            await sleep(100);
        } else {
            break;
        }
    }
}

const initializeMediaStream = async (buildAudioChunk) => {
    // Ask authorization to access the microphone
    mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
            deviceId: "default",
            sampleRate: 16000,
            sampleSize: 16,
            channelCount: 1,
        },
        video: false,
    });
    audioContext = new AudioContext({ sampleRate: 16000 });
    await audioContext.audioWorklet.addModule("rawPcm16Processor.js")
    pcmWorker = new AudioWorkletNode(audioContext, rawPCM16WorkerName, {
        outputChannelCount: [1],
    });
    mediaSource = audioContext.createMediaStreamSource(mediaStream);
    mediaSource.connect(pcmWorker);

    // pcm post on message
    pcmWorker.port.onmessage = (msg) => {
        const pcm16iSamples = msg.data;
        const audioAsBase64String = btoa(
            String.fromCodePoint(...new Uint8Array(pcm16iSamples.buffer)),
        );
        if (websocket.readyState !== websocket.OPEN) {
            console.error("Websocket is no longer open")
            return;
        }

        websocket.send(buildAudioChunk(audioAsBase64String))
    }
}

const stopAudio = () => {
    try {
        audioContext?.close();
    } catch (e) {
        console.error("Error while closing AudioContext", e);
    }

    try {
        pcmWorker?.port.close();
        pcmWorker?.disconnect();
    } catch (e) {
        console.error("Error while closing PCM worker", e);
    }

    try {
        mediaSource?.mediaStream.getTracks().forEach((track) => track.stop());
        mediaSource?.disconnect();
    } catch (e) {
        console.error("Error while closing media stream", e);
    }
}

const insertElementByStartOffset = (element, parentElement) => {
    const elementStartOffset = element.getAttribute["data-start-offset"]
    let elementBefore = null;
    for (let childElement of parentElement.childNodes) {
        const childStartOffset =
            childElement.nodeName === element.nodeName && childElement.hasAttribute("data-start-offset")
                ? childElement.getAttribute("data-start-offset")
                : 0
        if (childStartOffset > elementStartOffset) {
            elementBefore = childElement;
            break;
        }
    }
    if (elementBefore) {
        parentElement.insertBefore(element, elementBefore);
    } else {
        parentElement.appendChild(element);
    }
}

// Transcript -----------------------------------------------------------------

// Utilities

const disableAll = () => {
    disableElementById("start-btn");
    disableElementById("generate-btn");
    disableElementById("normalize-btn");
    disableElementById("patient-instructions-btn");
}

const enableAll = () => {
    enableElementById("start-btn");
    enableElementById("generate-btn");
    enableElementById("normalize-btn");
    enableElementById("patient-instructions-btn");
}

const clearTranscript = () => {
    document.getElementById("transcript").innerHTML = "";
}

const clearNoteContent = () => {
    document.getElementById("note").innerHTML = "";
}

const clearPatientInstructions = () => {
    document.getElementById("patient-instructions").innerHTML = "";
}

const clearNormalizedData = () => {
    document.getElementById("normalized-data").innerHTML = "";
}

const msToTime = (milli) => {
    const seconds = Math.floor((milli / 1000) % 60);
    const minutes = Math.floor((milli / (60 * 1000)) % 60);
    return `${String(minutes).padStart(2, 0)}:${String(seconds).padStart(2, 0)}`;
};

const insertTranscriptItem = (data) => {
    transcriptItems[data.id] = data.text;
    const transcriptContent =
        `[${msToTime(data.start_offset_ms)} to ${msToTime(data.end_offset_ms)}]: ${data.text}`;
    const transcriptContainer = document.getElementById("transcript");
    let transcriptItem = document.getElementById(data.id)
    if (!transcriptItem) {
        transcriptItem = document.createElement("div");
        transcriptItem.setAttribute("id", data.id);
        transcriptItem.setAttribute("data-start-offset", data.start_offset_ms);
        insertElementByStartOffset(transcriptItem, transcriptContainer)
    }
    transcriptItem.innerHTML = transcriptContent;
    if (data.is_final) {
        transcriptItem.classList.remove("temporary-item")
    } else if (!transcriptItem.classList.contains("temporary-item")) {
        transcriptItem.classList.add("temporary-item")
    }
}

const initializeTranscriptConnection = async () => {
    // Ideally we'd send the authentication token in an 'Authorization': 'Bearer <YOUR_TOKEN>' header.
    // But since JS WS client does not support sending additional headers,
    // we rely on this alternative authentication mechanism.
    const bearerToken = await getOrRefetchUserAccessToken();
    websocket = new WebSocket(
        `wss://${CORE_API_BASE_URL}/user/transcribe-ws`,
        ["transcribe-protocol", "jwt-" + bearerToken],
    );

    websocket.onclose = (e) => {
        console.log(`Websocket closed: ${e.code} ${e.reason}`);
    };

    websocket.onmessage = (mes) => {
        if (websocket.readyState !== WebSocket.OPEN) return;
        if (typeof mes.data === "string") {
            const data = JSON.parse(mes.data);

            if (data.type === "AUDIO_CHUNK_ACK") {
                // This is where you'd remove audio chunks from your buffer
            } else if (data.type === "TRANSCRIPT_ITEM") {
                insertTranscriptItem(data);
            } else if (data.type === "ERROR_MESSAGE") {
                console.error(data.message);
            }
        }
    };
}

const sleep = (duration) => new Promise((r) => setTimeout(r, duration));

const stopRecording = async () => {
    enableElementById("generate-btn");
    stopAudio();
    await endConnection({ type: "END" });
    toggleStartStopVisibility();
    enableAll();
}


const startRecording = async () => {
    toggleStartStopVisibility();

    clearTranscript();

    transcriptSeqId = 0;
    await initializeTranscriptConnection();

    // Await websocket being open
    for (let i = 0; i < 10; i++) {
        if (websocket.readyState !== WebSocket.OPEN) {
            await sleep(100);
        } else {
            break;
        }
    }
    if (websocket.readyState !== WebSocket.OPEN) {
        throw new Error("Websocket did not open");
    }

    if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
        await initializeMediaStream((audioAsBase64String) => {
            return JSON.stringify({
                type: "AUDIO_CHUNK",
                payload: audioAsBase64String,
                stream_id: "stream1",
                seq_id: transcriptSeqId++,
            })
        })

        const config = {
            type: "CONFIG",
            encoding: "PCM_S16LE",
            sample_rate: 16000,
            speech_locales: ["ENGLISH_US"],
            streams: [
                { id: "stream1", speaker_type: "unspecified" },
            ],
            enable_audio_chunk_ack: true,
        };
        websocket.send(JSON.stringify(config));

        // pcm start
        pcmWorker.port.start();
    } else {
        console.error("Microphone audio stream is not accessible on this browser");
    }
}

const generateNote = async () => {
    if (Object.keys(transcriptItems).length === 0) return;

    disableAll();

    clearNoteContent();
    await digest();

    enableAll();
}

const digest = async () => {
    startThinking(document.getElementById("note"));

    const bearerToken = await getOrRefetchUserAccessToken();
    const response = await fetch(`https://${CORE_API_BASE_URL}/user/generate-note`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${bearerToken}`
        },
        body: JSON.stringify({
            note_template: "GENERIC_MULTIPLE_SECTIONS",
            note_locale: "ENGLISH_US",
            transcript_items: Object.values(transcriptItems).map((it) => ({ text: it, speaker_type: "unspecified" })),
        })
    });

    const note = document.getElementById("note");
    stopThinking(note);

    if (!response.ok) {
        console.error('Error during note generation:', response.status);
        const errData = await response.json();
        const errText = document.createElement("p");
        errText.classList.add("error");
        errText.innerHTML = errData.message;
        note.appendChild(errText)
        return;
    }

    const data = await response.json();
    generatedNote = data.note;

    const sectionTitle = document.createElement("h3");
    sectionTitle.innerHTML = "Note";
    note.appendChild(sectionTitle);

    data.note.sections.forEach((section) => {
        const title = document.createElement("h4");
        title.innerHTML = section.title;
        const text = document.createElement("p");
        text.innerHTML = section.text;
        note.appendChild(title);
        note.appendChild(text);
    })
}

const generateNormalizedData = async () => {
    if (!generatedNote) return;

    disableAll();
    clearNormalizedData();
    const normalizationContainer = document.getElementById("normalized-data");
    startThinking(normalizationContainer);

    const bearerToken = await getOrRefetchUserAccessToken();
    const response = await fetch(`https://${CORE_API_BASE_URL}/user/generate-normalized-data`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${bearerToken} `
        },
        body: JSON.stringify({
            note: generatedNote,
            note_template: "GENERIC_MULTIPLE_SECTIONS",
            note_locale: "ENGLISH_US"
        })
    });

    stopThinking(normalizationContainer);

    if (!response.ok) {
        console.error('Error during normalized data generation:', response.status);
        const errData = await response.json();
        const errText = document.createElement("p");
        errText.classList.add("error");
        errText.innerHTML = errData.message;
        normalizationContainer.appendChild(errText);
        return;
    }

    const data = await response.json();

    const sectionTitle = document.createElement("h3");
    sectionTitle.innerHTML = "Normalized Data";
    normalizationContainer.appendChild(sectionTitle);

    const conditionTitle = document.createElement("h4");
    conditionTitle.innerHTML = "Conditions:";
    normalizationContainer.appendChild(conditionTitle);

    addConditions(data.conditions, normalizationContainer);

    const familyHistoryTitle = document.createElement("h4");
    familyHistoryTitle.innerHTML = "Family history:";
    normalizationContainer.appendChild(familyHistoryTitle);

    const historyList = document.createElement("ul");
    data.family_history.forEach((member) => {
        const memberListItem = document.createElement("li");
        const relationship = document.createElement("span");
        relationship.innerText = member.relationship;
        memberListItem.appendChild(relationship);
        addConditions(member.conditions, memberListItem);
        historyList.appendChild(memberListItem);
    })
    normalizationContainer.appendChild(historyList);

    enableAll();
}

const addConditions = (conditions, parent) => {
    const conditionsList = document.createElement("ul");
    conditions.forEach((condition) => {
        const element = document.createElement("li");
        element.innerHTML = `${condition.coding.display.toUpperCase()} (${condition.coding.code})<br /><u>Clinical status:</u> ${condition.clinical_status}<br />`;
        if (condition.categories.length > 0) {
            element.innerHTML += `<u>Categories:</u> [${ condition.categories.join() }]`;
        }
        conditionsList.appendChild(element);
    })
    parent.appendChild(conditionsList);
}

const generatePatientInstructions = async () => {
    if (!generatedNote) return;

    clearPatientInstructions();
    disableAll();
    const patientInstructions = document.getElementById("patient-instructions");
    startThinking(patientInstructions);

    const bearerToken = await getOrRefetchUserAccessToken();
    const response = await fetch(`https://${CORE_API_BASE_URL}/user/generate-patient-instructions`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${bearerToken} `
        },
        body: JSON.stringify({
            note: generatedNote,
            note_locale: "ENGLISH_US",
            note_template: "GENERIC_MULTIPLE_SECTIONS",
            instructions_locale: "ENGLISH_US",
            consultation_type: "IN_PERSON"
        })
    });

    if (!response.ok) {
        console.error('Error during note generation:', response.status);
    }

    const data = await response.json();

    stopThinking(patientInstructions);

    const sectionTitle = document.createElement("h3");
    sectionTitle.innerHTML = "Patient Instructions";
    patientInstructions.appendChild(sectionTitle);

    const instructionsTitle = document.createElement("h4");
    instructionsTitle.innerHTML = "Instructions: ";
    patientInstructions.appendChild(instructionsTitle);

    const text = document.createElement("p");
    text.innerHTML = data.instructions;
    patientInstructions.appendChild(text);
    enableAll();
}

const clearEncounter = async () => {
    disableElementById("start-btn");
    disableAll();
    clearNoteContent();
    clearNormalizedData();
    clearPatientInstructions();
    clearTranscript();
    ensureStartButtonVisibility();
    enableElementById("start-btn");
}

const initPage = () => {
    // Initial call to display an error message directly if the refresh token is expired:
    getOrRefetchUserAccessToken();
    disableAll();
    ensureStartButtonVisibility();
    enableElementById("start-btn");
}
