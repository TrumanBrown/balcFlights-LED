import types
import unittest
from unittest.mock import patch

from balc_flights_led import privileges


class FakeOs:
    """Just enough of the os module to watch a privilege drop happen."""

    def __init__(self, uid: int = 0, gid: int = 0, groups: tuple[int, ...] = (0,)) -> None:
        self.uid = uid
        self.gid = gid
        self.groups = list(groups)
        self.calls: list[tuple[str, tuple[int, ...]]] = []
        self.fail_on: str | None = None
        self.ignore_setgroups = False

    def geteuid(self) -> int:
        return self.uid

    def getuid(self) -> int:
        return self.uid

    def getegid(self) -> int:
        return self.gid

    def getgid(self) -> int:
        return self.gid

    def getgroups(self) -> list[int]:
        return list(self.groups)

    def setgroups(self, groups: list[int]) -> None:
        self._record("setgroups", tuple(groups))
        if not self.ignore_setgroups:
            self.groups = list(groups)

    def setresgid(self, real: int, effective: int, saved: int) -> None:
        self._record("setresgid", (real, effective, saved))
        self.gid = effective

    def setresuid(self, real: int, effective: int, saved: int) -> None:
        self._record("setresuid", (real, effective, saved))
        self.uid = effective

    def _record(self, name: str, arguments: tuple[int, ...]) -> None:
        if name == self.fail_on:
            raise PermissionError(1, "Operation not permitted")
        self.calls.append((name, arguments))


def fake_pwd(uid: int = 1, gid: int = 1) -> types.ModuleType:
    module = types.ModuleType("pwd")
    accounts = {"daemon": types.SimpleNamespace(pw_uid=uid, pw_gid=gid)}

    def getpwnam(name: str) -> types.SimpleNamespace:
        return accounts[name]

    module.getpwnam = getpwnam
    return module


class PrivilegeTests(unittest.TestCase):
    def drop(self, fake: FakeOs, pwd: types.ModuleType | None = None) -> list[str]:
        events: list[str] = []
        with (
            patch.object(privileges, "os", fake),
            patch.dict("sys.modules", {"pwd": pwd or fake_pwd()}),
            patch.object(
                privileges,
                "_forbid_new_privileges",
                side_effect=lambda: events.append("no_new_privs"),
            ),
        ):
            privileges.drop_root()
        return events

    def test_root_drops_to_daemon_with_no_groups_and_no_way_back(self) -> None:
        fake = FakeOs()

        events = self.drop(fake)

        # Groups must go first: after setresuid the right to clear them is gone.
        self.assertEqual(
            fake.calls,
            [
                ("setgroups", ()),
                ("setresgid", (1, 1, 1)),
                ("setresuid", (1, 1, 1)),
            ],
        )
        self.assertEqual((fake.uid, fake.gid, fake.groups), (1, 1, []))
        self.assertEqual(events, ["no_new_privs"])

    def test_a_privileged_target_account_is_refused(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "privileged"):
            self.drop(FakeOs(), fake_pwd(uid=0, gid=0))

    def test_a_missing_target_account_is_an_error(self) -> None:
        empty = types.ModuleType("pwd")

        def getpwnam(name: str) -> None:
            raise KeyError(name)

        empty.getpwnam = getpwnam

        with self.assertRaisesRegex(RuntimeError, "no 'daemon' account"):
            self.drop(FakeOs(), empty)

    def test_a_failed_drop_is_an_error_rather_than_a_warning(self) -> None:
        fake = FakeOs()
        fake.fail_on = "setresuid"

        with self.assertRaisesRegex(RuntimeError, "could not drop root"):
            self.drop(fake)

    def test_a_lingering_root_group_is_caught(self) -> None:
        fake = FakeOs()
        fake.ignore_setgroups = True

        with self.assertRaisesRegex(RuntimeError, "root group"):
            self.drop(fake)

    def test_an_unprivileged_process_is_left_alone(self) -> None:
        fake = FakeOs(uid=1000, gid=1000, groups=(1000, 999))

        events = self.drop(fake)

        self.assertEqual(fake.calls, [])
        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()
