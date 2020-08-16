# MrBot - A Discord Bot

Host requirements (Debian):
`texlive dvipng libffi-dev libnacl-dev libopus-dev ffmpeg`

A PostgreSQL server is required.

Running in Docker is the easiest solution, [Dockerfile](https://github.com/cosandr/containers/blob/master/containers/mrbot/bot.Dockerfile)

Most of the CPU heavy tasks are run using its [brains API](https://github.com/cosandr/mrbot-brains).
The bot runs without it, however none of the machine learning commands will work.

## Configuration

All config files go in the `config` directory.
[config.py](config/config.py) is for general bot settings.

Set its listening address in `paths.json` as the `brains` key.

Config is loaded from JSON file(s), missing values will break some functions.

`secrets.json`
```json
{
    "token": "",
    "api-keys": {
        "google": "",
        "oxford": "",
        "wolfram": ""
    },
    "psql": {
        "main": "",
        "public": ""
    },
    "approved_guilds": []
}
```

`paths.json`
```json
{
    "data": "",
    "upload": "",
    "brains": "",
    "hostname": ""
}
```

`guild.json`
```json
{
    "id": 123,
    "name": "guild name",
    "members": {
        "111": {
            "name": "test user 1",
            "self_role": true,
            "roles": []
        }
    },
    "text_channels": {
        "channel-name": {
            "read_only": true,
            "member_names": ["user 1"],
            "member_ids": [111],
            "roles": ["role 1"]
        }
    },
    "roles": {
        "role 1": {
          "view_audit_log": true,
          "change_nickname": true,
          "manage_nicknames": true,
          "read_messages": true
        }
    }
}

```
