# MrBot - A Discord Bot

Host requirements (Debian):
`texlive dvipng libffi-dev libnacl-dev libopus-dev ffmpeg`

A PostgreSQL server is required.

Running in Docker is the easiest solution, [Dockerfile](https://github.com/cosandr/containers/blob/master/mrbot/bot.Dockerfile)

Most of the CPU heavy tasks are run using its [brains API](https://github.com/cosandr/mrbot-brains).
The bot runs without it, however none of the machine learning commands will work.

Set its listening address in as the `brains` key in one of the paths config types.

Check `launcher.py -h` for launch options.

## Configuration

[constants.py](config/constants.py) is for general bot settings.

Config can be loaded from JSON files or a PSQL table.
Launch with `json-config` or `psql-config` respectively.

The data itself is the same between the two, see below for examples.

The load order is important, loading multiple files of the same type overrides previous data.

This is useful for running different instances with slightly different data, as they can share certain settings
and not others (for example different tokens with otherwise identical configs).

### PSQL config

Must specify PostgreSQL connection string:
 - Directly using `-c/--dsn`
 - Read from the environment variable `CONFIG_DSN` using `--env`
 - Read from file using `-f/--file`

All guild definitions and configs named "main" are loaded first.

Extra names may be specified by using `-e <name>` for example `-e test` will load
the row with name `test`.

Examples:
 - `./launcher.py psql-config -c 'postgres://user:password@localhost/db'`
 - `CONFIG_DSN='postgres://user:password@localhost/db' ./launcher.py psql-config --env`
 - `./launcher.py psql-config -f config/.dsn`


### JSON config

Must specify JSON files to load, at least one for secrets, paths and guilds.

Example `./launcher.py json-config -c config/config.json -g config/guild.json`

### Example configs
`config`
```json
{
    "token": "",
    "psql": {
        "main": "postgres://user:pass@/discord",
        "public": "postgres://user:pass@/public",
        "web": "postgres://user:pass@/web"
    },
    "api-keys": {
        "google": "",
        "wolfram": ""
    },
    "approved_guilds": [],
    "brains": "http://localhost:7762",
    "hostname": "https://www.example.com",
    "paths": {
        "data": "/data",
        "upload": "/var/www/discord"
    },
    "channels": {
        "exceptions": 444276260164665321,
        "default_voice": 453141750106882032,
        "test": 453141750106882033
    }
}

```

`guild`
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
