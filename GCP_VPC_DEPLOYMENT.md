# Deploying on a private Google Compute Engine VM

This deployment runs the existing Airflow Compose stack and the companion app
on a Linux Compute Engine VM attached to your VPC. The published ports bind to
`127.0.0.1`, so they are not reachable directly from the internet or from
other VPC hosts. Use IAP, a VPN, or an internal load balancer when access is
needed.

## 1. Create or choose the VM

Use a Linux VM with at least 2 vCPUs, 8 GB RAM, and 30 GB of persistent disk.
Attach it to the intended VPC subnet with no external IP when IAP or a VPN is
available. Grant the VM service account only the permissions it needs; do not
use project-wide editor access.

Install Docker and the Compose plugin using Google's supported Linux package
instructions. Then clone this repository onto the VM:

```bash
git clone <repository-url> psiddhi-claims-platform
cd psiddhi-claims-platform
```

## 2. Allow private administration only

Do not create an ingress rule for ports 8080, 8000, or 8081. The Compose
override binds them to loopback. Permit SSH/IAP or VPN access according to your
organization's policy. If you use IAP, grant the operator
`roles/iap.tunnelResourceAccessor` and allow the IAP TCP forwarding source range
to reach SSH.

Create an SSH tunnel from an authorized workstation:

```bash
gcloud compute ssh <vm-name> --zone <zone> --tunnel-through-iap \
  -- -L 8081:127.0.0.1:8081
```

Open `http://localhost:8081`. Airflow is available through a separate tunnel
when needed:

```bash
gcloud compute ssh <vm-name> --zone <zone> --tunnel-through-iap \
  -- -L 8080:127.0.0.1:8080
```

## 3. Configure secrets

Create a `.env` file on the VM with permissions `600`. Generate the Fernet
key with `openssl rand -base64 32` or Airflow's Fernet-key guidance. Set unique
values for the Airflow username/password and JWT secret. Add the Databricks and
LLM variables required by the pipeline. Never commit this file or put secrets
in the Compose YAML.

At minimum, set:

```dotenv
AIRFLOW_UID=50000
_AIRFLOW_WWW_USER_USERNAME=<strong-admin-username>
_AIRFLOW_WWW_USER_PASSWORD=<strong-admin-password>
FERNET_KEY=<generated-fernet-key>
AIRFLOW__API_AUTH__JWT_SECRET=<random-secret>
CORS_ALLOWED_ORIGINS=
```

`CORS_ALLOWED_ORIGINS` can remain empty because the frontend proxies `/api`
through Nginx. If the backend is called from another private origin, provide a
comma-separated allowlist of exact origins.

## 4. Initialize and start

Validate the merged configuration, initialize Airflow, then start the stack:

```bash
docker compose -f docker-compose.yaml -f docker-compose.prod.yaml config
docker compose -f docker-compose.yaml -f docker-compose.prod.yaml up airflow-init
docker compose -f docker-compose.yaml -f docker-compose.prod.yaml up -d
docker compose -f docker-compose.yaml -f docker-compose.prod.yaml ps
```

The first start builds the Airflow, backend, and frontend images and may take
several minutes. Check logs with:

```bash
docker compose -f docker-compose.yaml -f docker-compose.prod.yaml logs -f airflow-apiserver backend frontend
```

Verify from the VM:

```bash
curl http://127.0.0.1:8081/api/health
curl http://127.0.0.1:8080/api/v2/monitor/health
```

## 5. Persistence and operations

The Compose named volume stores PostgreSQL metadata. The repository bind mount
stores DAGs, logs, DuckDB analytics, model artifacts, and narrative output.
Back up both the named PostgreSQL volume and the project data before upgrades.
Do not run `docker compose down -v` unless you intentionally want to delete
Airflow metadata.

For an update:

```bash
git pull
docker compose -f docker-compose.yaml -f docker-compose.prod.yaml build
docker compose -f docker-compose.yaml -f docker-compose.prod.yaml up -d
```

Monitor disk usage (`docker system df` and `df -h`) and rotate or archive
Airflow logs. For production workloads, move PostgreSQL to Cloud SQL and use
Cloud Storage or another durable store for generated artifacts rather than
relying only on the VM disk.
