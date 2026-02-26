# OpenFSC Client (example/stub) written in Python

## How to run

The project uses Docker Compose and installs its Python dependencies in the `openfsc-client-python` container.

Set required environment variables for authentication:

- `OPENFSC_SITE_ACCESS_KEY`
- `OPENFSC_SITE_SECRET`

Optional:

- `OPENFSC_URL` (defaults to `wss://fsc.sandbox.euca.pacelink.net/ws/text`)

Then run `docker-compose build && docker-compose up`.
