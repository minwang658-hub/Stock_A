# Remote Deploy Notes

## Overview

Recommended public deployment topology:

1. Deploy the FastAPI backend to your Aliyun Linux server
2. Put Nginx in front of the backend
3. Expose only the domain, not the raw port
4. Configure the HTML page to request your public API domain

Template files already prepared in this repo:

- `deploy/linux/start_api.sh`
- `deploy/linux/mimi-stock-api.service`
- `deploy/linux/nginx-mimi-stock-api.conf`

## 1. Server preparation

Example target path:

```bash
sudo mkdir -p /opt/mimi_stock_zoe1
sudo chown -R $USER:$USER /opt/mimi_stock_zoe1
```

Upload the project to the server, then:

```bash
cd /opt/mimi_stock_zoe1
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2. Start locally on the server first

Quick smoke test before systemd:

```bash
cd /opt/mimi_stock_zoe1
source .venv/bin/activate
export MIMI_API_HOST=127.0.0.1
export MIMI_API_PORT=8765
export MIMI_ALLOWED_ORIGIN=https://your-frontend.example.com
export MIMI_API_KEY=change-me
python3 scripts/local_stock_api.py
```

Check:

```bash
curl "http://127.0.0.1:8765/api/health?key=change-me"
```

## 3. Configure systemd

Edit these values in `deploy/linux/mimi-stock-api.service` before installing:

- `WorkingDirectory=/opt/mimi_stock_zoe1`
- `MIMI_ALLOWED_ORIGIN=https://your-frontend.example.com`
- `MIMI_API_KEY=change-me`

If you use a venv, edit `deploy/linux/start_api.sh` or set:

```bash
export PYTHON_BIN=/opt/mimi_stock_zoe1/.venv/bin/python
```

Install and enable:

```bash
sudo cp deploy/linux/mimi-stock-api.service /etc/systemd/system/mimi-stock-api.service
sudo systemctl daemon-reload
sudo systemctl enable mimi-stock-api
sudo systemctl start mimi-stock-api
sudo systemctl status mimi-stock-api --no-pager
```

Logs:

```bash
sudo journalctl -u mimi-stock-api -f
```

## 4. Configure Nginx

Edit `deploy/linux/nginx-mimi-stock-api.conf`:

- `server_name api.example.com` -> your real domain

Install config:

```bash
sudo cp deploy/linux/nginx-mimi-stock-api.conf /etc/nginx/conf.d/mimi-stock-api.conf
sudo nginx -t
sudo systemctl reload nginx
```

Now test externally:

```bash
curl "http://api.example.com/api/health?key=change-me"
```

## 5. Aliyun security settings

Make sure these are open:

1. Aliyun Security Group: open `80` and `443`
2. Linux firewall if enabled: allow `80` and `443`

If you expose the raw backend port directly for debugging, also open `8765`, but production is better through Nginx only.

## 6. HTTPS

Strongly recommended for public access.

If you use Certbot with Nginx:

```bash
sudo certbot --nginx -d api.example.com
```

Then your API becomes:

```text
https://api.example.com/api/stock
```

## 7. Frontend usage

Open the HTML page and fill in:

- API地址: `https://api.example.com/api/stock`
- API密钥: same value as `MIMI_API_KEY` if enabled

The page saves these settings to browser localStorage.

You can also pass them by URL:

```text
file:///.../合肥城建-可视化分析-2026-05-15.html?api=https%3A%2F%2Fapi.example.com%2Fapi%2Fstock&key=change-me
```

## 8. Recommended production rules

- Keep the Tushare token only on the server side
- Restrict `MIMI_ALLOWED_ORIGIN` to your real frontend domain
- Use a non-empty `MIMI_API_KEY`
- Put the backend behind Nginx and HTTPS
- Do not expose `8765` to the public unless you are debugging
