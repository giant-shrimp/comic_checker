import importlib


def test_import_gui_module():
    module = importlib.import_module("comic_checker.gui")
    assert hasattr(module, "App")
    assert hasattr(module, "main")
