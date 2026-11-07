# Jean Paul

![Picture of Jean Paul](assets/jean-paul.jpg)

Hi! I’m Jean Paul Publish III, country gentleman and sole heir to a modest estate of some fourteen thousand acres.

I enjoy long walks through the countryside, a proper marmalade, and immutable versioned publishes. My family has lived in the same house for nine generations, despite having the means to leave.

Posts in one Discord forum become issues labelled `discord` in a GitHub repository, and their replies become comments. Closing or reopening an issue changes the post's Open or Closed tag.

## Setup, once

- **Discord.** Create an application with a bot and turn on its Message Content intent. Invite it to the server. In the forum, it needs View Channel, Read Message History, Send Messages, Send Messages in Threads and Manage Threads. In a private maintainer channel, it needs View Channel and Send Messages. Give the forum the tags **Open** and **Closed**, each with "Only allow moderators to apply this tag".
- **GitHub.** Create a GitHub App with Issues read and write. Install it on the repository, generate a private key, and create the label `discord`.
- **Settings.** Copy `config.example.toml` to `~/.config/jean-paul/config.toml` and fill it in. Put the bot token in `discord_token` and the key in `github_app.pem` beside it. Make all three mode 600.

If anything is missing, the bot refuses to start and its log says what.

## Install

```sh
git clone https://github.com/joseph-wardle/jean-paul.git ~/jean-paul
cd ~/jean-paul
uv sync --frozen --no-dev
mkdir -p ~/.config/systemd/user
ln -s ~/jean-paul/jean-paul.service ~/.config/systemd/user/
sudo loginctl enable-linger "$USER"     # start at boot, not at login
systemctl --user daemon-reload
systemctl --user enable --now jean-paul
```

## Running

```sh
journalctl --user -u jean-paul -f        # log
systemctl --user restart jean-paul
cd ~/jean-paul && git pull && uv sync --frozen --no-dev && systemctl --user restart jean-paul   # update
```

Warnings and errors the bot survives also go to the maintainer channel. The nightly watchdog workflow fails, and GitHub emails you, if any post is still untagged after 30 minutes. It needs the bot token as the repository secret `DISCORD_TOKEN` and the forum id in the workflow file.

- **Run exactly one copy.** Two would each file every new post. To move hosts, run `systemctl --user disable --now jean-paul` on the old one first, then copy `~/.config/jean-paul/` across.
- **Keep the hidden `<!-- discord-thread: … -->` line** when editing an issue the bot wrote. Without it, the issue can't find its post, and the bot warns until the line is restored from the issue's edit history.
