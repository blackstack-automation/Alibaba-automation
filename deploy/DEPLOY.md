# Deploying to a fresh Ubuntu 24.04 VPS

Everything below assumes a brand-new server. Total time: about 15 minutes.

What you end up with: gunicorn (web) + Celery worker + Celery beat, each a
systemd service that restarts itself, Redis on localhost,
and the app reachable either through an SSH tunnel or nginx + HTTPS.

## 1. First login (as root, once)

Create a normal user, give it your SSH key, and lock down the firewall.
Allow SSH **before** enabling the firewall or you will lock yourself out.

```bash
adduser deploy
usermod -aG sudo deploy
rsync --archive --chown=deploy:deploy ~/.ssh /home/deploy
ufw allow OpenSSH
ufw allow 80,443/tcp
ufw enable
```

Open a second terminal and confirm `ssh deploy@<vps-ip>` works before closing
the root session.

## 2. Get the code (as `deploy`)

```bash
sudo apt-get update && sudo apt-get install -y git
git clone https://github.com/blackstack-automation/Alibaba-automation.git ~/mail-dashboard
cd ~/mail-dashboard
```

If the repo is private, HTTPS will ask for credentials. Use a GitHub personal
access token as the password, or add a deploy key:

```bash
ssh-keygen -t ed25519 -C "vps" -f ~/.ssh/id_ed25519 -N ""
cat ~/.ssh/id_ed25519.pub     # GitHub repo -> Settings -> Deploy keys -> Add (read-only is fine)
git clone git@github.com:blackstack-automation/Alibaba-automation.git ~/mail-dashboard
```

## 3. Run the setup script

```bash
bash deploy/setup.sh
```

It installs Redis/nginx/Python deps, generates fresh `SECRET_KEY` and
`ENCRYPTION_KEY`, migrates the database, optionally creates your admin login,
and installs and starts the three services.

**It prints the `ENCRYPTION_KEY` once. Copy it into a password manager
immediately.** It encrypts every stored Alibaba AccessKey secret and is
Without it those secrets are gone.

Check the services any time with:

```bash
systemctl status mail-dashboard-web mail-dashboard-worker mail-dashboard-beat
journalctl -u mail-dashboard-worker -f      # live send logs
```

## 4. Reach the app

### Option A: SSH tunnel (best for testing, nothing exposed publicly)

On your own PC:

```bash
ssh -L 8000:127.0.0.1:8000 deploy@<vps-ip>
```

Then open http://localhost:8000.

### Option B: a domain with HTTPS (real use)

This app stores Alibaba keys, so do not serve it over plain HTTP.

1. Point an `A` record for your domain at the VPS IP.
2. Install and enable the nginx config:

```bash
sudo cp deploy/nginx/mail-dashboard.conf /etc/nginx/sites-available/mail-dashboard
sudo sed -i 's/YOUR_DOMAIN/dashboard.example.com/' /etc/nginx/sites-available/mail-dashboard
sudo ln -s /etc/nginx/sites-available/mail-dashboard /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

3. Get a certificate (also sets up the HTTP to HTTPS redirect):

```bash
sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot --nginx -d dashboard.example.com
```

## 5. Updating the app later

```bash
cd ~/mail-dashboard && bash deploy/update.sh
```

Pulls from GitHub, installs new dependencies, runs migrations, restarts the
three services.

## 6. Before the first real send

The send pipeline has never run against real Alibaba. Per the development plan:

1. Add one real account and a sender with a **low** baseline quota (50 to 100).
2. Click "Test Connection" on the account.
3. Upload a list of 10 to 20 addresses **you control**, create a job, watch it.
4. Only then scale up.

Also: the first admin password should be a real one, and if you ever used
`temp-dev-password-change-me`, it must not exist on this server.

## Troubleshooting

| Symptom | Check |
|---|---|
| Job stays `pending` after Send Now | `systemctl status redis-server mail-dashboard-worker` |
| Job stuck on `sending` | `journalctl -u mail-dashboard-worker -n 100`; see SETUP.md runbook |
| Live counters never update behind nginx | the `/jobs/<id>/status` block in the nginx config (`proxy_buffering off`) |
| 502 from nginx | `systemctl status mail-dashboard-web`, `journalctl -u mail-dashboard-web -n 50` |
| `instance/logs/worker.log` looks incomplete | Celery takes over logging; `journalctl -u mail-dashboard-worker` is authoritative |
