#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
repo="$PWD"
image="selenium/standalone-firefox:4.48.0-20260905"
if ! docker container inspect pytonazz-cookie-browser >/dev/null 2>&1; then
  docker run -d --name pytonazz-cookie-browser --restart unless-stopped --shm-size=2g \
    -p 127.0.0.1:17900:7900 \
    -v pytonazz-firefox-profile:/home/seluser/pytonazz-profile "$image"
  docker exec -u root pytonazz-cookie-browser chown seluser:seluser /home/seluser/pytonazz-profile
else
  docker start pytonazz-cookie-browser >/dev/null
fi
mkdir -p "$HOME/.config/systemd/user"
cat > "$HOME/.config/systemd/user/pytonazz-cookie-browser.service" <<EOF
[Unit]
Description=Pytonazz dedicated YouTube cookie renewal
After=network-online.target

[Service]
WorkingDirectory=$repo
ExecStart=$repo/venv/bin/python -u -m monitoring.cookie_browser
Restart=on-failure
RestartSec=15
UMask=0077

[Install]
WantedBy=default.target
EOF
loginctl enable-linger "$(id -un)"
systemctl --user daemon-reload
systemctl --user enable --now pytonazz-cookie-browser.service
echo 'Login: ssh -N -L 17900:127.0.0.1:17900 pytonazz'
echo 'Browser: http://127.0.0.1:17900/vnc.html (password noVNC: secret)'
