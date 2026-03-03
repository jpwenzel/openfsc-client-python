# OpenFSC Python Client with Docker Demo

This repository implements a Python client for the [OpenFSC protocol](https://github.com/pace/openfsc-spec).

It includes a runnable example that can be quickly started with Docker to test and try out the client behavior end-to-end.

The example implementation ships with a simulated POS adapter that acts as a virtual drop-in for a gas station, including simulated user traffic such as transactions and price changes.

## How to run

The project uses Docker Compose and installs its Python dependencies in the `openfsc-client-python` container.

If you prefer Podman, you can use `podman` in place of `docker` for the commands below.

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

## Run on Kubernetes

The repository includes Kubernetes manifests in `k8s/`.

1. Build the image locally:

   ```bash
   docker build -t openfsc-client-python:local .
   ```

2. If your cluster runs in a separate container runtime (for example `kind`), load the image into the cluster:

   ```bash
   kind load docker-image openfsc-client-python:local
   ```

3. Create/update the Kubernetes secret from your root `.env` file:

    ```bash
    kubectl create secret generic openfsc-client-secret \
       --from-env-file=.env \
       --dry-run=client -o yaml | kubectl apply -f -
    ```

    This pulls variables from `.env` into `openfsc-client-secret`.

4. Deploy:

   ```bash
   kubectl apply -k k8s
   ```

5. Check pod status:

   ```bash
   kubectl get pods -l app=openfsc-client
   ```

6. Tail logs:

   ```bash
   kubectl logs -f deployment/openfsc-client
   ```

7. Remove the demo:

   ```bash
   kubectl delete -k k8s
   ```

8. (Optional) Remove the secret:

   ```bash
   kubectl delete secret openfsc-client-secret
   ```

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
