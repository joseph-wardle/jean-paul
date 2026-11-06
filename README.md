# Jean Paul

![Picture of Jean Paul](assets/jean-paul.jpg)

Hi! I’m Jean Paul Publish III, country gentleman and sole heir to a modest estate of some fourteen thousand acres.

I enjoy long walks through the countryside, a proper marmalade, and immutable versioned publishes. My family has lived in the same house for nine generations, despite having the means to leave.

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
