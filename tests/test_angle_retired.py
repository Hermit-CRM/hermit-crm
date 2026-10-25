"""Angle was retired (format 18). What an older folder may still hold must load
and run without errors or warnings, and a saved view that names `angle` fails as
gently as any other unknown column."""

from hermitcrm import adjust, cli, outreach, routines
from hermitcrm.datafolder import init_folder
from hermitcrm.store import Store, load_config

ITEM = "2026-10-16T0900-email-lindenhof-data-mara-keller"


def demo(tmp_path):
    root = init_folder(tmp_path / "crm", demo=True)
    return root, Store(root)


def test_an_old_item_with_an_angle_key_reads_and_the_key_is_not_written_back(tmp_path):
    item = outreach.Item(id=ITEM, state="drafted", company="lindenhof-data",
                         contact="mara-keller", body="Hi Mara,\n\nA first message.\n\nSam\n")
    text = outreach.item_text(item).replace("kind:", "angle: hook\nkind:", 1)
    assert "angle: hook" in text
    again = outreach.item_from_text(ITEM, text)
    assert again.body == item.body and not hasattr(again, "angle")
    assert "angle" not in outreach.item_text(again)


def test_the_old_config_keys_are_read_and_ignored(tmp_path):
    root, store = demo(tmp_path)
    config = root / "config.toml"
    config.write_text(config.read_text(encoding="utf-8")
                      + '\noutreach_angles = ["scale", "hook", "custom"]\n'
                        'learning_angle_sampling = true\n', encoding="utf-8")
    assert load_config(root)["learning_angle_sampling"] is True
    assert [p for p in adjust.validate_config(root) if "angle" in p] == []
    text, code = cli.cmd_check(Store(root))
    assert "angle" not in text.lower()


def test_a_saved_dashboard_and_layout_naming_angle_fail_gently(tmp_path):
    root, store = demo(tmp_path)
    (root / "dashboards").mkdir(exist_ok=True)
    (root / "dashboards" / "old.toml").write_text(
        'title = "Old"\n[[widget]]\ntype = "list"\nscope = "messages"\n'
        'columns = ["subject", "angle"]\nsort = "angle"\n', encoding="utf-8")
    found = adjust.all_problems(root)
    assert any("old.toml" in p and "unknown column angle" in p for p in found)
    page = cli.cmd_check(Store(root))[0]
    assert "unknown column angle" in page


def test_a_routine_filter_on_angle_is_an_unknown_column(tmp_path):
    root, store = demo(tmp_path)
    _, problems = routines._check_filters({"angle": "hook"}, routines.columns(root, "companies"))
    assert any("unknown column angle" in p for p in problems)
