# repomaint
Maintains a local Arch Linux repository mirror.

## Prerequisites
*System packages*

- wget2
- pacserve
- yay
- tar
- openssl-1.1

*Python packages*

*Permissions*

- Group: repomaint (With full access to /mnt/repodata)

*System*

- Direcotry: /mnt/repodata/
- Directory: /mnt/repodata/scripts
- Directory: /mnt/repodata/repos

## Usage

- Put this repo and it's scripts in /mnt/repodata/scripts

- Modify config.json with the appropriate settings you require

- Add repomaint.server and repomaint.timer to /etc/systemd/system, then enable the timer.
    - sudo systemctl start repomaint.timer
    - sudo systemctl enable repomaint.timer

## TODO

- Build AUR packages in a docker container
