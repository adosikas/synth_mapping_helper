from nicegui import app, events, ui

from .utils import *

presets = {
    "Merge Rails": "--merge-rails",
    "Split Rails": "--split-rails",
}

def command_tab():
    @ui.refreshable
    def quick_run_buttons():
        for p in presets:
            ui.button(p, icon="fast_forward", on_click=run_preset)

    def presets_updated():
        preset_selector.set_options(list(presets))
        quick_run_buttons.refresh()

    def load_commands(e: events.UploadEventArguments):
        data = e.content.read()
        try:
            presets[e.name] = data.decode()
            presets_updated()
            preset_selector.value = e.name  # this also loads the content
        except UnicodeDecodeError as exc:
            msg = f"Error reading commands from {e.name}"
            logger.error(msg)
            ui.notify(msg, type="negative")
        e.sender.reset()

    def run_command():
        p = cli.get_parser()
        p.exit_on_error = False
        commands = command_input.value.splitlines()
        count = 0
        for i, line in enumerate(commands):
            if line.startswith("#"):
                continue
            error = None
            args = line.split(" ")
            if not count and use_orig_cb.value:
                args.append("--use-original")
            if mirror_left_cb.value:
                args.append("--mirror-left")

            try:
                opts, remaining = p.parse_known_args(args)
            except ArgumentError as exc:
                error = f"Error parsing line {i+1}: {exc!s}"
            else:
                if remaining:
                    error = f"Unknown arguments in line {i+1}: {remaining}"
                else:
                    try:
                        cli.main(opts)
                    except RuntimeError as exc:
                        error = f"Error running line {i+1}: {exc!r}"
            if error:
                logger.error(error)
                ui.notify(error, type="negative")
                break
            count += 1
        else:
            if preset_selector.value:
                message = f"Sucessfully executed preset '{preset_selector.value}' ({count} command{'s'*(count>1)})"
            else:
                message = f"Sucessfully executed {count} command{'s'*(count>1)}"
            logger.info(message)
            ui.notify(message, type="positive")

    def run_preset(e: events.ClickEventArguments):
        preset_selector.value = e.sender.text
        run_command()

    def load_presets():
        global presets
        loaded_presets = app.storage.user.get("command_presets")
        if loaded_presets:
            presets = {**loaded_presets}  # copy
            presets_updated()
            logger.info(f"Loaded {len(presets)} presets")

    def save_presets():
        app.storage.user["command_presets"] = presets
        logger.info(f"Saved {len(presets)} presets")

    def add_preset():
        presets[add_preset_name.value] = command_input.value
        presets_updated()
        preset_selector.value = add_preset_name.value
        add_dialog.close()

    with ui.dialog() as add_dialog, ui.card():
        add_preset_name = ui.input("Preset name", value="Untitled")
        with ui.row():
            ui.button("Cancel", icon="cancel", on_click=add_dialog.close).props("flat")
            ui.button("Add", icon="add", color="green", on_click=add_preset)

    def delete_preset(e: events.ClickEventArguments):
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
            with ui.select(list(presets), with_input=True) as preset_selector:
                ui.tooltip("Select a preset")
            preset_selector.bind_value(app.storage.user, "command_preset")
            with ui.button(icon="delete", color="red", on_click=remove_dialog.open).classes("my-auto").bind_enabled_from(preset_selector, "value"):
                ui.tooltip("Delete current preset")
            with ui.button(icon="add", color="green", on_click=add_dialog.open).classes("my-auto") as add_button:
                ui.tooltip("Add current command as preset")
            ui.upload(label="Add from file", auto_upload=True, multiple=True, on_upload=load_commands).classes("h-14 w-40")
            with ui.button(icon="restore", on_click=load_presets).classes("my-auto"):
                ui.tooltip("Restore presets")
            with ui.button(icon="save", on_click=save_presets).classes("my-auto"):
                ui.tooltip("Store presets")
        ui.separator()
        command_input = ui.textarea("Commands", placeholder="--offset=1,0,0", on_change=lambda e: presets.get(preset_selector.value) == e.value or preset_selector.set_value(None)).props("autogrow").classes("w-full")
        command_input.bind_value(app.storage.user, "command_input")
        preset_selector.bind_value_to(command_input, forward=lambda v: v and presets.get(v))
        preset_selector.bind_value_to(remove_confirmation_label, "text", forward=lambda v: f"Really delete '{v}'?")
        add_button.bind_enabled_from(command_input, "value")

        with ui.row():
            ui.button("Execute", icon="play_arrow", on_click=run_command).bind_enabled_from(command_input, "value")
            with ui.checkbox("Use original JSON") as use_orig_cb:
                wiki_reference("Miscellaneous-Options#use-original-json")
            with ui.checkbox("Mirror for left hand") as mirror_left_cb:
                wiki_reference("Miscellaneous-Options#mirror-operations-for-left-hand")
        ui.separator()
    
        ui.label("Quick run:")
        with ui.row():
            quick_run_buttons()

    load_presets()