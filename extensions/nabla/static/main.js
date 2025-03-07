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
let noteSectionsCustomization = {};
let transcriptSeqId = 0;
let dictateSeqId = 0;

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
    document.getElementById("transcript").innerHTML = "<h3>Transcript:</h3>";
}

const clearNoteContent = () => {
    document.getElementById("note").innerHTML = "<h3>Note:</h3>";
}

const clearPatientInstructions = () => {
    document.getElementById("patient-instructions").innerHTML = "<h3>Patient instructions:</h3>";
}

const clearNormalizedData = () => {
    document.getElementById("normalized-data").innerHTML = "<h3>Normalized data:</h3>";
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

const startRecording = async () => {
    if (getFirstTranscriptLocale() === getSecondTranscriptLocale()) {
        const errorMessage = document.createElement("p");
        errorMessage.classList.add("error");
        errorMessage.innerText = "First and second transcript locales must be different."
        document.getElementById("transcript").appendChild(errorMessage)
        return;
    }
    clearTranscript();

    enableElementById("generate-btn");

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
            speech_locales: [getFirstTranscriptLocale(), getSecondTranscriptLocale()],
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

const getFirstTranscriptLocale = () => (
    document.getElementById("first-transcript-locale")?.selectedOptions[0]?.value ?? "ENGLISH_US"
)

const getSecondTranscriptLocale = () => (
    document.getElementById("second-transcript-locale")?.selectedOptions[0]?.value ?? "SPANISH_ES"
)

const generateNote = async () => {
    if (Object.keys(transcriptItems).length === 0) return;

    disableAll();

    stopAudio();
    await endConnection({ type: "END" });

    clearNoteContent();
    await digest();

    enableAll();
}

const digest = async () => {
    startThinking(document.getElementById("note"));

    const noteSectionsCustomizationArray = Object.entries(noteSectionsCustomization).map(
        ([sectionKey, customizationOptions]) => ({
            section_key: sectionKey,
            ...customizationOptions
        })
    );

    const bearerToken = await getOrRefetchUserAccessToken();
    const response = await fetch(`https://${CORE_API_BASE_URL}/user/generate-note`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${bearerToken}`
        },
        body: JSON.stringify({
            note_template: getNoteTemplate(),
            note_locale: getNoteLanguage(),
            patient_context: getPatientContext(),
            transcript_items: Object.values(transcriptItems).map((it) => ({ text: it, speaker_type: "unspecified" })),
            note_sections_customization: noteSectionsCustomizationArray,
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

    data.note.sections.forEach((section) => {
        const title = document.createElement("h4");
        title.innerHTML = section.title;
        const text = document.createElement("p");
        text.innerHTML = section.text;
        note.appendChild(title);
        note.appendChild(text);
    })
}

const getNoteTemplate = () => (
    document.getElementById("note-template")?.selectedOptions[0]?.value ?? "GENERIC_MULTIPLE_SECTIONS"
)

const getPatientContext = () => (
    document.getElementById("patient-context")?.value
)

const getNoteLanguage = () => (
    document.getElementById("note-locale")?.selectedOptions[0]?.value ?? "ENGLISH_US"
)

const generateNormalizedData = async () => {
    if (!generatedNote) return;

    disableAll();
    clearNormalizedData();
    const normalizationContainer = document.getElementById("normalized-data");
    startThinking(normalizationContainer);

    const note_locale = getNoteLanguage();
    if (!["FRENCH_FR", "ENGLISH_US", "ENGLISH_UK"].includes(note_locale)) {
        const errorMessage = document.createElement("p");
        errorMessage.classList.add("error");
        errorMessage.innerText = "Normalized data are only available for note with locale FRENCH_FR, ENGLISH_US, ENGLISH_UK"
        note.appendChild(errorMessage)
        return;
    }

    const bearerToken = await getOrRefetchUserAccessToken();
    const response = await fetch(`https://${CORE_API_BASE_URL}/user/generate-normalized-data`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${bearerToken} `
        },
        body: JSON.stringify({
            note: generatedNote,
            note_template: getNoteTemplate(),
            note_locale
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
            element.innerHTML += "<u>Categories:</u> [${ condition.categories.join() }]";
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
            note_template: getNoteTemplate(),
            instructions_locale: "ENGLISH_US",
            consultation_type: "IN_PERSON"
        })
    });

    if (!response.ok) {
        console.error('Error during note generation:', response.status);
    }

    const data = await response.json();

    stopThinking(patientInstructions);
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
    stopAudio();
    await endConnection({ type: "END" });
    clearNoteContent();
    clearNormalizedData();
    clearPatientInstructions();
    clearTranscript();
    enableElementById("start-btn");
    enableAll();
}


// Dictated notes -------------------------------------------------------------

const insertedDictatedItem = (data) => {
    const dictationContainer = document.getElementById("dictated-note");
    let dicatedItem = document.getElementById(data.id)
    if (!dicatedItem) {
        dicatedItem = document.createElement("span");
        dicatedItem.setAttribute("id", data.id);
        dicatedItem.setAttribute("data-start-offset", data.start_offset_ms);
        insertElementByStartOffset(dicatedItem, dictationContainer)
    }
    dicatedItem.innerHTML = data.text + "&nbsp;";
    if (data.is_final) {
        dicatedItem.classList.remove("temporary-item")
    } else if (!dicatedItem.classList.contains("temporary-item")) {
        dicatedItem.classList.add("temporary-item")
    }
}

const initializeDictationConnection = async () => {
    const bearerToken = await getOrRefetchUserAccessToken();
    websocket = new WebSocket(
        `wss://${CORE_API_BASE_URL}/user/dictate-ws`,
        ["dictate-protocol", "jwt-" + bearerToken]
    );

    websocket.onclose = (e) => {
        console.log(`Websocket closed: ${e.code} ${e.reason}`);
    };

    websocket.onmessage = (mes) => {
        if (websocket.readyState !== WebSocket.OPEN) {
            console.log("ws not open");
            return;
        }
        if (typeof mes.data === "string") {
            const data = JSON.parse(mes.data);

            if (data.type === "AUDIO_CHUNK_ACK") {
                // This is where you'd remove audio chunks from your buffer
            } else if (data.type === "DICTATION_ITEM") {
                insertedDictatedItem(data);
            } else if (data.type === "ERROR_MESSAGE") {
                console.error(data.message);
            }
        }
    };
}

const getDictationLocale = () => {
    const dictationLocaleSelect = document.getElementById("dictationLocale");
    return dictationLocaleSelect.selectedOptions && dictationLocaleSelect.selectedOptions.length > 0
        ? dictationLocaleSelect.selectedOptions[0].value
        : "ENGLISH_US";
}

const isPunctuationExplicit = () => {
    return document.getElementById("punctuation-switch").checked;
}

const startDictating = async () => {
    disableElementById("dictate-btn");
    enableElementById("pause-btn");

    dictateSeqId = 0;
    await initializeDictationConnection();

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
        await initializeMediaStream((audioAsBase64String) => (JSON.stringify({
            type: "AUDIO_CHUNK",
            payload: audioAsBase64String,
            seq_id: dictateSeqId++,
        })));

        const locale = getDictationLocale();
        const config = {
            type: "CONFIG",
            encoding: "PCM_S16LE",
            sample_rate: 16000,
            speech_locale: locale,
            dictate_punctuation: isPunctuationExplicit(),
            enable_audio_chunk_ack: true,
        };
        websocket.send(JSON.stringify(config));

        // pcm start
        pcmWorker.port.start();
    } else {
        console.error("Microphone audio stream is not accessible on this browser");
    }
}

const pauseDictating = async () => {
    disableElementById("pause-btn");
    stopAudio();
    await endConnection({ type: "END" });
    enableElementById("dictate-btn");
}


// Switch ambient encounter / dictated note ------------------------------------------

const showAmbientEncounter = () => {
    let ambientEncounterLink = document.getElementById("ambient-encounter-link");
    let dictatedNoteLink = document.getElementById("dictated-note-link");
    if (ambientEncounterLink.className.match("active")) return;

    ambientEncounterLink.classList.add("active");
    dictatedNoteLink.classList.remove("active");

    for (let element of document.getElementsByClassName("encounter")) {
        element.classList.remove("hide");
    }
    for (let element of document.getElementsByClassName("dictation")) {
        element.classList.add("hide");
    };
}

const showDictatedNote = () => {
    let ambientEncounterLink = document.getElementById("ambient-encounter-link");
    let dictatedNoteLink = document.getElementById("dictated-note-link");
    if (dictatedNoteLink.className.match("active")) return;

    ambientEncounterLink.classList.remove("active");
    dictatedNoteLink.classList.add("active");

    for (let element of document.getElementsByClassName("encounter")) {
        element.classList.add("hide");
    }

    for (let element of document.getElementsByClassName("dictation")) {
        element.classList.remove("hide");
    }
}

const initPage = () => {
    updateSectionsList();
    // Initial call to display an error message directly if the refresh token is expired:
    getOrRefetchUserAccessToken();
    document.getElementById("ambient-encounter-link").addEventListener("click", showAmbientEncounter);
    document.getElementById("dictated-note-link").addEventListener("click", showDictatedNote);
}

// Note customization ----------------------------------------------------------------

const templateSectionsMap = {
    "GENERIC_MULTIPLE_SECTIONS": [
        "CHIEF_COMPLAINT",
        "HISTORY_OF_PRESENT_ILLNESS",
        "PAST_MEDICAL_HISTORY",
        "PAST_SURGICAL_HISTORY",
        "PAST_OBSTETRIC_HISTORY",
        "FAMILY_HISTORY",
        "SOCIAL_HISTORY",
        "ALLERGIES",
        "CURRENT_MEDICATIONS",
        "IMMUNIZATIONS",
        "VITALS",
        "LAB_RESULTS",
        "IMAGING_RESULTS",
        "PHYSICAL_EXAM",
        "ASSESSMENT",
        "PLAN",
        "PRESCRIPTION",
        "APPOINTMENTS"
    ],
    "GENERIC_SOAP": [
        "SUBJECTIVE",
        "OBJECTIVE",
        "ASSESSMENT",
        "PLAN"
    ],
};

const onTemplateChange = () => {
    noteSectionsCustomization = {};
    updateSectionsList();
}

const updateSectionsList = () => {
    const template = getNoteTemplate();
    const selectElement = document.getElementById("note-sections");
    selectElement.innerHTML = "";

    const sections = templateSectionsMap[template] || [];
    sections.forEach((sectionKey) => {
        const opt = document.createElement("option");
        opt.value = sectionKey;
        opt.innerText = sectionKey;
        selectElement.appendChild(opt);
    });

    selectElement.value = sections[0] || "";
    onSectionToCustomizeChange();
}

const onSectionToCustomizeChange = () => {
    const selected = document.getElementById("note-sections").value;
    if (!selected) {
        document.getElementById("section-customization-fields").style.display = "none";
        return;
    }

    document.getElementById("section-customization-fields").style.display = "inline-block";
    const existing = noteSectionsCustomization[selected] || {};
    document.getElementById("style-select").value = existing.style || "AUTO";
    document.getElementById("custom-instruction").value = existing.custom_instruction || "";
}

const onSectionStyleChange = () => {
    const sectionKey = document.getElementById("note-sections").value;
    if (!sectionKey) return;

    const styleValue = document.getElementById("style-select").value;

    const customizationOptions = noteSectionsCustomization[sectionKey] ?? {};
    customizationOptions.style = styleValue;
    noteSectionsCustomization[sectionKey] = customizationOptions;
}

const onSectionCustomInstructionChange = () => {
    const sectionKey = document.getElementById("note-sections").value;
    if (!sectionKey) return;

    const customInstructionValue = document.getElementById("custom-instruction").value;

    const customizationOptions = noteSectionsCustomization[sectionKey] ?? {};
    customizationOptions.custom_instruction = customInstructionValue;
    noteSectionsCustomization[sectionKey] = customizationOptions;
}
