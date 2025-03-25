![Canvas Nabla Integration](https://images.prismic.io/canvas-website/Z-K-2HdAxsiBv4Qs_Nabla_logo_200px.png?auto=format,compress)

# Nabla Ambient AI Assistant


## Description

Ambient AI can save physicians countless hours of administrative work and documentation by transcribing conversations and converting them into clinical notes.

With the Canvas-Nabla integration, users can:
- Access Nabla directly from the patient chart in the EMR
- Initiate a recording session
- Receive AI-generated clinical notes from the encounter
- Copy notes from to clipboard


## Configuration

Requirements:
- Nabla user account
- Access to Nabla Core API

After installing, go to the plugin setting page and provide values for:

- `NABLA_OAUTH_CLIENT_ID`
- `JWK_PRIVATE_KEY`
- `JWK_PUBLIC_KEY`

To get these values, 

1. Generate the private key

```bash
openssl genpkey -algorithm RSA -out private_key.pem
```

2. Extract the public key from the private one

```bash
openssl rsa -pubout -in private_key.pem -out public_key.pem
```

3. Register a new OAuth Client Nabla Core API using the public key from above.
   After registering, you will be provided with the client id.

For more information see:
[https://docs.nabla.com/guides/authentication](https://docs.nabla.com/guides/authentication)

## About Nabla
Nabla is the leading ambient AI assistant, reducing practitioner stress and improving patient care. Nabla produces AI-generated clinical notes in seconds from any encounter across all specialties. Powered by proprietary LLMs, fine-tuned to the medical field, Nabla's capabilities include AI-enabled medical coding identification and smooth EHR integrations.

[Nabla](https://www.nabla.com/)
