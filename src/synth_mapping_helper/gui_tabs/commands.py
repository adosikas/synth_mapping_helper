from argparse import ArgumentError

from nicegui import app, events, ui

from .utils import *
from .. import cli

DEFAULT_PRESETS = {
    "Merge Rails": "--merge-rails",
    "Split Rails": "--split-rails",
    "Spikify": """
        # add up-down spikes every 1/4 beat to a rail
        # See https://github.com/adosikas/synth_mapping_helper/wiki/Rail-Options#spikes
        --interpolate=1/4 --spikes=2 --radius=2 --start-angle=90""",
    "Spiralize": """
        # turn a rail into a spiral around the original path, with one rotation per beat and starting top/right
        # See https://github.com/adosikas/synth_mapping_helper/wiki/Rail-Options#spiral
        --interpolate=1/8 --spiral=8 --radius=2 --start-angle=45""",
    "Parallels": """
        # create parallel rails to the input, with 2 sq distance. left/right notes are added additionally to the left/right of the right/left notes, single/both notes are "split"
        # There will be conflicts when you have multiple notes or start of rails at the same time. Check the wiki on how it decides on priority or just avoid that.
        # See https://github.com/adosikas/synth_mapping_helper/wiki/Pre--and-Post-Processing-Options#create-parallel-patterns
        --parallels=2""",
    "Autostack circular": """
        # automatically detect rotation & outset between the first two objects of the same type and continue the pattern for a total of 16 (first + 15 stacked copies)
        # See https://github.com/adosikas/synth_mapping_helper/wiki/Movement-options#autostacking
        --autostack=OUTSET --stack-count=15""",
    "Autostack linear": """
        # automatically detect offset between the first two objects of the same type and continue the pattern for 8 measures
        # See https://github.com/adosikas/synth_mapping_helper/wiki/Movement-options#autostacking
        --autostack=OFFSET --stack-duration=8""",
    "Autostack spiral walls": """
        # automatically detect spiral shape from first two walls and continue the patterns for 8 measures
        # you can have notes and other walls in the pattern, but ensure the first PAIR of objects is walls
        # See https://github.com/adosikas/synth_mapping_helper/wiki/Movement-options#autostacking
        --autostack=SPIRAL --stack-duration=8""",
    "Rail to notestack": """
        # convert rails to notestacks with 1/16 spacing
        # you can also do "--rails-to-singles=1" to KEEP the rail instead of removing it
        # See https://github.com/adosikas/synth_mapping_helper/wiki/Pre--and-Post-Processing-Options#convert-rails-into-single-notes
        --interpolate=1/16 --rails-to-singles""",
}

# strip newlines and tabs
DEFAULT_PRESETS = {
    k: '\n'.join(l.strip() for l in v.splitlines() if l)
    for k,v in DEFAULT_PRESETS.items()
}

def _command_tab() -> None:
    presets: dict[str, str] = {}

    loaded_presets = app.storage.user.get("command_presets")
    if loaded_presets:
        logger.info(f"Loaded {len(loaded_presets)} presets")
        presets = loaded_presets
    else:
        logger.info(f"No presets saved, loading defaults")
        presets = DEFAULT_PRESETS.copy()

    @ui.refreshable
    def quick_run_buttons() -> None:
        for p in presets:
            ui.button(p, icon="fast_forward", on_click=run_preset).tooltip(f"Load and immediately execute {p} preset")

    def presets_updated() -> None:
        preset_selector.set_options(list(presets))
        quick_run_buttons.refresh()

    @handle_errors
    def load_commands(e: events.UploadEventArguments) -> None:
        upl: ui.upload = e.sender  # type: ignore
        upl.reset()
        data = e.content.read()
        try:
            presets[e.name] = data.decode()
            presets_updated()
            preset_selector.value = e.name  # this also loads the content
        except UnicodeDecodeError as ude:
            raise PrettyError(msg=f"Error reading commands from {e.name}", exc=ude, data=data[ude.start: ude.end].hex())

    @handle_errors
    def run_command() -> None:
        p = cli.get_parser()
        p.exit_on_error = False
        commands = command_input.value.splitlines()
        count = 0
        for i, line in enumerate(commands):
            if line.startswith("#"):
                continue
            args = line.split(" ")
            if not count and use_orig_cb.value:
                args.append("--use-original")
            if mirror_left_cb.value:
                args.append("--mirror-left")

            try:
                opts, remaining = p.parse_known_args(args)
            except ArgumentError as ae:
                raise PrettyError(msg=f"Error parsing line {i+1}", exc=ae, data=line) from ae
            if remaining:
                raise PrettyError(msg=f"Unknown arguments in line {i+1}", data=remaining)
            try:
                cli.main(opts)
            except RuntimeError as re:
                raise PrettyError(msg=f"Error running line {i+1}", exc=re, data=line) from re
            count += 1
        else:
            if preset_selector.value:
                message = f"Sucessfully executed preset '{preset_selector.value}' ({count} command{'s'*(count>1)})"
            else:
                message = f"Sucessfully executed {count} command{'s'*(count>1)}"
            info(message)

    def run_preset(e: events.ClickEventArguments) -> None:
        btn: ui.button = e.sender  # type: ignore
        preset_selector.value = btn.text
        run_command()

    def restore_presets() -> None:
        presets.update(DEFAULT_PRESETS)
        presets_updated()
        prev_val = preset_selector.value
        preset_selector.value = None
        if prev_val in presets:
            preset_selector.value = prev_val
        info("Restored default presets")

    def save_presets() -> None:
        app.storage.user["command_presets"] = presets
        info(f"Saved {len(presets)} presets")

    def add_preset() -> None:
        presets[add_preset_name.value] = command_input.value
        presets_updated()
        preset_selector.value = add_preset_name.value
        add_dialog.close()

    with ui.dialog() as add_dialog, ui.card():
        add_preset_name = ui.input("Preset name", value="Untitled").props("autofocus")
        with ui.row():
            ui.button("Cancel", icon="cancel", on_click=add_dialog.close).props("flat")
            ui.button("Add", icon="add", color="green", on_click=add_preset)

    def delete_preset(e: events.ClickEventArguments) -> None:
        del presets[preset_selector.value]
        presets_updated()
        preset_selector.value = None
        remove_dialog.close()

    with ui.dialog() as remove_dialog, ui.card():
        remove_confirmation_label = ui.label("Really delete?")
        with ui.row():
            ui.button("Cancel", icon="cancel", on_click=remove_dialog.close).props("flat")
            ui.button("Delete", icon="delete", color="red", on_click=delete_preset)

    with ui.card():
        with ui.row():
            with ui.select(list(presets), label="Preset Name", with_input=True).props("dense") as preset_selector:
                ui.tooltip("Select a preset")
            preset_selector.bind_value(app.storage.user, "command_preset")
            with ui.button(icon="delete", color="red", on_click=remove_dialog.open).classes("my-auto").bind_enabled_from(preset_selector, "value"):
                ui.tooltip("Delete current preset")
            with ui.button(icon="add", color="green", on_click=add_dialog.open).classes("my-auto") as add_button:
                ui.tooltip("Add current command as preset")
            ui.separator().props("vertical")
            with ui.button(icon="save", on_click=save_presets).props("outline").classes("my-auto"):
                ui.tooltip("Store presets")
            ui.upload(label="Import files", auto_upload=True, multiple=True, on_upload=load_commands).props('color="positive" flat').classes("w-40")
            with ui.button(icon="post_add", on_click=restore_presets, color="red").props("outline").classes("my-auto"):
                ui.tooltip("Restore default presets")
        command_input = ui.textarea("Commands", placeholder="--offset=1,0,0").props("outlined").classes("w-full")
        command_input.bind_value(app.storage.user, "command_input")

        # clear preset name when content changes
        def _clear_preset(e: events.ValueChangeEventArguments) -> None:
            if presets.get(preset_selector.value) != e.value:
                preset_selector.set_value(None)
        command_input.on_value_change(_clear_preset)
        # set content when preset changes to a valid preset
        def _load_preset(e: events.ValueChangeEventArguments) -> None:
            preset = e.value
            if preset and preset in presets:
                command_input.set_value(presets[preset])
        preset_selector.on_value_change(_load_preset)
    
        preset_selector.bind_value_to(remove_confirmation_label, "text", forward=lambda v: f"Really delete '{v}'?")
        add_button.bind_enabled_from(command_input, "value")

        with ui.row():
            ui.button("Execute", icon="play_arrow", on_click=run_command).bind_enabled_from(command_input, "value").tooltip("Execute commands and copy result to clipboard")
            with ui.checkbox("Use original JSON") as use_orig_cb:
                wiki_reference("Miscellaneous-Options#use-original-json")
            with ui.checkbox("Mirror for left hand") as mirror_left_cb:
                wiki_reference("Miscellaneous-Options#mirror-operations-for-left-hand")
        ui.separator()
    
        ui.label("Quick run:").tooltip("Stored presets will show here")
        with ui.row():
            quick_run_buttons()

command_tab = GUITab(
    name="command",
    label="Commands",
    icon="play_arrow",
    content_func=_command_tab,
)
