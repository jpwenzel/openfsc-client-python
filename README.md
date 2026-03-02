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
   - `POS_ADAPTER_CLASS` (optional) - Adapter plugin class (`module_name.ClassName`)

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

## Run tests

Run unit tests locally:

```bash
python3 -m unittest discover -s tests -v
```

## POS Adapter extensibility

The client is designed to accept any implementation of `PosAdapter`.

- Built-in reference implementation: `ExamplePosAdapter` in `openfsc-client/example_pos_adapter.py`
- Runtime plugin selection: set `POS_ADAPTER_CLASS` to `module_name.ClassName`

You can provide your own adapter by implementing the `PosAdapter` interface in `openfsc-client/pos_adapter.py` and wiring it into `openfsc-client/main.py`.

Example:

```bash
export POS_ADAPTER_CLASS=example_pos_adapter.ExamplePosAdapter
```

Custom adapter example:

```bash
export POS_ADAPTER_CLASS=my_company.adapters.StorePosAdapter
```

Or in `.env`:

```dotenv
POS_ADAPTER_CLASS=my_company.adapters.StorePosAdapter
```
