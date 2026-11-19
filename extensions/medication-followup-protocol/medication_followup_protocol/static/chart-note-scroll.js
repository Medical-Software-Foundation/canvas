/* Scrolling the same origin chart to one of its own notes, shared by the note scoped
   pane and the patient scoped pane, which are one page now, program_panel.html.

   Both panes sit in a same origin iframe over the chart and both carry a link back to a
   note. Left as two copies, the note wrapper's markup, its data-test attribute, its
   collapsed class and its toggle selector would have to be read off the running chart
   twice, and the day Canvas changes any of it only one copy would get fixed. So the read
   lives here once, and each page loads this file and calls the one function it exposes.

   window.mfpChartNote.scrollTo takes the note as an explicit argument rather than reading
   it off a page level state object, because the note scoped pane holds the one note its
   whole pane is open on while the patient scoped pane holds one note per section, so the
   two callers have nowhere in common to read it from. note carries dbid, at and
   provider_name, the three fields both pages already have on hand for their own note. */
(function () {
  "use strict";

  // --- The moment, in the shape the note prints it
  //
  // Two formatters rather than one, and both locales are deliberate.
  //
  // The clock and the date are forced to US style because that is what the home app
  // prints on a note, 8/20/26 and 9:00 AM, and it prints it that way whatever locale the
  // browser is set to. Following the browser gave 20/08/2026 and 09:00 beside a note
  // reading 8/20/26 and 9:00 AM, which is the opposite of recognisable.
  //
  // The zone comes from the British locale for one narrow reason. Asked for a short zone
  // name, the US locale answers GMT+2 for a European zone while the British one answers
  // CEST, which is the abbreviation the note shows. For US zones the two agree, so this
  // is the wider of the two answers rather than a preference. Both are read off the same
  // instant, so they cannot disagree about the time itself.
  function noteMoment(at) {
    var weekday = at.toLocaleDateString("en-US", { weekday: "long" });
    var date = at.toLocaleDateString("en-US", {
      month: "numeric", day: "numeric", year: "2-digit"
    });
    var clock = at.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
    var zone = "";
    var parts = new Intl.DateTimeFormat("en-GB", {
      hour: "numeric", timeZoneName: "short"
    }).formatToParts(at);
    for (var i = 0; i < parts.length; i++) {
      if (parts[i].type === "timeZoneName") { zone = parts[i].value; }
    }
    return weekday + ", " + date + " at " + clock + (zone ? " " + zone : "");
  }

  /* --- Finding this note in the chart, since the platform names nothing for us to ask
     The note wrapper the chart renders carries a data-test attribute reading note and a
     class naming the note type, and nothing else. Read off the running chart rather than
     guessed from the component that draws it, the wrapper holds no id, no data attribute
     and no link anywhere inside it naming which note in the database it is, collapsed or
     expanded. So there is no handle to ask for by id, only a sentence to recognise.

     That sentence is the note header timestamp, and it is worth trusting because both
     sides compute it from the same record rather than one copying the other. The caller
     already carries the identical weekday, date, clock and time zone for its own note
     line, which is why the two read as one sentence rather than a paraphrase of it. The
     match stops after the provider rather than reaching for the location, because a
     supervising provider prints extra words between the provider and the location, and a
     match that reached past the provider would break exactly there.

     This is still a seam into a page nobody wrote a contract for. A future note header
     can reword that sentence, drop the attribute, or stop rendering it at all, and on that
     day this finds nothing, returns false, and the caller falls through to the anchor
     below rather than scrolling nowhere silently. Fixing it then means reading the new
     chart the same way this one was read, there is no supported alternative to reach for
     first. */
  /* --- Why the moment and the provider are matched separately
     The sentence was originally matched as one prefix, On the moment then with the
     provider. That silently failed for every note tied to a scheduled appointment, because
     the chart writes the duration between the two, reading On Thursday, 8/20/26 at 1:00 PM
     CEST for 20 min with Larry Weed, and a prefix built without that clause stops matching
     at the word for. Driven on a real chart, an appointment note was never found and its
     link reloaded the page every time, which is the whole complaint this file exists to fix.

     So the moment is matched as the opening of the sentence and the provider is looked for
     anywhere after it, which reads both shapes. Nothing is loosened by that, the moment
     still has to begin the sentence to the minute including the time zone, and the
     ambiguity guard below still refuses two notes that both answer. */
  function findNoteInChart(doc, note) {
    var at = note.at ? new Date(note.at) : null;
    if (!at || isNaN(at.getTime())) { return null; }
    var opening = "On " + noteMoment(at);
    var provider = note.provider_name ? "with " + note.provider_name : "";
    var stamps = doc.querySelectorAll('[data-test="note-header-timestamp"]');
    var target = null;
    for (var i = 0; i < stamps.length; i++) {
      var text = stamps[i].textContent.replace(/\s+/g, " ").trim();
      if (text.indexOf(opening) !== 0) { continue; }
      if (provider && text.indexOf(provider, opening.length) === -1) { continue; }
      // More than one note reads the same sentence, which should not happen for a real
      // chart, so this refuses the guess rather than picking either one.
      if (target) { return null; }
      target = stamps[i].closest('[data-test="note"]');
    }
    return target;
  }

  /* --- Expanding it first, without the flag the chart itself needs
     The chart's own react to a permalink is gated behind a practice setting that is off
     here, and reads it once on mount rather than on every change, which is the reason a
     second click on an already mounted note never moved it. The note's own collapse
     toggle carries no such gate, a click on its header flips a plain local state whatever
     that setting is, so this reaches for that click rather than the permalink machinery
     the chart never runs locally. */
  function expandNoteIfCollapsed(noteEl) {
    if (!noteEl.classList.contains("note-is-collapsed")) { return; }
    var toggle = noteEl.querySelector("a.note-header-toggle");
    if (toggle) { toggle.click(); }
  }

  /* --- Scrolling the chart without reloading it
     The pane is a same origin iframe carrying no sandbox attribute, so it can reach into
     the document above it directly rather than asking the chart to do the scrolling. The
     chart's own machinery for that is a React ref that only fires the moment a note
     mounts, never again for a note already sitting in the list, which is why the note
     never moved on a second click. Scrolling the element found above sidesteps that ref
     entirely and has no reason to stop working on a third click or a tenth.

     The hash is still set alongside it, deferred by a frame the same way it always was,
     because it costs nothing and it keeps the address bar honest, and it would let the
     chart's own permalink handling take over on an instance where the practice setting
     above is on. Nothing here relies on it doing anything by itself.

     This reaches out of the frame because the platform offers no way to ask. Its message
     channel carries only opening, closing and resizing, so there is no navigate message to
     send. If Canvas ever sandboxes this iframe the read below throws, the anchor above
     takes over, and the failure is a full chart load rather than nothing happening.

     Returns whether it actually scrolled, which is what lets a caller preventDefault only
     when the click really moved something, so a page this could not read, or a note it
     could not find on it, falls through to the anchor's own target _top instead of the
     click going nowhere. */
  function scrollTo(note, event) {
    if (!note || !note.dbid) { return false; }
    var scrolled = false;
    try {
      var above = window.top;
      if (!above || above === window) { return false; }
      var target = findNoteInChart(above.document, note);
      if (target) {
        expandNoteIfCollapsed(target);
        target.scrollIntoView({ behavior: "smooth", block: "start" });
        scrolled = true;
      }
      var want = "noteId=" + note.dbid;
      if (above.location.hash.slice(1) === want) {
        above.location.hash = "";
        window.requestAnimationFrame(function () { above.location.hash = want; });
      } else {
        above.location.hash = want;
      }
    } catch (unreachable) {
      // Sandboxed or cross origin. The anchor's own target _top does the ordinary thing.
    }
    // Only swallowed when the scroll above actually moved something, so a page this could
    // not read, or a note it could not find on it, falls through to the anchor instead of
    // the click going nowhere.
    if (scrolled && event) { event.preventDefault(); }
    return scrolled;
  }

  // noteMoment rides along on the same global, since program_panel.html's own note line
  // builds the identical sentence for display and would otherwise need a second copy of
  // the same two formatters just to print what this file already knows how to print.
  window.mfpChartNote = { scrollTo: scrollTo, noteMoment: noteMoment };
})();
