import pytest
import pytest_mock

from config.types import *


def test_guild_json():
    expected_roles = {
        "role 1": RoleDef(
            name="role 1",
            view_audit_log=True,
            change_nickname=True,
            manage_nicknames=True,
            read_messages=True,
        ),
    }
    expected_members = {
        111: MemberDef(
            id_=111,
            name="test user 1",
            self_role=True,
            roles=[],
        ),
        222: MemberDef(
            id_=222,
            name="test user 2",
            self_role=False,
            roles=["role 1"],
        ),
    }
    expected_text_channels = {
        "channel-one": TextChannelDef(
            name="channel-one",
            roles=[],
            member_names=[],
            member_ids=[],
            read_only=False,
        ),
        "channel-two": TextChannelDef(
            name="channel-two",
            roles=["@everyone"],
            member_names=[],
            member_ids=[],
            read_only=False,
        ),
        "channel-three": TextChannelDef(
            name="channel-three",
            roles=["role 1"],
            member_names=[],
            member_ids=[],
            read_only=False,
        ),
        "channel-four": TextChannelDef(
            name="channel-four",
            roles=["role 1"],
            member_names=["test user 1"],
            member_ids=[222],
            read_only=True,
        ),
    }
    expected_guild = GuildDef(
        id_=123,
        name="test guild",
        members=expected_members,
        roles=expected_roles,
        text_channels=expected_text_channels,
    )
    with open("test_config_guild.json", "r") as f:
        data = json.load(f)
    actual_guild = GuildDef.from_dict(data)
    # Check roles
    assert len(actual_guild.roles) == len(expected_roles)
    for name, exp in expected_roles.items():
        assert name in actual_guild.roles
        actual = actual_guild.roles[name]
        assert actual.name == exp.name
        assert actual.permission_overwrite == exp.permission_overwrite
    # Make sure __eq__ works
    assert actual_guild.roles == expected_guild.roles
    # Check members
    assert len(actual_guild.members) == len(expected_members)
    for id_, exp in expected_members.items():
        assert id_ in actual_guild.members
        actual = actual_guild.members[id_]
        assert actual.id == exp.id
        assert actual.name == exp.name
        assert actual.self_role == exp.self_role
        assert actual.roles == exp.roles
    # Make sure __eq__ works
    assert actual_guild.members == expected_guild.members
    # Check text channels
    assert len(actual_guild.text_channels) == len(expected_text_channels)
    for name, exp in expected_text_channels.items():
        assert name in actual_guild.text_channels
        actual = actual_guild.text_channels[name]
        assert actual.name == exp.name
        assert actual.roles == exp.roles
        assert actual.read_only == exp.read_only
        assert actual.member_names == exp.member_names
        assert actual.member_ids == exp.member_ids
    # Make sure __eq__ works
    assert actual_guild.text_channels == expected_guild.text_channels
    # Make sure __eq__ works
    assert actual_guild == expected_guild


def test_dump_role():
    role = RoleDef(
        name="role 1",
        view_audit_log=True,
        change_nickname=True,
        manage_nicknames=True,
        read_messages=True,
    )
    expected = {
        "role 1": dict(
            view_audit_log=True,
            change_nickname=True,
            manage_nicknames=True,
            read_messages=True,
        )
    }
    actual = role.to_dict()
    assert actual == expected


@pytest.mark.asyncio
async def test_from_psql(mocker: pytest_mock.MockFixture):
    mock_pg_data = [
        {
            "name": "main",
            "type": "config",
            "data": json.dumps(
                {
                    "token": "main_token",
                    "psql": {
                        "main": "postgres://main_user:pass@/discord",
                        "public": "postgres://main_user:pass@/public",
                        "web": "postgres://main_user:pass@/web",
                    },
                    "api-keys": {"google": "main_google", "wolfram": "main_wolfram"},
                    "approved_guilds": [],
                    "brains": "http://main_brains:7762",
                    "hostname": "https://www.main_example.com",
                    "paths": {"data": "/main_data", "upload": "/main_upload"},
                    "channels": {
                        "exceptions": 444276260164665321,
                        "default_voice": 453141750106882032,
                        "test": 453141750106882033,
                    },
                }
            ),
        },
        {
            "name": "docker",
            "type": "config",
            "data": json.dumps(
                {
                    "paths": {
                        "data": "/docker_data",
                        "upload": "/docker_upload",
                    },
                    "brains": "http://docker_brains:7762",
                }
            ),
        },
        {
            "name": "test",
            "type": "guild",
            "data": json.dumps(
                {
                    "id": 123,
                    "name": "guild name",
                }
            ),
        },
    ]
    mock_con = mocker.AsyncMock()
    mock_con.fetch.return_value = mock_pg_data
    mocker.patch("asyncpg.connect", return_value=mock_con)
    mocker.patch.object(PathsConfig, "_verify_path")
    config = await BotConfig.from_psql("", ["docker"])

    expected_psql = PostgresConfig()
    expected_psql.main = "postgres://main_user:pass@/discord"
    expected_psql.public = "postgres://main_user:pass@/public"
    expected_psql.web = "postgres://main_user:pass@/web"

    expected_config = BotConfig(
        token="main_token",
        psql=expected_psql,
        api_keys={"google": "main_google", "wolfram": "main_wolfram"},
        approved_guilds=[],
        brains="http://docker_brains:7762",
        guilds={},
        hostname="https://www.main_example.com",
        paths=PathsConfig(
            data="/docker_data",
            upload="/docker_upload",
        ),
        channels=ChannelsConfig(
            exceptions=444276260164665321,
            default_voice=453141750106882032,
            test=453141750106882033,
        ),
        http=HttpConfig(),
    )
    assert config.token == expected_config.token

    assert config.psql.main == expected_config.psql.main
    assert config.psql.public == expected_config.psql.public
    assert config.psql.web == expected_config.psql.web
    assert config.psql.live == expected_config.psql.live

    assert config.api_keys == expected_config.api_keys
    assert config.approved_guilds == expected_config.approved_guilds
    assert config.brains == expected_config.brains
    assert config.hostname == expected_config.hostname
    assert config.paths.data == expected_config.paths.data
    assert config.paths.upload == expected_config.paths.upload
    assert config.channels.exceptions == expected_config.channels.exceptions
    assert config.channels.default_voice == expected_config.channels.default_voice
    assert config.channels.test == expected_config.channels.test

    assert config.http.host == expected_config.http.host
    assert config.http.port == expected_config.http.port


@pytest.mark.asyncio
async def test_from_env_psql_override(mocker: pytest_mock.MockFixture):
    set_env = {
        "MAIN_DSN": "postgres://env_user:pass@/discord",
        "WEB_DSN": "postgres://env_user:pass@/web",
        "PUBLIC_DSN": "postgres://env_user:pass@/public",
        "GOOGLE_API_KEY": "env_google",
        "TOKEN": "env_token",
        "WOLFRAM_API_KEY": "env_wolfram",
        "MRBOT_HOSTNAME": "https://www.env_example.com",
        "DATA_PATH": "/env_data",
        "UPLOAD_PATH": "/env_upload",
        "BRAINS_PATH": "http://env_brains:7762",
    }
    for k, v in set_env.items():
        os.environ[k] = v
    mock_pg_data = [
        {
            "name": "main",
            "type": "config",
            "data": json.dumps(
                {
                    "token": "main_token",
                    "psql": {
                        "main": "postgres://main_user:pass@/discord",
                        "public": "postgres://main_user:pass@/public",
                        "web": "postgres://main_user:pass@/web",
                    },
                    "api-keys": {"google": "main_google", "wolfram": "main_wolfram"},
                    "approved_guilds": [],
                    "brains": "http://main_brains:7762",
                    "hostname": "https://www.main_example.com",
                    "paths": {"data": "/main_data", "upload": "/main_upload"},
                    "channels": {
                        "exceptions": 444276260164665321,
                        "default_voice": 453141750106882032,
                        "test": 453141750106882033,
                    },
                }
            ),
        },
        {
            "name": "docker",
            "type": "config",
            "data": json.dumps(
                {
                    "paths": {
                        "data": "/docker_data",
                        "upload": "/docker_upload",
                    },
                    "brains": "http://docker_brains:7762",
                }
            ),
        },
        {
            "name": "test",
            "type": "guild",
            "data": json.dumps(
                {
                    "id": 123,
                    "name": "guild name",
                }
            ),
        },
    ]
    mock_con = mocker.AsyncMock()
    mock_con.fetch.return_value = mock_pg_data
    mocker.patch("asyncpg.connect", return_value=mock_con)
    mocker.patch.object(PathsConfig, "_verify_path")
    config = await BotConfig.from_env_psql(["main", "docker"])

    expected_psql = PostgresConfig()
    expected_psql.main = "postgres://env_user:pass@/discord"
    expected_psql.public = "postgres://env_user:pass@/public"
    expected_psql.web = "postgres://env_user:pass@/web"

    expected_config = BotConfig(
        token="env_token",
        psql=expected_psql,
        api_keys={"google": "env_google", "wolfram": "env_wolfram"},
        approved_guilds=[],
        brains="http://env_brains:7762",
        guilds={},
        hostname="https://www.env_example.com",
        paths=PathsConfig(
            data="/env_data",
            upload="/env_upload",
        ),
        channels=ChannelsConfig(
            exceptions=444276260164665321,
            default_voice=453141750106882032,
            test=453141750106882033,
        ),
        http=HttpConfig(),
    )
    assert config.token == expected_config.token

    assert config.psql.main == expected_config.psql.main
    assert config.psql.public == expected_config.psql.public
    assert config.psql.web == expected_config.psql.web
    assert config.psql.live == expected_config.psql.live

    assert config.api_keys == expected_config.api_keys
    assert config.approved_guilds == expected_config.approved_guilds
    assert config.brains == expected_config.brains
    assert config.hostname == expected_config.hostname
    assert config.paths.data == expected_config.paths.data
    assert config.paths.upload == expected_config.paths.upload
    assert config.channels.exceptions == expected_config.channels.exceptions
    assert config.channels.default_voice == expected_config.channels.default_voice
    assert config.channels.test == expected_config.channels.test

    assert config.http.host == expected_config.http.host
    assert config.http.port == expected_config.http.port


@pytest.mark.asyncio
async def test_from_env_psql_simple(mocker: pytest_mock.MockFixture):
    set_env = {
        "MAIN_DSN": "postgres://env_user:pass@/discord",
        "WEB_DSN": "postgres://env_user:pass@/web",
        "PUBLIC_DSN": "postgres://env_user:pass@/public",
        "GOOGLE_API_KEY": "env_google",
        "TOKEN": "env_token",
        "WOLFRAM_API_KEY": "env_wolfram",
        "MRBOT_HOSTNAME": "https://www.env_example.com",
        "DATA_PATH": "/env_data",
        "UPLOAD_PATH": "/env_upload",
        "BRAINS_PATH": "http://env_brains:7762",
        "HTTP_SERVER_HOST": "0.0.0.0",
        "HTTP_SERVER_PORT": "8888",
    }
    for k, v in set_env.items():
        os.environ[k] = v
    mock_pg_data = [
        {
            "name": "main",
            "type": "config",
            "data": json.dumps(
                {
                    "approved_guilds": [111112222233333444],
                    "channels": {
                        "exceptions": 444276260164665321,
                        "default_voice": 453141750106882032,
                        "test": 453141750106882033,
                    },
                }
            ),
        },
        {
            "name": "test",
            "type": "guild",
            "data": json.dumps(
                {
                    "id": 123,
                    "name": "guild name",
                }
            ),
        },
    ]
    mock_con = mocker.AsyncMock()
    mock_con.fetch.return_value = mock_pg_data
    mocker.patch("asyncpg.connect", return_value=mock_con)
    mocker.patch.object(PathsConfig, "_verify_path")
    config = await BotConfig.from_env_psql(["main"])

    expected_psql = PostgresConfig()
    expected_psql.main = "postgres://env_user:pass@/discord"
    expected_psql.public = "postgres://env_user:pass@/public"
    expected_psql.web = "postgres://env_user:pass@/web"

    expected_config = BotConfig(
        token="env_token",
        psql=expected_psql,
        api_keys={"google": "env_google", "wolfram": "env_wolfram"},
        approved_guilds=[111112222233333444],
        brains="http://env_brains:7762",
        guilds={},
        hostname="https://www.env_example.com",
        paths=PathsConfig(
            data="/env_data",
            upload="/env_upload",
        ),
        channels=ChannelsConfig(
            exceptions=444276260164665321,
            default_voice=453141750106882032,
            test=453141750106882033,
        ),
        http=HttpConfig(host="0.0.0.0", port=8888),
    )
    assert config.token == expected_config.token

    assert config.psql.main == expected_config.psql.main
    assert config.psql.public == expected_config.psql.public
    assert config.psql.web == expected_config.psql.web
    assert config.psql.live == expected_config.psql.live

    assert config.api_keys == expected_config.api_keys
    assert config.approved_guilds == expected_config.approved_guilds
    assert config.brains == expected_config.brains
    assert config.hostname == expected_config.hostname
    assert config.paths.data == expected_config.paths.data
    assert config.paths.upload == expected_config.paths.upload
    assert config.channels.exceptions == expected_config.channels.exceptions
    assert config.channels.default_voice == expected_config.channels.default_voice
    assert config.channels.test == expected_config.channels.test

    assert config.http.host == expected_config.http.host
    assert config.http.port == expected_config.http.port
