# Game server kit

Everything to install and run the Arma Reforger dedicated server for
Wasteland-Z on Windows or Linux — full walkthrough in the main guide
([`index.html`](../index.html), "Install the game server" + "Run" sections).

| File | What it is |
|---|---|
| `install_or_update_server.bat` | Windows: installs the Reforger server via SteamCMD. Re-run after every official game update. |
| `server1.json.example` | The game server's config — copy to your configs folder as `server1.json` and set your server name + admin password. Wasteland-Z is already in the `mods` list. |
| `server2.json.example` | Ready-made second-server config for the multi-server "hive": ports 2002/17778 and the Arland map already set. Copy, rename the server, done. |
| `start_server1.bat` | Windows: starts server 1 in its own labeled window with an auto-restart loop (crash = back up in 10 s). Close the window (or run the stop script) to stop it for good. |
| `stop_server1.bat` | Windows: stops server 1 and its restart loop. Gateway and other servers keep running. |
| `start_all.bat` | Windows: one double-click starts the gateway plus every enabled game server, each in its own window. Put a shortcut in `shell:startup` to launch on boot. |
| `wz-gateway.service.example` | Linux: ready-made systemd service for the gateway — copy to `/etc/systemd/system/`, set your username, enable. |
| `wz-server1.service.example` | Linux: systemd service for game server 1 (auto-start on boot, auto-restart on crash). |
| `wz-server2.service.example` | Linux: systemd service for game server 2 — pairs with `server2.json.example`. |

**Running 2–3 servers on one machine:** copy the `server1` files to
`server2`/`server3` (the kit ships ready-made `server2` examples), change the
ports and paths inside (there's a table in the main guide), add the matching
entry in the gateway's `config.py` `SERVERS` list, and start it — Windows:
un-comment the extra `start` lines in `start_all.bat`; Linux: enable the
extra systemd unit. All servers share one database — same money and gear
everywhere.
