/* Voice Dictation — Scribe-style UI with audio level + silence warnings */
(function () {
  var config = JSON.parse(document.getElementById('dictate-config').textContent);
  var NOTE_UUID = config.noteUuid;
  var API_BASE = '/plugin-io/api/voice_dictation/dictate';

  /* Constants */
  var SILENCE_RMS_THRESHOLD = 0.01;
  var SILENCE_WARNING_SECONDS = 7.5;

  /* State */
  var status = 'idle';
  var commandType = 'hpi';
  var seconds = 0;
  var timerInterval = null;
  var confirmingFinish = false;
  var confirmTimer = null;
  var mediaRecorder = null;
  var audioChunks = [];
  var micStream = null;
  var transcript = '';

  /* Audio analysis state */
  var audioContext = null;
  var analyserNode = null;
  var audioLevel = 0;
  var levelInterval = null;
  var lastAudioTime = 0;
  var silenceWarning = false;
  var silenceCheckInterval = null;

  var app = document.getElementById('app');

  function fmtTime(s) {
    var m = Math.floor(s / 60);
    var sec = s % 60;
    return m + ':' + (sec < 10 ? '0' : '') + sec;
  }

  function escapeHtml(str) {
    var d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
  }

  /* --- Audio level analysis --- */
  function startAudioAnalysis(stream) {
    audioContext = new (window.AudioContext || window.webkitAudioContext)();
    var source = audioContext.createMediaStreamSource(stream);
    analyserNode = audioContext.createAnalyser();
    analyserNode.fftSize = 256;
    source.connect(analyserNode);

    var dataArray = new Float32Array(analyserNode.fftSize);
    lastAudioTime = Date.now();
    silenceWarning = false;

    /* Poll audio level ~15fps */
    levelInterval = setInterval(function () {
      if (!analyserNode) return;
      analyserNode.getFloatTimeDomainData(dataArray);

      /* RMS calculation */
      var sum = 0;
      for (var i = 0; i < dataArray.length; i++) sum += dataArray[i] * dataArray[i];
      var rms = Math.sqrt(sum / dataArray.length);
      audioLevel = rms;

      if (rms >= SILENCE_RMS_THRESHOLD) {
        lastAudioTime = Date.now();
        if (silenceWarning) { silenceWarning = false; updateWarning(); }
      }

      updateLevelDot();
    }, 66);

    /* Silence check every 2s */
    silenceCheckInterval = setInterval(function () {
      if (status !== 'recording') return;
      var elapsed = (Date.now() - lastAudioTime) / 1000;
      if (elapsed >= SILENCE_WARNING_SECONDS && !silenceWarning) {
        silenceWarning = true;
        updateWarning();
      }
    }, 2000);
  }

  function stopAudioAnalysis() {
    if (levelInterval) { clearInterval(levelInterval); levelInterval = null; }
    if (silenceCheckInterval) { clearInterval(silenceCheckInterval); silenceCheckInterval = null; }
    if (audioContext) { audioContext.close(); audioContext = null; }
    analyserNode = null;
    audioLevel = 0;
    silenceWarning = false;
  }

  function updateLevelDot() {
    var dot = document.getElementById('level-dot');
    if (!dot) return;
    var scale = 1 + Math.min(audioLevel * 10, 1.2);
    var opacity = 0.5 + Math.min(audioLevel * 8, 0.5);
    dot.style.transform = 'scale(' + scale + ')';
    dot.style.opacity = opacity;
  }

  function updateWarning() {
    var el = document.getElementById('silence-warning');
    if (el) el.style.display = silenceWarning ? 'flex' : 'none';
  }

  /* --- Recording --- */
  function startRecording() {
    audioChunks = [];
    seconds = 0;
    transcript = '';
    navigator.mediaDevices.getUserMedia({ audio: true }).then(function (stream) {
      micStream = stream;
      mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' });
      mediaRecorder.ondataavailable = function (e) { if (e.data.size > 0) audioChunks.push(e.data); };
      mediaRecorder.start(1000);
      startAudioAnalysis(stream);
      status = 'recording';
      timerInterval = setInterval(function () { seconds++; renderTimer(); }, 1000);
      render();
    }).catch(function () { alert('Microphone access denied.'); });
  }

  function pauseRecording() {
    if (mediaRecorder && mediaRecorder.state === 'recording') {
      mediaRecorder.pause();
      status = 'paused';
      clearInterval(timerInterval);
      render();
    }
  }

  function resumeRecording() {
    if (mediaRecorder && mediaRecorder.state === 'paused') {
      mediaRecorder.resume();
      status = 'recording';
      lastAudioTime = Date.now();
      silenceWarning = false;
      timerInterval = setInterval(function () { seconds++; renderTimer(); }, 1000);
      render();
    }
  }

  function finishRecording() {
    if (!confirmingFinish) {
      confirmingFinish = true;
      render();
      confirmTimer = setTimeout(function () { confirmingFinish = false; render(); }, 5000);
      return;
    }
    clearTimeout(confirmTimer);
    confirmingFinish = false;
    clearInterval(timerInterval);
    stopAudioAnalysis();
    if (mediaRecorder && mediaRecorder.state !== 'inactive') {
      status = 'transcribing';
      render();
      mediaRecorder.onstop = function () {
        if (micStream) { micStream.getTracks().forEach(function (t) { t.stop(); }); micStream = null; }
        doTranscribe();
      };
      mediaRecorder.stop();
    }
  }

  /* --- Transcription --- */
  function doTranscribe() {
    var blob = new Blob(audioChunks, { type: 'audio/webm' });
    var fd = new FormData();
    fd.append('audio', blob, 'recording.webm');
    fetch(API_BASE + '/transcribe', { method: 'POST', body: fd }).then(function (r) {
      return r.text().then(function (t) {
        var d; try { d = JSON.parse(t); } catch (e) { d = { error: t || '(empty)' }; }
        return { ok: r.ok, data: d };
      });
    }).then(function (res) {
      if (!res.ok) { status = 'idle'; alert('Transcription failed: ' + (res.data.error || '')); render(); return; }
      transcript = res.data.transcript || '';
      status = 'done';
      render();
      var el = document.getElementById('transcript-input');
      if (el) el.value = transcript;
    }).catch(function (err) { status = 'idle'; alert('Network error: ' + err.message); render(); });
  }

  /* --- Command creation --- */
  function submitTranscript() {
    var el = document.getElementById('transcript-input');
    var text = el ? (el.value || '').trim() : transcript.trim();
    if (!text) { alert('Transcript is empty.'); return; }
    var url = API_BASE + '/create/' + commandType + '?note_id=' + encodeURIComponent(NOTE_UUID);
    var fd = new FormData();
    fd.append('transcript', text);
    var btn = document.getElementById('submit-btn');
    if (btn) btn.disabled = true;
    fetch(url, { method: 'POST', body: fd }).then(function (r) {
      return r.text().then(function (t) {
        var d; try { d = JSON.parse(t); } catch (e) { d = { error: t || '(empty)' }; }
        return { ok: r.ok, data: d };
      });
    }).then(function (res) {
      if (!res.ok) { alert('Failed: ' + (res.data.error || '')); if (btn) btn.disabled = false; return; }
      status = 'idle'; transcript = ''; audioChunks = []; seconds = 0; render();
    }).catch(function (err) { alert('Network error: ' + err.message); if (btn) btn.disabled = false; });
  }

  function resetAll() {
    clearInterval(timerInterval); clearTimeout(confirmTimer);
    stopAudioAnalysis();
    if (mediaRecorder && mediaRecorder.state !== 'inactive') mediaRecorder.stop();
    if (micStream) { micStream.getTracks().forEach(function (t) { t.stop(); }); micStream = null; }
    status = 'idle'; transcript = ''; audioChunks = []; seconds = 0; confirmingFinish = false; render();
  }

  function selectType(type) { commandType = type; render(); }
  function renderTimer() { var el = document.getElementById('timer-display'); if (el) el.textContent = fmtTime(seconds); }

  /* --- Icons --- */
  var micSvg = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="1" width="6" height="13" rx="3"/><path d="M5 10a7 7 0 0014 0"/><line x1="12" y1="21" x2="12" y2="17"/><line x1="8" y1="21" x2="16" y2="21"/></svg>';
  var pauseSvg = '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/></svg>';
  var playSvg = '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><polygon points="6,4 20,12 6,20"/></svg>';
  var checkSvg = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>';
  var warnSvg = '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z"/></svg>';

  /* --- Render --- */
  function render() {
    var isRec = (status === 'recording' || status === 'paused');
    var h = '<div class="top-bar">';

    if (status === 'transcribing') {
      h += '<div class="status-bar finishing"><span class="spinner"></span> Transcribing...</div>';
    } else if (isRec) {
      h += '<div class="status-bar ' + (status === 'recording' ? 'recording' : 'paused') + '">';
      if (status === 'recording') {
        h += '<span class="level-dot" id="level-dot"></span>';
      } else {
        h += '<span class="pulse-dot"></span>';
      }
      h += ' ' + (status === 'recording' ? 'Recording' : 'Paused');
      h += ' <span class="timer" id="timer-display">' + fmtTime(seconds) + '</span></div>';
    } else if (status === 'done') {
      h += '<span class="transcript-label-inline">' + (commandType === 'hpi' ? 'HPI' : 'Plan') + '</span>';
    } else {
      h += '<div class="type-pills">';
      h += '<button class="type-pill' + (commandType === 'hpi' ? ' active' : '') + '" onclick="__d.selectType(\'hpi\')">HPI</button>';
      h += '<button class="type-pill' + (commandType === 'plan' ? ' active' : '') + '" onclick="__d.selectType(\'plan\')">Plan</button></div>';
    }

    h += '<div class="top-bar-spacer"></div><div class="recording-controls">';
    if (status === 'idle') {
      h += '<button class="start-btn" onclick="__d.startRecording()">' + micSvg + ' Record</button>';
    } else if (status === 'recording') {
      h += '<button class="control-btn" onclick="__d.pauseRecording()">' + pauseSvg + ' Pause</button>';
      h += '<button class="finish-btn' + (confirmingFinish ? ' confirming' : '') + '" onclick="__d.finishRecording()">' + checkSvg + (confirmingFinish ? ' Confirm?' : ' Finish') + '</button>';
    } else if (status === 'paused') {
      h += '<button class="control-btn" onclick="__d.resumeRecording()">' + playSvg + ' Resume</button>';
      h += '<button class="finish-btn' + (confirmingFinish ? ' confirming' : '') + '" onclick="__d.finishRecording()">' + checkSvg + (confirmingFinish ? ' Confirm?' : ' Finish') + '</button>';
    } else if (status === 'done') {
      h += '<button class="reset-btn" onclick="__d.resetAll()">Discard</button>';
      h += '<button id="submit-btn" class="submit-btn" onclick="__d.submitTranscript()">Add to Note</button>';
    }
    h += '</div></div>';

    /* Silence warning bar */
    if (isRec) {
      h += '<div class="silence-warning" id="silence-warning" style="display:' + (silenceWarning ? 'flex' : 'none') + '">';
      h += warnSvg + ' No audio detected \u2014 check microphone permissions and unmute</div>';
    }

    h += '<div class="content">';
    if (status === 'done') {
      h += '<textarea id="transcript-input" class="transcript-text" placeholder="Edit transcript..."></textarea>';
    } else if (status === 'transcribing') {
      h += '<div class="empty-state"><span class="spinner" style="width:20px;height:20px;border-width:2px"></span><p>Transcribing...</p></div>';
    } else if (isRec) {
      h += '<div class="empty-state"><svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="' + (status === 'recording' ? '#b91c1c' : '#999') + '" stroke-width="1.5"><rect x="9" y="1" width="6" height="13" rx="3"/><path d="M5 10a7 7 0 0014 0"/><line x1="12" y1="21" x2="12" y2="17"/><line x1="8" y1="21" x2="16" y2="21"/></svg>';
      h += '<p>' + (status === 'paused' ? 'Paused' : 'Listening...') + '</p></div>';
    } else {
      h += '<div class="empty-state"><svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#999" stroke-width="1.5"><rect x="9" y="1" width="6" height="13" rx="3"/><path d="M5 10a7 7 0 0014 0"/><line x1="12" y1="21" x2="12" y2="17"/><line x1="8" y1="21" x2="16" y2="21"/></svg>';
      h += '<p>Select HPI or Plan, then Record.</p></div>';
    }
    h += '</div>';

    app.innerHTML = h;

    if (status === 'done' && transcript) {
      var txEl = document.getElementById('transcript-input');
      if (txEl && !txEl.value) txEl.value = transcript;
    }
  }

  window.__d = { startRecording: startRecording, pauseRecording: pauseRecording, resumeRecording: resumeRecording, finishRecording: finishRecording, submitTranscript: submitTranscript, resetAll: resetAll, selectType: selectType };
  render();
})();
