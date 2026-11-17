"""Deterministic service/package target extraction (no guessing)."""

from app.ops.targets import extract_package, extract_service_target


def test_app_worker_wins_over_supervisor_and_records_manager() -> None:
    target = extract_service_target("app-worker 被 Supervisor 反复重启")
    assert target.name == "app-worker"
    assert target.manager == "supervisor"
    assert target.manager_only is False


def test_manager_only_does_not_become_a_service_name() -> None:
    target = extract_service_target("Supervisor 服务频繁退出")
    assert target.name is None
    assert target.manager == "supervisor"
    assert target.manager_only is True


def test_explicit_unit_file_has_priority() -> None:
    target = extract_service_target("app-worker 和 nginx.service 都有问题，先看 nginx.service")
    assert target.name == "nginx"


def test_unknown_service_is_not_extracted() -> None:
    assert extract_service_target("mysqld 服务启动失败").name is None


def test_rpm_file_name_is_trimmed_to_package() -> None:
    assert extract_package("安装 nginx-1.26.1-1.oe2403.x86_64.rpm") == "nginx"


def test_arbitrary_english_token_is_not_a_package() -> None:
    assert extract_package("服务器安装某个 RPM 软件包时出现依赖冲突") is None


def test_explicit_rpm_command_argument_is_a_package() -> None:
    assert extract_package("rpm -q redis 的依赖是什么") == "redis"


def test_supervisor_as_manager_is_not_a_package() -> None:
    assert extract_package("app-worker 被 Supervisor 反复重启") is None
