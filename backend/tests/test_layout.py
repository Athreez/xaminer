import importlib


def test_packages_import() -> None:
    for name in [
        "app",
        "domain_core",
        "cli",
        "workers.app_worker",
        "workers.exec_worker",
        "workers.inference_worker",
    ]:
        importlib.import_module(name)
