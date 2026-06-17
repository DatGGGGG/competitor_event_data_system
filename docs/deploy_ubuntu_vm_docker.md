# Ubuntu VM Deployment with Docker Compose

This guide is the recommended deployment path for a **shared Ubuntu VM**.

It isolates the event API from other projects on the same machine by running:

- one `api` container
- one `ngrok` container
- one reusable `job` container profile for ad hoc or scheduled ETL work

The SQLite database stays on the VM host and is mounted into the containers from the VM filesystem.
Replayable Sensor Tower raw snapshots also stay on the VM host.

Note:
- the current API startup path still runs schema initialization / lightweight migrations
- so the container needs write access to the mounted SQLite database
- do not mount the DB directory read-only unless the API startup flow is changed later

## Deployment Assets

- [Dockerfile](/C:/Users/VEE0634/Desktop/Coding/vn_competitor_event_data_system/Dockerfile)
- [docker-compose.yml](/C:/Users/VEE0634/Desktop/Coding/vn_competitor_event_data_system/deploy/docker/docker-compose.yml)
- [vm.env.example](/C:/Users/VEE0634/Desktop/Coding/vn_competitor_event_data_system/deploy/docker/vm.env.example)
- [pipeline.env.example](/C:/Users/VEE0634/Desktop/Coding/vn_competitor_event_data_system/deploy/docker/pipeline.env.example)
- [run_vm_pipeline.sh](/C:/Users/VEE0634/Desktop/Coding/vn_competitor_event_data_system/deploy/docker/run_vm_pipeline.sh)
- [vn-event-dw-pipeline.service.example](/C:/Users/VEE0634/Desktop/Coding/vn_competitor_event_data_system/deploy/docker/vn-event-dw-pipeline.service.example)
- [vn-event-dw-pipeline.timer.example](/C:/Users/VEE0634/Desktop/Coding/vn_competitor_event_data_system/deploy/docker/vn-event-dw-pipeline.timer.example)

## Recommended VM Layout

- repo: `/opt/vn_event_dw/vn_competitor_event_data_system`
- host DB directory: `/opt/vn_event_dw/data`
- DB file: `/opt/vn_event_dw/data/warehouse.db`
- raw ingest directory: `/opt/vn_event_dw/data_ingest`
- mounted secrets directory: `/opt/vn_event_dw/secrets`
- compose env file: `/opt/vn_event_dw/vn_competitor_event_data_system/deploy/docker/vm.env`
- pipeline env file: `/opt/vn_event_dw/vn_competitor_event_data_system/deploy/docker/pipeline.env`

## 1. Install Docker and Compose

```bash
sudo apt update
sudo apt install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo \"$VERSION_CODENAME\") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

Optional: allow your SSH user to run Docker without `sudo`:

```bash
sudo usermod -aG docker "$USER"
newgrp docker
```

## 2. Clone the Repo

```bash
sudo mkdir -p /opt/vn_event_dw
sudo chown -R "$USER":"$USER" /opt/vn_event_dw
cd /opt/vn_event_dw
git clone https://github.com/DatGGGGG/vn_competitor_event_data_system.git
```

## 3. Prepare the Host Database Directory

```bash
mkdir -p /opt/vn_event_dw/data
mkdir -p /opt/vn_event_dw/data_ingest
mkdir -p /opt/vn_event_dw/secrets
```

Copy the database from your local machine to the VM host:

```bash
scp /path/to/warehouse.db <vm-user>@<vm-host>:/tmp/warehouse.db
```

Then on the VM:

```bash
mv /tmp/warehouse.db /opt/vn_event_dw/data/warehouse.db
chmod 644 /opt/vn_event_dw/data/warehouse.db
```

Copy the Socialdata Google service-account JSON to the VM host if you want unattended Socialdata sync:

```bash
scp /path/to/socialdata-service-account.json <vm-user>@<vm-host>:/tmp/socialdata-service-account.json
mv /tmp/socialdata-service-account.json /opt/vn_event_dw/secrets/socialdata-service-account.json
chmod 600 /opt/vn_event_dw/secrets/socialdata-service-account.json
```

## 4. Create the Compose Env File

```bash
cd /opt/vn_event_dw/vn_competitor_event_data_system
cp deploy/docker/vm.env.example deploy/docker/vm.env
nano deploy/docker/vm.env
```

Fill in at least:

```bash
HOST_DATA_DIR=/opt/vn_event_dw/data
HOST_INGEST_DIR=/opt/vn_event_dw/data_ingest
HOST_SECRETS_DIR=/opt/vn_event_dw/secrets
NGROK_AUTHTOKEN=your_real_ngrok_token_here
NGROK_DOMAIN=april-refund-promoter.ngrok-free.dev
API_PORT=8765
NGROK_INSPECT_PORT=4040
```

Notes:

- `NGROK_DOMAIN` should be your reserved public HTTPS URL host, for example `april-refund-promoter.ngrok-free.dev`
- `NGROK_AUTHTOKEN` must be the real token from your ngrok dashboard, not a placeholder

## 5. Create the Runtime Pipeline Env File

```bash
cd /opt/vn_event_dw/vn_competitor_event_data_system
cp deploy/docker/pipeline.env.example deploy/docker/pipeline.env
nano deploy/docker/pipeline.env
```

Fill in:

```bash
SENSOR_TOWER_AUTH_TOKEN=your_real_token
SOCIALDATA_APP_SLUG=srcvn
SOCIALDATA_GOOGLE_SERVICE_ACCOUNT_FILE=/app/secrets/socialdata-service-account.json
SOCIALDATA_GOOGLE_SCOPES=https://www.googleapis.com/auth/userinfo.email
OPENAI_API_KEY=your_real_key
OPENAI_BASE_URL=https://compass.llm.shopee.io/compass-api/v1
OPENAI_PROVIDER=OpenAI
OPENAI_MODEL=gpt-5.4-nano
OPENAI_UNIFIED_EVENT_MERGE_MODEL=gpt-5.4
SOCIALDATA_SYNC_LOOKBACK_DAYS=10
SENSORTOWER_SYNC_LOOKBACK_DAYS=3
```

Notes:

- `SOCIALDATA_GOOGLE_SERVICE_ACCOUNT_FILE` is the best unattended auth path for weekly VM runs.
- `SOCIALDATA_GOOGLE_SCOPES` should include `https://www.googleapis.com/auth/userinfo.email` so Socialdata can identify the granted service-account email.
- `SOCIALDATA_USESSION` and `SOCIALDATA_GOOGLE_ACCESS_TOKEN` are optional manual fallbacks, but both expire.
- `PIPELINE_UNIFIED_MONTHS` can stay blank. The VM pipeline script will then rebuild the previous month and current month automatically.

## 6. Start the Stack

From the repo root on the VM:

```bash
cd /opt/vn_event_dw/vn_competitor_event_data_system
docker compose --env-file deploy/docker/vm.env -f deploy/docker/docker-compose.yml up -d --build
```

If your VM user is not in the Docker group, use `sudo docker compose ...` instead.

## 7. Check Container Health

```bash
docker compose --env-file deploy/docker/vm.env -f deploy/docker/docker-compose.yml ps
docker compose --env-file deploy/docker/vm.env -f deploy/docker/docker-compose.yml logs -f api ngrok
```

You want to see:

- API bound on `0.0.0.0:8765` inside the container
- ngrok connected successfully
- your reserved public URL attached

## 8. Smoke Test

On the VM host:

```bash
curl "http://127.0.0.1:8765/api/games?q=MLBB"
curl "https://april-refund-promoter.ngrok-free.dev/api/games?q=MLBB"
```

## 9. Run the Data Pipeline Manually

The repo includes a VM-side wrapper script that runs:

- `sync-socialdata-posts`
- `sync-sensortower-raw`
- `load-sensortower-raw`
- `build-unified-events-llm` for the previous month and current month
- `docker compose restart api`

Run it:

```bash
cd /opt/vn_event_dw/vn_competitor_event_data_system
chmod +x deploy/docker/run_vm_pipeline.sh
./deploy/docker/run_vm_pipeline.sh
```

If you want to force specific months:

```bash
cd /opt/vn_event_dw/vn_competitor_event_data_system
PIPELINE_UNIFIED_MONTHS=2026-06,2026-07 ./deploy/docker/run_vm_pipeline.sh
```

## 10. Install the Weekly Timer

Copy the example unit files and replace `__VM_USER__` with your real VM username:

```bash
cd /opt/vn_event_dw/vn_competitor_event_data_system
sed "s/__VM_USER__/garenavn/g" deploy/docker/vn-event-dw-pipeline.service.example | sudo tee /etc/systemd/system/vn-event-dw-pipeline.service > /dev/null
sudo cp deploy/docker/vn-event-dw-pipeline.timer.example /etc/systemd/system/vn-event-dw-pipeline.timer
sudo systemctl daemon-reload
sudo systemctl enable --now vn-event-dw-pipeline.timer
```

Check the timer:

```bash
systemctl status vn-event-dw-pipeline.timer
systemctl list-timers --all | grep vn-event-dw-pipeline
```

Run the service once on demand:

```bash
sudo systemctl start vn-event-dw-pipeline.service
sudo journalctl -u vn-event-dw-pipeline.service -n 200 --no-pager
```

## Update Flow

### Push latest code to the VM

After pushing new code to GitHub:

```bash
cd /opt/vn_event_dw/vn_competitor_event_data_system
git pull
docker compose --env-file deploy/docker/vm.env -f deploy/docker/docker-compose.yml up -d --build
```

If your VM uses `sudo` for Docker, prefix the compose commands accordingly.

Because `deploy/docker/vm.env` and `deploy/docker/pipeline.env` are untracked local files, `git pull` should not overwrite them.

If the Docker image or deployment files changed, rebuild after pulling:

```bash
cd /opt/vn_event_dw/vn_competitor_event_data_system
docker compose --env-file deploy/docker/vm.env -f deploy/docker/docker-compose.yml up -d --build
```

### Overwrite the VM database with the latest local DB

Copy a new `warehouse.db` onto the VM host, replacing the old file:

```bash
scp /path/to/warehouse.db <vm-user>@<vm-host>:/tmp/warehouse.db
```

Then on the VM:

```bash
mv /tmp/warehouse.db /opt/vn_event_dw/data/warehouse.db
chmod 664 /opt/vn_event_dw/data/warehouse.db
cd /opt/vn_event_dw/vn_competitor_event_data_system
docker compose --env-file deploy/docker/vm.env -f deploy/docker/docker-compose.yml restart api
```

If you want the VM to pick up the new DB and immediately rebuild the latest monthly unified tables on top of it, run:

```bash
cd /opt/vn_event_dw/vn_competitor_event_data_system
./deploy/docker/run_vm_pipeline.sh
```

## Stop / Restart

Stop:

```bash
cd /opt/vn_event_dw/vn_competitor_event_data_system
docker compose --env-file deploy/docker/vm.env -f deploy/docker/docker-compose.yml down
```

Restart:

```bash
cd /opt/vn_event_dw/vn_competitor_event_data_system
docker compose --env-file deploy/docker/vm.env -f deploy/docker/docker-compose.yml up -d
```

## Why This Setup Is Better on a Shared VM

- container-level dependency isolation
- no shared Python virtualenv conflicts
- cleaner restarts and upgrades
- DB remains host-managed and easy to refresh with `scp` or `rsync`
- raw Sensor Tower snapshots remain host-managed and survive container rebuilds
- ngrok is isolated from the application runtime
- the ETL job uses the same image and env as the API, so production behavior is easier to reason about
