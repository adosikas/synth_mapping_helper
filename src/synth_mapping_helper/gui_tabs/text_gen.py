from nicegui import app, ui, elements
import numpy as np

from .. import synth_format, movement
from ..utils import parse_number
from .utils import GUITab, SMHInput, ParseInputError, info, error, write_clipboard
from .map_render import SettingsPanel, MapScene

FONT_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
DEFAULT_FONT = '{"BPM":76.0,"startMeasure":192.0,"startTime":2368.42114,"lenght":22105.2617,"notes":{"1344":[{"Position":[-0.407500029,0.00120002031,331.578949],"Segments":null,"Type":1}]},"effects":[],"jumps":[],"crouchs":[],"squares":[{"time":1088.0,"position":[0.00199997425,0.274200022,268.421051],"zRotation":45.0000038,"initialized":true},{"time":1216.0,"position":[0.00199997425,0.410700023,300.0],"zRotation":45.0000038,"initialized":true}],"triangles":[],"slides":[{"time":192.0,"slideType":2,"position":[0.274999976,0.137700021,47.3684235],"zRotation":352.499969,"initialized":true},{"time":194.0,"slideType":4,"position":[-0.274999976,0.137700021,47.86184],"zRotation":-352.499969,"initialized":true},{"time":193.0,"slideType":3,"position":[0.00199997425,-0.135299981,47.61513],"zRotation":269.999939,"initialized":true},{"time":257.0,"slideType":1,"position":[0.411499977,0.8202,63.4046059],"zRotation":284.999969,"initialized":true},{"time":258.0,"slideType":0,"position":[-0.680500031,-0.271799982,63.6513138],"zRotation":254.999939,"initialized":true},{"time":256.0,"slideType":3,"position":[-0.680500031,0.137700021,63.1578941],"zRotation":0.0,"initialized":true},{"time":320.0,"slideType":4,"position":[0.274999976,-0.271799982,78.9473648],"zRotation":90.0000153,"initialized":true},{"time":321.0,"slideType":2,"position":[-0.407500029,0.8202,79.19408],"zRotation":90.0,"initialized":true},{"time":385.0,"slideType":2,"position":[-0.274999976,-0.271799982,94.98355],"zRotation":-90.0000153,"initialized":true},{"time":386.0,"slideType":4,"position":[0.407500029,0.8202,95.23026],"zRotation":-90.0,"initialized":true},{"time":384.0,"slideType":3,"position":[-0.817000031,0.137700021,94.73685],"zRotation":0.0,"initialized":true},{"time":450.0,"slideType":4,"position":[0.411499977,1.22970009,111.019737],"zRotation":307.499969,"initialized":true},{"time":449.0,"slideType":2,"position":[-0.271000028,-0.6813,110.773026],"zRotation":232.499908,"initialized":true},{"time":451.0,"slideType":3,"position":[-0.134500027,0.137700021,111.266449],"zRotation":269.999939,"initialized":true},{"time":448.0,"slideType":3,"position":[-1.09,0.00120002031,110.526321],"zRotation":0.0,"initialized":true},{"time":514.0,"slideType":4,"position":[0.411499977,1.22970009,126.809212],"zRotation":307.499969,"initialized":true},{"time":512.0,"slideType":3,"position":[-1.09,0.00120002031,126.315788],"zRotation":0.0,"initialized":true},{"time":513.0,"slideType":2,"position":[-0.544,0.274200022,126.5625],"zRotation":232.499908,"initialized":true},{"time":642.0,"slideType":2,"position":[0.411499977,0.00120002031,158.388153],"zRotation":322.5,"initialized":true},{"time":641.0,"slideType":4,"position":[-0.407500029,0.00120002031,158.141449],"zRotation":37.5,"initialized":true},{"time":640.0,"slideType":3,"position":[0.00199997425,-0.135299981,157.89473],"zRotation":269.999939,"initialized":true},{"time":704.0,"slideType":3,"position":[0.00199997425,0.137700021,173.684219],"zRotation":0.0,"initialized":true},{"time":769.0,"slideType":3,"position":[0.821,0.274200022,189.7204],"zRotation":0.0,"initialized":true},{"time":768.0,"slideType":2,"position":[-0.544,-0.408299983,189.4737],"zRotation":209.999908,"initialized":true},{"time":832.0,"slideType":3,"position":[-0.817000031,0.137700021,205.263168],"zRotation":0.0,"initialized":true},{"time":833.0,"slideType":4,"position":[0.411499977,-0.271799982,205.509857],"zRotation":90.0000153,"initialized":true},{"time":834.0,"slideType":2,"position":[-0.271000028,0.8202,205.756577],"zRotation":90.0,"initialized":true},{"time":897.0,"slideType":3,"position":[0.00199997425,-0.8178,221.299332],"zRotation":269.999939,"initialized":true},{"time":896.0,"slideType":4,"position":[-0.271000028,0.137700021,221.052643],"zRotation":37.5,"initialized":true},{"time":1024.0,"slideType":3,"position":[-0.817000031,0.00120002031,252.631577],"zRotation":0.0,"initialized":true},{"time":1025.0,"slideType":4,"position":[1.367,0.137700021,252.878281],"zRotation":37.5,"initialized":true},{"time":1026.0,"slideType":2,"position":[-0.134500027,0.00120002031,253.125],"zRotation":7.500002,"initialized":true},{"time":1152.0,"slideType":3,"position":[-0.680500031,0.137700021,284.210541],"zRotation":0.0,"initialized":true},{"time":1153.0,"slideType":1,"position":[0.411499977,0.8202,284.457245],"zRotation":284.999969,"initialized":true},{"time":1280.0,"slideType":3,"position":[-0.680500031,0.137700021,315.789459],"zRotation":0.0,"initialized":true},{"time":1281.0,"slideType":1,"position":[0.548,0.9567,316.0362],"zRotation":269.999939,"initialized":true},{"time":1282.0,"slideType":4,"position":[0.411499977,-0.135299981,316.2829],"zRotation":82.5,"initialized":true},{"time":1217.0,"slideType":3,"position":[0.821,-0.6813,300.2467],"zRotation":37.5,"initialized":true},{"time":1344.0,"slideType":3,"position":[0.00199997425,0.137700021,331.578949],"zRotation":52.5000038,"initialized":true},{"time":1345.0,"slideType":2,"position":[-0.271000028,1.0932,331.825653],"zRotation":60.0000038,"initialized":true},{"time":1346.0,"slideType":4,"position":[0.411499977,-0.6813,332.0724],"zRotation":127.5,"initialized":true},{"time":1409.0,"slideType":3,"position":[0.0,0.0,347.6151],"zRotation":0.0,"initialized":true},{"time":1472.0,"slideType":1,"position":[0.548,-0.6813,363.1579],"zRotation":269.999939,"initialized":true},{"time":1473.0,"slideType":4,"position":[-0.544,0.137700021,363.4046],"zRotation":37.5,"initialized":true},{"time":1474.0,"slideType":2,"position":[0.548,0.137700021,363.651337],"zRotation":322.499969,"initialized":true},{"time":1536.0,"slideType":4,"position":[0.9575001,0.274200022,378.9474],"zRotation":187.5,"initialized":true},{"time":1537.0,"slideType":2,"position":[-0.9575001,0.274200022,379.194061],"zRotation":-187.5,"initialized":true},{"time":960.0,"slideType":3,"position":[0.00199997425,0.00120002031,236.8421],"zRotation":0.0,"initialized":true},{"time":961.0,"slideType":4,"position":[1.094,0.410700023,237.0888],"zRotation":239.999908,"initialized":true},{"time":962.0,"slideType":2,"position":[-1.09,0.410700023,237.335526],"zRotation":120.000084,"initialized":true},{"time":1600.0,"slideType":3,"position":[0.00200002571,0.3561,394.736847],"zRotation":180.0,"initialized":true},{"time":1601.0,"slideType":4,"position":[-0.4075,0.192299977,394.983551],"zRotation":59.99991,"initialized":true},{"time":1602.0,"slideType":2,"position":[0.4115,0.192299977,395.2303],"zRotation":300.0001,"initialized":true},{"time":1665.0,"slideType":3,"position":[0.00199997425,0.137700021,410.773],"zRotation":322.5,"initialized":true},{"time":1664.0,"slideType":3,"position":[0.00199997425,0.137700021,410.526337],"zRotation":37.5,"initialized":true},{"time":1408.0,"slideType":3,"position":[0.00199997425,1.0932,347.368439],"zRotation":269.999939,"initialized":true},{"time":1728.0,"slideType":3,"position":[0.411499977,-0.135299981,426.3158],"zRotation":329.999969,"initialized":true},{"time":1792.0,"slideType":3,"position":[0.138499975,0.00120002031,442.1053],"zRotation":314.999939,"initialized":true},{"time":1793.0,"slideType":4,"position":[0.274999976,0.9567,442.352],"zRotation":314.999969,"initialized":true},{"time":1794.0,"slideType":2,"position":[-0.271000028,-0.6813,442.598663],"zRotation":239.999908,"initialized":true},{"time":1729.0,"slideType":2,"position":[-0.407500029,0.410700023,426.5625],"zRotation":337.499878,"initialized":true},{"time":576.0,"slideType":1,"position":[0.411499977,-0.8178,142.10527],"zRotation":82.5,"initialized":true},{"time":577.0,"slideType":3,"position":[0.6845,-0.9543,142.351974],"zRotation":344.999969,"initialized":true},{"time":579.0,"slideType":0,"position":[-1.363,0.137700021,142.8454],"zRotation":0.0,"initialized":true},{"time":578.0,"slideType":4,"position":[0.274999976,1.22970009,142.598679],"zRotation":307.5,"initialized":true}],"lights":[]}'

def load_font(font_data: synth_format.DataContainer) -> dict[str, list["numpy array (1, 5)"]]:
    out: dict[str, list["numpy array (1, 5)"]] = {}
    for t, l in enumerate(FONT_LETTERS):
        try:
            out[l] = [font_data.walls[t]]  # expecting at least one wall
            for o in range(1, 64):  # while there are folliwing walls, add them
                if not t+o/64 in font_data.walls:
                    break
                out[l].append(font_data.walls[t+o/64])
        except Exception as e:
            error(f"Could not find letter '{l}'", exc=e, data={t: list(w[0]) for t, w in font_data.walls.items()})
    return out

def generate_text(
    data: synth_format.DataContainer, text: str,
    font: dict[str, list["numpy array (1, 5)"]],
    pos: "numpy array (3)", offset: "numpy array (3)", wall_spacing=1/64, center: bool=True,
    rotation: float=0, pivot: "numpy array (3)"=np.zeros((3,)),
    letter_rotation_start: float=0, letter_rotation: float=0, 
) -> None:
    # strip text to only contain font or spaces
    text = ''.join(l if l in font else " " for l in text)

    if center:  # modify start so the center lines up at start position
        mult = (len(text)-1)/2
        letter_rotation_start -= letter_rotation * mult
        if mult % 1:
            ratio = mult % 1
            pos = movement.rotate(pos, angle=-rotation*ratio, pivot=pivot)
            pos -= offset * ratio
            mult -= ratio
        for _ in range(int(mult)):
            pos = movement.rotate(pos, angle=-rotation, pivot=pivot)
            pos -= offset

    p = pos * [1,1,0]
    lr = letter_rotation_start
    for l in text:
        if l != " ":
            ws = font[l]
            for j, w in enumerate(ws):
                w = w.copy()  # copy the wall as template
                w[0,2] = j*wall_spacing  # replace time on template to match in-letter offset
                w = movement.rotate(w, lr)  # rotate template around itself
                w[0,:3]+= p  # add offset (x,y,time)
                data.walls[w[0,2]] = w  # add wall to output

        p += offset  # offset positon
        p = movement.rotate(p, angle=rotation, pivot=pivot)  # rotate position
        lr += letter_rotation

def make_input(label: str, value: str|float, storage_id: str, **kwargs) -> SMHInput:
    default_kwargs: dict[str, str|int] = {"tab_id": "text_gen", "width": 20}
    return SMHInput(storage_id=storage_id, label=label, default_value=value, **(default_kwargs|kwargs))

def _text_gen_tab() -> None:
    preview_scene: MapScene|None = None
    with ui.card():
        with ui.row():
            text_input = ui.input("Text", value="SAMPLE TEXT").props("dense").bind_value(app.storage.user, "text_gen_text")
            generate_button = ui.button("Generate & Copy", icon="play_arrow")
            with ui.dialog() as font_dialog, ui.card():
                with ui.button(icon="restore", on_click=lambda _: font_input.set_value(DEFAULT_FONT), color="negative").props("outline"):
                    ui.tooltip("Restore default font")
                ui.markdown("""
                    Expects clipboard 26 beats long (letters A-Z).  
                    Walls for each letter must start at each full beat, and then follow at 1/64 spacing after.

                    To edit:

                    * Triple-Click the text field below to select everything (or use CTRL-A)
                    * Copy to clipboard (CTRL-C) 
                    * Paste in Editor
                    * Edit walls
                    * Copy from the editor and paste the contents below (replace everything)
                """)
                def _is_valid_clipboard(s: str) -> bool:
                    try:
                        synth_format.ClipboardDataContainer.from_json(s)
                        return True
                    except Exception as e:
                        return False
                font_input = ui.input("Font (clipboard JSON)", value=DEFAULT_FONT, validation={"Invalid clipboard content": _is_valid_clipboard}).props("dense").classes("w-full h-full").bind_value(app.storage.user, "text_gen_font")
            def _open_font_dialog() -> None:
                font_dialog.open()
                font_input.update()
            with ui.button(icon="format_size", on_click=_open_font_dialog, color="info").classes("cursor-text").style("width: 36px"):
                ui.tooltip("Edit font")
        ui.separator()
        with ui.row():
            center_sw = ui.switch("Center", value=True).bind_value(app.storage.user, "text_gen_centered")
            wall_spacing = make_input("Wall Spacing", "1/64", "wall_spacing", suffix="b")
            offset_t = make_input("Letter Spacing", "1/16", "offset_t", suffix="b")
            rotation = make_input("Rotation", "-10", "rotation", suffix="°")
        ui.separator()
        with ui.row():
            with ui.column():
                ui.label("Start")
                start_x = make_input("X", "0", "start_x", suffix="sq")
                start_y = make_input("Y", "40", "start_y", suffix="sq")
            ui.separator().props("vertical")
            with ui.column():
                ui.label("Offset")
                offset_x = make_input("X", "15", "offset_x", suffix="sq")
                offset_y = make_input("Y", "0", "offset_y", suffix="sq")
            ui.separator().props("vertical")
            with ui.column():
                ui.label("Pivot")
                pivot_x = make_input("Pivot X", "0", "pivot_x", suffix="sq")
                pivot_y = make_input("Pivot Y", "0", "pivot_y", suffix="sq")
            ui.separator().props("vertical")
            with ui.column():
                ui.label("Letter Rotation")
                letter_rotation_start = make_input("Start", "0", "letter_rotation_start", suffix="°")
                letter_rotation = make_input("Angle", "-10", "letter_rotation", suffix="°")
    with ui.card():
        with ui.row():
            with ui.expansion("Preview Settings", icon="palette").props("dense"):
                sp = SettingsPanel()
                ui.separator()
                with ui.row():
                    ui.icon("preview", size="3em").tooltip("Change size and scaling of preview")
                    scene_width = make_input("Width", "800", "width", tab_id="preview", suffix="px", tooltip="Width of the preview in px")
                    scene_height = make_input("Height", "600", "height", tab_id="preview", suffix="px", tooltip="Height of the preview in px")
                    time_scale = make_input("Time Scale", "64", "time_scale", tab_id="preview", tooltip="Ratio between XY and time")
                    frame_length = make_input("Frame Length", "2", "frame_length", tab_id="preview", suffix="b", tooltip="Number of beats to draw frames for")
            apply_button = ui.button("Apply").props("outline")
            def _soft_refresh(copy:bool = True):
                data = synth_format.ClipboardDataContainer()
                try:
                    font_data = synth_format.ClipboardDataContainer.from_json(font_input.value)
                except Exception as exc:
                    error(f"Error parsing font data", exc, data=font_input.value)
                    return
                try:
                    generate_text(
                        data=data,
                        text=text_input.value.upper(),
                        font=load_font(font_data),
                        pos=np.array([start_x.parsed_value, start_y.parsed_value, 0]),
                        offset=np.array([offset_x.parsed_value, offset_y.parsed_value, offset_t.parsed_value]),
                        wall_spacing=wall_spacing.parsed_value,
                        center=center_sw.value,
                        rotation=rotation.parsed_value,
                        pivot=np.array([pivot_x.parsed_value, pivot_y.parsed_value, 0]),
                        letter_rotation_start=letter_rotation_start.parsed_value,
                        letter_rotation=letter_rotation.parsed_value,
                    )
                except ParseInputError as pie:
                    error(f"Error parsing text setting: {pie.input_id}", pie, data=pie.value)
                    return
                if copy:
                    write_clipboard(data.to_clipboard_json(realign_start=False))
                    info(
                        "Generated text",
                        caption=f"Copied {len(data.walls)} walls to clipboard",
                    )
                try:
                    preview_settings = sp.parse_settings()
                except ParseInputError as pie:
                    error(f"Error parsing preview setting: {pie.input_id}", pie, data=pie.value)
                    return
                if preview_scene is None:
                    draw_preview_scene.refresh()
                if preview_scene is not None:
                    preview_scene.render(data, preview_settings)
        @ui.refreshable
        def draw_preview_scene():
            nonlocal preview_scene
            try:
                w = int(scene_width.parsed_value)
                h = int(scene_height.parsed_value)
                l = int(frame_length.parsed_value)
                t = time_scale.parsed_value
            except ParseInputError as pie:
                error(f"Error parsing preview setting: {pie.input_id}", pie, data=pie.value)
                return
            preview_scene = MapScene(width=w, height=h, frame_length=l, time_scale=t, zoomout=40)
            _soft_refresh(False)
        draw_preview_scene()
        apply_button.on("click", draw_preview_scene.refresh)
        generate_button.on("click", _soft_refresh)

text_gen_tab = GUITab(
    name="text_gen",
    label="Text",
    icon="rtt",
    content_func=_text_gen_tab,
)
