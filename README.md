# repomaint
Maintain a local Arch Linux repository

## Prerequisites
*System packages*

- wget2
- pacserve
- yay
- tar

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

- Add rsync method - https://gitlab.archlinux.org/archlinux/infrastructure/-/blob/master/roles/syncrepo/files/syncrepo-template.sh
    -   rsync url found - https://archlinux.org/mirrors/
