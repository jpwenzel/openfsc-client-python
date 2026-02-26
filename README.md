# OpenFSC Client (example/stub) written in Python

## How to run

The project uses Docker Compose and installs its Python dependencies in the `openfsc-client-python` container.

### Configuration

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` and set your credentials:
   - `OPENFSC_SITE_ACCESS_KEY` - Your site access key (UUID)
   - `OPENFSC_SITE_SECRET` - Your site secret
   - `OPENFSC_URL` (optional) - Server URL (defaults to sandbox)

3. Start the container:
   ```bash
   docker compose up -d --build
   ```

4. View logs:
   ```bash
   docker compose logs -f openfsc-client-python
   ```

5. Stop the container:
   ```bash
   docker compose down
   ```

### Unauthenticated Mode

If credentials are not set in `.env`, the client stays connected in unauthenticated mode and only responds to `HEARTBEAT` requests.
