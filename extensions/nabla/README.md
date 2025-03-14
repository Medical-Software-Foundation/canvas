Nabla Ambient AI Assistant
=====

## Description

[Nabla](https://www.nabla.com/)

## Configuration

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
