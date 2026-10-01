# Consent Capture — Guides

Helpful materials for the people who set up and use the Consent Capture plugin. Each guide is
available as **Markdown** (read on screen / GitHub) and as a **PDF** (print or share).

## Start here

| Guide | Who it's for | What it covers |
|-------|--------------|----------------|
| **[Setup & Configuration](SETUP_GUIDE.md)** ([PDF](SETUP_GUIDE.pdf)) | Administrator | Installing the plugin, credentials and plugin variables, creating consent types, configuring each consent, and turning on banners. |
| **[Recording Consents — Staff Guide](RECORDING_GUIDE.md)** ([PDF](RECORDING_GUIDE.pdf)) | Front-desk & clinical staff | The full walkthrough of the consent window: recording a consent, signed-paper (Written) consents, viewing and renewing consents. |
| **[Consents — Quick Start](RECORDING_QUICKSTART.md)** ([PDF](RECORDING_QUICKSTART.pdf)) | Front-desk & clinical staff | A 2-page cheat sheet. Print it and keep it at the desk. |
| **[Record Patient Consent — Step-by-Step Guide](Record%20Patient%20Consent%20Step-by-Step%20Guide.pdf)** (PDF) | Front-desk & clinical staff | A click-by-click visual walkthrough of recording a consent. |

## Which one do I need?

- **Setting the plugin up for your practice?** → Setup & Configuration.
- **Recording consents day to day?** → Quick Start (or the full Staff Guide for detail).

## Notes

- `screenshots/` holds the images used by the guides. The consent-window images use sample
  data for illustration; the chart and admin-page images are from a live test instance.
- The PDFs are generated from the Markdown with `tools/screenshots/render_pdf.mjs`. After
  editing a guide, regenerate them with `node tools/screenshots/render_pdf.mjs`.
- For a technical/developer reference, see the plugin's **[README.md](../consent_capture/README.md)**.
