# Wasteland-Z — Server Setup

Everything an admin needs to stand up a **Wasteland-Z** dedicated server: the
gateway program, the database schema, example configs, and starter missions —
with a plain-English, step-by-step setup guide for **Windows and Linux**.

## Start here

Open **[`index.html`](index.html)** — the full setup guide (pick Windows or
Linux, follow the numbered steps). It covers:

- **Part 1 — Set it up once:** install MySQL + Python, create the database,
  configure and start the gateway, open the firewall, connect your game server.
- **Part 2 — Run, monitor & restart:** start/stop, check health, read logs,
  auto-start on boot, and back up your data.

## What's in this repo

| Folder / file | What it is |
|---|---|
| `index.html` | The step-by-step setup guide (open it in a browser). |
| `gateway/` | The gateway program — copy this folder to your server and run it. |
| `gateway/setup_database.sql` | Builds every database table in one shot. |
| `gateway/config.example.py` | Settings template — copy to `config.py` and fill in. |
| `gateway/start_gateway.bat` | Windows one-click start. |
| `configs/` | Example server settings (loot, vehicles, towns, admins, loadouts…). |
| `missions/` | A small set of ready-to-run starter missions. |

## Requirements

- Arma Reforger **dedicated server** installed, subscribed to the **Wasteland-Z**
  mod in the Reforger Workshop.
- **Python 3.12+** and **MySQL 8**.

## Show the guide as a web page (optional)

The guide already renders here on GitHub. To publish it at its own public URL:

1. Push this repo to GitHub.
2. Go to the repo's **Settings → Pages**.
3. Under **Build and deployment → Source**, choose **Deploy from a branch**,
   pick your branch and the `/ (root)` folder, and **Save**.
4. After a minute it's live at `https://<your-username>.github.io/HF_WastelandZ_SETUP/`.

---

By **Motavar** · [wasteland-z.com](https://wasteland-z.com)
