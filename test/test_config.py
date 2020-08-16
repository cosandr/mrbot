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
    with open('test_config_guild.json', 'r') as f:
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
