# Game server kit

Everything to install and run the Arma Reforger dedicated server for
Wasteland-Z on Windows — full walkthrough in the main guide
([`index.html`](../index.html), "Install the game server" + "Run" sections).

| File | What it is |
|---|---|
| `install_or_update_server.bat` | Installs the Reforger server via SteamCMD. Re-run after every official game update. |
| `server1.json.example` | The game server's config — copy to `C:\reforger\configs\server1.json` and set your server name + admin password. Wasteland-Z is already in the `mods` list. |
| `start_server1.bat` | Starts server 1 in its own labeled window with an auto-restart loop (crash = back up in 10 s). Close the window (or run the stop script) to stop it for good. |
| `stop_server1.bat` | Stops server 1 and its restart loop. Gateway and other servers keep running. |
| `start_all.bat` | One double-click starts the gateway plus every enabled game server, each in its own window. Put a shortcut in `shell:startup` to launch on boot. |

**Running 2–3 servers on one machine:** copy the `server1` files to
`server2`/`server3`, change the ports and paths inside (there's a table in
the main guide), add the matching entry in the gateway's `config.py`
`SERVERS` list, and un-comment the extra `start` lines in `start_all.bat`.
All servers share one database — same money and gear everywhere.
