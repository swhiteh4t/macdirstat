"""Pruebas de acciones sobre archivos, con papelera falsa (caso 20 del plan)."""

from __future__ import annotations

import os

import pytest

from app.models.file_node import NodeKind
from app.services import file_actions as file_actions_module
from app.services.file_actions import ActionResult, FileActions


@pytest.fixture
def tree_and_nodes(make_tree, scan_tree):
    root = make_tree(
        {
            "docs/informe.txt": 100,
            "docs/sub/nota.txt": 50,
            "enlace": "symlink:docs",
        }
    )
    result = scan_tree(root)
    nodes = {}
    for node in result.all_nodes:
        nodes[node.name] = node
    return result, nodes


def test_validate_ok(tree_and_nodes):
    _, nodes = tree_and_nodes
    actions = FileActions()
    assert actions.validate_for_trash(nodes["informe.txt"]) is None
    assert actions.validate_for_trash(nodes["sub"]) is None
    assert actions.validate_for_trash(nodes["enlace"]) is None


def test_validate_root_rejected(tree_and_nodes):
    result, _ = tree_and_nodes
    actions = FileActions()
    message = actions.validate_for_trash(result.root)
    assert message and "raíz" in message


def test_validate_missing_file(tree_and_nodes):
    _, nodes = tree_and_nodes
    actions = FileActions()
    informe = nodes["informe.txt"]
    os.remove(informe.path())
    message = actions.validate_for_trash(informe)
    assert message is not None


def test_validate_inode_changed(tree_and_nodes):
    _, nodes = tree_and_nodes
    actions = FileActions()
    informe = nodes["informe.txt"]
    path = informe.path()
    os.remove(path)
    with open(path, "wb") as handle:
        handle.write(b"nuevo contenido")
    message = actions.validate_for_trash(informe)
    assert message is not None and "cambió" in message


def test_trash_with_fake_fn(tree_and_nodes):
    _, nodes = tree_and_nodes
    calls = []

    def fake_trash(path: str) -> bool:
        calls.append(path)
        return True

    actions = FileActions(trash_fn=fake_trash)
    node = nodes["nota.txt"]
    result = actions.move_to_trash(node)
    assert isinstance(result, ActionResult) and result.ok
    assert calls == [node.path()]
    # El nodo no se muta aquí: la poda es responsabilidad de la ventana.
    assert node in nodes["sub"].children


def test_trash_failure_does_not_call_for_invalid(tree_and_nodes):
    _, nodes = tree_and_nodes
    calls = []

    def fake_trash(path: str) -> bool:
        calls.append(path)
        return True

    actions = FileActions(trash_fn=fake_trash)
    os.remove(nodes["informe.txt"].path())
    result = actions.move_to_trash(nodes["informe.txt"])
    assert not result.ok
    assert calls == []  # jamás se llamó a la papelera


def test_trash_fn_returning_false(tree_and_nodes):
    _, nodes = tree_and_nodes
    actions = FileActions(trash_fn=lambda path: False)
    result = actions.move_to_trash(nodes["nota.txt"])
    assert not result.ok and "Papelera" in result.message


def test_trash_fn_raising(tree_and_nodes):
    _, nodes = tree_and_nodes

    def boom(path: str):
        raise OSError("disco lleno")

    actions = FileActions(trash_fn=boom)
    result = actions.move_to_trash(nodes["nota.txt"])
    assert not result.ok and "disco lleno" in result.message


def test_open_missing_file(tree_and_nodes):
    _, nodes = tree_and_nodes
    actions = FileActions()
    os.remove(nodes["informe.txt"].path())
    result = actions.open_node(nodes["informe.txt"])
    assert not result.ok


def test_open_file_uses_desktop_services(tree_and_nodes, monkeypatch):
    _, nodes = tree_and_nodes
    opened = []

    class FakeDesktop:
        @staticmethod
        def openUrl(url):
            opened.append(url.toLocalFile())
            return True

    monkeypatch.setattr(file_actions_module, "QDesktopServices", FakeDesktop)
    actions = FileActions()
    result = actions.open_node(nodes["informe.txt"])
    assert result.ok
    assert opened == [nodes["informe.txt"].path()]


def test_reveal_missing_path(tmp_path):
    actions = FileActions()
    result = actions.reveal(str(tmp_path / "no-existe.txt"))
    assert not result.ok


def test_copy_path_uses_clipboard(qapp, tree_and_nodes, qtbot):
    _, nodes = tree_and_nodes
    actions = FileActions()
    result = actions.copy_path(nodes["informe.txt"])
    assert result.ok
    clipboard = qapp.clipboard()
    assert clipboard.text() == nodes["informe.txt"].path()


def test_default_trash_never_called_for_skipped_mount(tree_and_nodes):
    result, nodes = tree_and_nodes
    actions = FileActions(trash_fn=lambda path: True)
    # Simulamos un nodo de tipo punto de montaje.
    node = nodes["sub"]
    node.kind = NodeKind.SKIPPED_MOUNT
    message = actions.validate_for_trash(node)
    assert message is not None
